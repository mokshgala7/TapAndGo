import os
from typing import Optional
from dotenv import load_dotenv

# Search and load environment variables from all candidate .env paths
possible_env_paths = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'),
    os.path.join(os.getcwd(), '.env'),
    os.path.join(os.getcwd(), 'backend', '.env'),
]

# Automated tests must never read real credentials or reach a real database or
# provider. tests/conftest.py sets TAPGO_TESTING=1 before anything is imported.
if os.getenv("TAPGO_TESTING") != "1":
    for p in possible_env_paths:
        if os.path.exists(p):
            load_dotenv(dotenv_path=p, override=True)

# Sender used when neither SES_FROM_EMAIL nor AWS_SES_FROM_EMAIL is set. It belongs to the
# domain that has a verified SES identity (thetapandgo.in, DKIM aligned), so a missing
# variable can never fall back to a personal mailbox. There is no mailbox behind it:
# replies are routed through SES_REPLY_TO_EMAIL.
DEFAULT_SES_FROM = "Tap & Go <noreply@thetapandgo.in>"


def _ses_from_setting() -> str:
    """SES_FROM_EMAIL, else the AWS_SES_FROM_EMAIL alias, else the default. Blank or
    whitespace-only values count as unset (they must not produce an empty sender)."""
    for name in ("SES_FROM_EMAIL", "AWS_SES_FROM_EMAIL"):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return DEFAULT_SES_FROM


# The development default of SECRET_KEY (committed in this repo, so it is not a secret).
DEV_SECRET_KEY = "tapgo_super_secret_jwt_key_2026"


class Settings:
    @property
    def REVIEW_DEMO_MODE(self) -> bool:
        """Run the hosted demonstration environment from a resettable snapshot."""
        return os.getenv("REVIEW_DEMO_MODE", "false").lower() in ("1", "true", "yes")

    @property
    def IS_PRODUCTION(self) -> bool:
        """Determines if the application is running in a production cloud environment (e.g. Render)."""
        return bool(
            os.getenv("RENDER")
            or os.getenv("RENDER_SERVICE_ID")
            or os.getenv("RENDER_INSTANCE_ID")
            or os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
            or os.getenv("ENV", "").lower() in ("production", "prod")
        )

    @property
    def DB_HOST(self) -> str:
        return os.getenv("DB_HOST", "localhost")

    @property
    def DB_PORT(self) -> int:
        return int(os.getenv("DB_PORT", 3306))

    @property
    def DB_USER(self) -> str:
        return os.getenv("DB_USER", "root")

    @property
    def DB_PASSWORD(self) -> str:
        return os.getenv("DB_PASSWORD", "")

    @property
    def DB_NAME(self) -> str:
        return os.getenv("DB_NAME", "tapgo")

    @property
    def SECRET_KEY(self) -> str:
        return os.getenv("SECRET_KEY", DEV_SECRET_KEY)

    @property
    def ADMIN_EMAIL(self) -> str:
        return os.getenv("ADMIN_EMAIL", "admin@example.com")

    @property
    def ADMIN_PASSWORD(self) -> str:
        return os.getenv("ADMIN_PASSWORD", "admin@123")

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        return os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

    @property
    def PUBLIC_WEB_URL(self) -> str:
        """Website origin that QR payment links point at (no trailing slash)."""
        return os.getenv("PUBLIC_WEB_URL", "https://www.thetapandgo.in").strip().rstrip("/")

    # --- Amazon SES Configuration (HTTPS API via boto3) ---
    @property
    def AWS_ACCESS_KEY_ID(self) -> str:
        return os.getenv("AWS_ACCESS_KEY_ID", "").strip()

    @property
    def AWS_SECRET_ACCESS_KEY(self) -> str:
        return os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()

    @property
    def AWS_REGION(self) -> str:
        return os.getenv("AWS_REGION", "ap-south-1").strip()

    @property
    def SES_FROM_EMAIL(self) -> str:
        raw = _ses_from_setting()
        if "<" in raw:
            return raw
        return f"Tap & Go <{raw}>"

    @property
    def SES_SENDER_EMAIL(self) -> str:
        raw = _ses_from_setting()
        if "<" in raw and ">" in raw:
            return raw.split("<")[1].split(">")[0].strip()
        return raw

    @property
    def SES_REPLY_TO_EMAIL(self) -> Optional[str]:
        raw = os.getenv("SES_REPLY_TO_EMAIL", "").strip()
        return raw if raw else None

    # --- Local development SMTP fallback settings (environment variables only, no hardcoded secrets) ---
    @property
    def SMTP_HOST(self) -> str:
        return os.getenv("SMTP_HOST", "").strip()

    @property
    def SMTP_PORT(self) -> int:
        val = os.getenv("SMTP_PORT", "587").strip()
        try:
            return int(val)
        except ValueError:
            return 587

    # --- Supabase Storage Configuration ---
    @property
    def SUPABASE_URL(self) -> str:
        return os.getenv("SUPABASE_URL", "").strip()

    @property
    def SUPABASE_SERVICE_ROLE_KEY(self) -> str:
        return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    @property
    def SUPABASE_STORAGE_BUCKET(self) -> str:
        return os.getenv("SUPABASE_STORAGE_BUCKET", "verification-documents").strip()

    @property
    def SMTP_USER(self) -> str:
        return os.getenv("SMTP_USER", "").strip()

    @property
    def SMTP_PASSWORD(self) -> str:
        return os.getenv("SMTP_PASSWORD", "").strip()

    @property
    def SMTP_FROM_EMAIL(self) -> str:
        raw = os.getenv("SMTP_FROM_EMAIL", "").strip()
        if raw:
            return raw
        if self.SMTP_USER:
            return f"Tap & Go <{self.SMTP_USER}>"
        return ""

    @property
    def RESEND_API_KEY(self) -> str:
        """Optional HTTPS email provider key used by the hosted review demo."""
        return os.getenv("RESEND_API_KEY", "")

    @property
    def RESEND_FROM_EMAIL(self) -> str:
        return os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    @property
    def DATABASE_URL(self) -> str:
        """Database connection URI supporting Supabase PostgreSQL and fallback drivers."""
        raw = (os.getenv("DATABASE_URL") or "").strip()
        if raw:
            # Handle PostgreSQL schemes:
            # SQLAlchemy 2.x requires a specific driver prefix (postgresql+psycopg2://)
            if raw.startswith("postgres://"):
                return "postgresql+psycopg2://" + raw[len("postgres://"):]
            if raw.startswith("postgresql://"):
                return "postgresql+psycopg2://" + raw[len("postgresql://"):]
            if raw.startswith("mysql://"):
                return "mysql+pymysql://" + raw[len("mysql://"):]
            return raw

        # Fallback: build from individual DB_* components
        is_postgres = (
            self.DB_PORT in (5432, 6543)
            or self.DB_USER == "postgres"
            or os.getenv("DB_DIALECT", "").lower() in ("postgres", "postgresql")
        )
        driver = "postgresql+psycopg2" if is_postgres else "mysql+pymysql"
        auth = f"{self.DB_USER}:{self.DB_PASSWORD}" if self.DB_PASSWORD else self.DB_USER
        return f"{driver}://{auth}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"



    @property
    def ALLOW_MOCK_PAYMENTS(self) -> bool:
        """Development-only: allow fake Razorpay orders when no keys are set.
        Ignored (always False) in a production environment."""
        if self.IS_PRODUCTION:
            return False
        return os.getenv("ALLOW_MOCK_PAYMENTS", "false").strip().lower() in ("1", "true", "yes")

    @property
    def RAZORPAY_LIVE_ENABLED(self) -> bool:
        """Live-mode keys (rzp_live_*) are allowed by default. Set RAZORPAY_LIVE_ENABLED=false
        to switch live payments off without removing the keys."""
        return os.getenv("RAZORPAY_LIVE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

    @property
    def RAZORPAY_KEY_ID(self) -> str:
        return os.getenv("RAZORPAY_KEY_ID", "")

    @property
    def RAZORPAY_KEY_SECRET(self) -> str:
        return os.getenv("RAZORPAY_KEY_SECRET", "")

    @property
    def RAZORPAY_WEBHOOK_SECRET(self) -> str:
        return os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    @property
    def PAYMENT_PROVIDER(self) -> str:
        return os.getenv("PAYMENT_PROVIDER", "RAZORPAY")

    @property
    def PAYMENT_GATEWAY_PROVIDER(self) -> str:
        return os.getenv("PAYMENT_GATEWAY_PROVIDER", "RAZORPAY")


    @property
    def DEMO_MODE(self) -> bool:
        return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")

    @property
    def NFC_CARD_PRICE(self) -> float:
        """Standard customer-facing price of one Tap&Go NFC card (₹50)."""
        return float(os.getenv("NFC_CARD_PRICE", "50.0"))

    @property
    def LOCAL_DELIVERY_CHARGE(self) -> float:
        """Delivery charge for Mumbai local metro region."""
        return float(os.getenv("LOCAL_DELIVERY_CHARGE", "40.0"))

    @property
    def REGIONAL_DELIVERY_CHARGE(self) -> float:
        """Delivery charge for Maharashtra regional area outside Mumbai."""
        return float(os.getenv("REGIONAL_DELIVERY_CHARGE", "60.0"))

    @property
    def NATIONAL_DELIVERY_CHARGE(self) -> float:
        """Delivery charge for Rest of India national delivery."""
        return float(os.getenv("NATIONAL_DELIVERY_CHARGE", "90.0"))

settings = Settings()
