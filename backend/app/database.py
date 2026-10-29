import os
import shutil
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

def get_engine():
    """Create the SQLAlchemy engine targeting PostgreSQL (Supabase) or MySQL.

    If REVIEW_DEMO_MODE is true, intentionally runs from the reviewer snapshot.
    In normal production operation (REVIEW_DEMO_MODE=false), connects to the configured
    database and FAILS LOUDLY on connection errors — never silently falling back to SQLite.
    """
    if settings.REVIEW_DEMO_MODE:
        project_root = Path(__file__).resolve().parent.parent
        seed_database = project_root / "reviewer_seed" / "tapgo-reviewer.db"
        runtime_database = Path(os.getenv("REVIEW_DEMO_DATABASE_PATH", "/tmp/tapgo-reviewer.db"))

        if not seed_database.exists():
            raise RuntimeError(f"Reviewer database snapshot is missing: {seed_database}")

        if not runtime_database.exists():
            runtime_database.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(seed_database, runtime_database)
            print("[Database] Initialized runtime database from reviewer seed snapshot.")
        else:
            print("[Database] Using existing live runtime database.")
        return create_engine(
            f"sqlite:///{runtime_database}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

    db_url = settings.DATABASE_URL

    # Safety net: a test run may only ever use SQLite (never a real database).
    if os.getenv("TAPGO_TESTING") == "1" and not db_url.startswith("sqlite"):
        raise RuntimeError("TAPGO_TESTING=1 requires a sqlite DATABASE_URL; refusing to connect.")

    # Allow explicit SQLite only if explicitly designated in DATABASE_URL
    if db_url.startswith("sqlite"):
        print("[Database] Explicitly using SQLite database file from configuration.")
        if ":memory:" in db_url:
            # One shared connection: with the default per-thread pool an in-memory
            # database silently vanishes when worker threads are evicted.
            from sqlalchemy.pool import StaticPool
            return create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool, echo=False)
        return create_engine(db_url, connect_args={"check_same_thread": False}, echo=False)

    # PostgreSQL (Supabase) Connection
    if db_url.startswith("postgresql"):
        connect_args = {}
        # Apply SSL mode required by Supabase unless on localhost or already in URL
        if "sslmode=" not in db_url and not any(h in db_url for h in ("localhost", "127.0.0.1")):
            connect_args["sslmode"] = "require"

        try:
            eng = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=5,
                max_overflow=10,
                connect_args=connect_args,
                echo=False,
            )
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("[Database] Connected to PostgreSQL (Supabase) successfully.")
            return eng
        except Exception as e:
            print(f"[Database Error] PostgreSQL connection failed: {e}")
            raise RuntimeError(
                f"Failed to connect to PostgreSQL database ({e}). "
                f"Production mode (REVIEW_DEMO_MODE=false) will not fall back to SQLite."
            ) from e

    # MySQL Connection (for local development or transition)
    try:
        eng = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[Database] Connected to MySQL database successfully.")
        return eng
    except Exception as e:
        print(f"[Database Error] Database connection failed: {e}")
        raise RuntimeError(
            f"Failed to connect to configured database ({e}). "
            f"Production mode (REVIEW_DEMO_MODE=false) will not fall back to SQLite."
        ) from e

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def commit_keep_loaded(db) -> None:
    """Commit WITHOUT expiring the session's loaded objects.

    A plain commit() expires every loaded instance, so the next attribute access (passenger.email, driver.name, a
    wallet balance) silently re-SELECTs the row: one network round trip each against a remote database. Payment code
    calls this where it already holds fresh values (it refreshes explicitly after its own raw UPDATEs), which removes
    those re-reads without changing any value. Use it only on a session whose loaded rows were read in this request."""
    previous = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = previous


def get_db():
    """Dependency to yield a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
