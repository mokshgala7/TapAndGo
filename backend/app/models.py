from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, Text, DateTime, func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    account_type = Column(String(20), nullable=False, default="passenger")
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=False, unique=True, index=True)
    phone = Column(String(20), nullable=False, unique=True, index=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    pincode = Column(String(10), nullable=True)
    aadhaar = Column(String(20), nullable=True)
    pan = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    profile_photo = Column(String(255), nullable=True)

    # Driver Specific Fields
    vehicle_type = Column(String(50), nullable=True)
    vehicle_registration = Column(String(50), nullable=True)
    vehicle_make = Column(String(100), nullable=True)
    vehicle_model = Column(String(100), nullable=True)
    driving_licence_number = Column(String(50), nullable=True)

    # Document Upload File Paths
    rc_document = Column(String(255), nullable=True)
    licence_document = Column(String(255), nullable=True)
    insurance_document = Column(String(255), nullable=True)
    signature_document = Column(String(255), nullable=True)
    id_document = Column(String(255), nullable=True)

    # Location & Emergency Contact
    state = Column(String(100), nullable=True)
    emergency_contact_name = Column(String(100), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)

    # Bank Payout Details & Single-Edit Locking
    bank_account_holder = Column(String(100), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_ifsc = Column(String(20), nullable=True)
    bank_upi_id = Column(String(50), nullable=True)
    bank_locked = Column(Integer, default=0)  # 0 = editable once, 1 = locked
    bank_request_status = Column(String(20), default="none")  # none, requested, approved
    doc_request_status = Column(String(20), default="none")   # none, requested, approved
    phone_request_status = Column(String(20), default="none") # none, requested, approved
    status = Column(String(20), nullable=False, default="active")
    qr_identifier = Column(String(128), nullable=True)
    nfc_identifier = Column(String(128), nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class EmailOTP(Base):
    """
    Email OTP model for transactional verification workflows.
    Canonical reasons:
      - 'create_account' (legacy purpose: 'registration')
      - 'forgot_password'
      - 'withdraw_balance' (legacy purpose: 'withdrawal')
      - 'wallet_topup'
    Lifecycle:
      - OTP rows are NEVER physically deleted; they are persisted for auditability and security history.
      - 'used=True' means the OTP is no longer usable. This includes successful consumption,
        invalidation upon resend of a newer code, expiration, or lockout after 5 failed attempts.
    """
    __tablename__ = "email_otps"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(120), nullable=False, index=True)
    otp = Column(String(10), nullable=False)
    # Canonical workflow reason
    reason = Column(String(32), nullable=False, default="create_account", index=True)
    # Purpose retained and synchronized for backward compatibility
    purpose = Column(String(32), nullable=False, default="create_account", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    is_verified = Column(Boolean, nullable=False, default=False)
    # used=True means no longer usable (consumed, invalidated by resend, or locked out)
    used = Column(Boolean, nullable=False, default=False, index=True)
    # Optional metadata (e.g., amount-tied topup JSON {"amount": 100.0, "user_id": 1})
    otp_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    expires_at = Column(DateTime, nullable=False)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, default="Tap&Go Administrator")
    email = Column(String(120), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminSession(Base):
    """Server-side administrator session. Only the SHA-256 of the bearer token
    is stored. Replaces the former trust in a client-supplied X-Admin-Id header."""
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class PaymentOrder(Base):
    """Server-side record of every Razorpay order created for a wallet top-up.

    The authoritative amount, currency and owner of a top-up are taken from this
    row, never from the client. `status` moves created -> paid exactly once."""
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    status = Column(String(20), nullable=False, default="created", index=True)  # created, paid
    is_mock = Column(Boolean, nullable=False, default=False)
    provider_payment_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    paid_at = Column(DateTime, nullable=True)


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0)
    is_frozen = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    upi_uri = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="Pending", index=True)  # Pending, Completed, Expired, Failed
    provider = Column(String(30), nullable=False, default="RAZORPAY")
    provider_transaction_id = Column(String(128), nullable=True)
    utr = Column(String(128), nullable=True, index=True)
    payer_name = Column(String(120), nullable=True)
    raw_email_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reference = Column(String(64), nullable=False, unique=True, index=True)
    passenger_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(20), nullable=False, default="wallet")
    status = Column(String(20), nullable=False, default="pending")
    otp_verified = Column(Boolean, nullable=False, default=False)
    fraud_status = Column(String(20), nullable=False, default="clear")
    
    # Safe non-destructive fields for ledger completeness, idempotency & linking
    transaction_type = Column(String(30), nullable=True)
    description = Column(Text, nullable=True)
    balance_after = Column(Numeric(12, 2), nullable=True)
    idempotency_key = Column(String(128), nullable=True, unique=True, index=True)
    related_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Razorpay / Provider Audit Fields
    provider = Column(String(30), nullable=True)
    provider_transaction_id = Column(String(128), nullable=True, unique=True, index=True)
    utr = Column(String(128), nullable=True)
    payer_name = Column(String(120), nullable=True)
    payment_request_id = Column(Integer, ForeignKey("payment_requests.id"), nullable=True)
    payment_source = Column(String(50), nullable=True)
    email_received_at = Column(DateTime, nullable=True)
    raw_email_id = Column(String(255), nullable=True)

    # Why a failed tap/payment did not complete (e.g. INSUFFICIENT_BALANCE). NULL for every other row.
    failure_code = Column(String(40), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserDocument(Base):
    __tablename__ = "user_documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_type = Column(String(80), nullable=False)
    file_path = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class EditRequest(Base):
    __tablename__ = "edit_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    previous_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    proof_path = Column(String(255), nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(Integer, ForeignKey("admins.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)
    risk_score = Column(Integer, nullable=False, default=0)
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime, nullable=True)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class ProjectSetting(Base):
    __tablename__ = "project_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NFCCardOrder(Base):
    __tablename__ = "nfc_card_orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_reference = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    card_type = Column(String(50), nullable=False, default="standard_nfc")
    card_price = Column(Numeric(12, 2), nullable=False, default=50.00)
    delivery_charge = Column(Numeric(12, 2), nullable=False, default=0.00)
    total_amount = Column(Numeric(12, 2), nullable=False, default=50.00)
    delivery_tier = Column(String(30), nullable=False, default="local")
    
    # Recipient & Delivery Address Details
    recipient_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address_line1 = Column(Text, nullable=False)
    address_line2 = Column(Text, nullable=True)
    area = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    pincode = Column(String(10), nullable=False)

    # Order Lifecycle & Statuses
    order_status = Column(String(30), nullable=False, default="processing", index=True) # pending_payment, processing, dispatched, delivered, cancelled, failed
    payment_status = Column(String(30), nullable=False, default="paid", index=True)     # pending, paid, failed, refunded
    is_demo = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email_type = Column(String(50), nullable=False, index=True)
    recipient = Column(String(120), nullable=False, index=True)
    reference = Column(String(64), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="SENT")  # SENT, FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=False)
    phone = Column(String(20), nullable=False)
    category = Column(String(50), nullable=False, default="other")  # billing, technical, nfc_card, account, other
    priority = Column(String(20), nullable=False, default="medium")  # low, medium, high, urgent
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="open", index=True)  # open, in_progress, resolved, closed
    admin_reply = Column(Text, nullable=True)
    replied_by = Column(Integer, ForeignKey("admins.id"), nullable=True)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NFCCard(Base):
    __tablename__ = "nfc_cards"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    card_reference = Column(String(64), nullable=False, unique=True, index=True)
    # Chip UID as read by the POS: uppercase hex, no separators (8 or 14 chars). NULL until assigned.
    card_uid = Column(String(32), nullable=True, unique=True)
    card_type = Column(String(50), nullable=False, default="standard_nfc")
    status = Column(String(20), nullable=False, default="active", index=True)  # active, blocked, lost, replaced
    blocked_reason = Column(Text, nullable=True)
    block_requested_at = Column(DateTime, nullable=True)
    # FK to the nfc_card_orders record that originally issued this card (optional)
    nfc_order_id = Column(Integer, ForeignKey("nfc_card_orders.id"), nullable=True)
    # FK to the replacement nfc_card_orders record (set when status→replaced)
    replacement_order_id = Column(Integer, ForeignKey("nfc_card_orders.id"), nullable=True)
    issued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FraudAssessment(Base):
    """One row per fraud-gate decision on a ride payment (QR, NFC or wallet pay). Audit only:
    ids, amounts, scores and the decision; no names, contact data or location."""
    __tablename__ = "fraud_assessments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    passenger_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    channel = Column(String(10), nullable=False)                 # qr, nfc, wallet
    idempotency_key = Column(String(128), nullable=True, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    assessed_at = Column(DateTime, nullable=False)               # naive UTC, when the payment was initiated
    mode = Column(String(10), nullable=False)                    # mode that applied to THIS payment: off, shadow, enforce
    enforced_by_allowlist = Column(Boolean, nullable=False, default=False)   # enforce because the passenger is in TAPGO_FRAUD_ENFORCE_USER_IDS
    risk_score = Column(Numeric(8, 6), nullable=True)            # NULL when the model produced no score
    model_flag = Column(Boolean, nullable=True)
    rule_10min = Column(Boolean, nullable=False, default=False)
    elapsed_seconds = Column(Integer, nullable=True)             # since the previous COMPLETED ride; NULL if none
    ml_status = Column(String(30), nullable=False)               # scored, disabled, model_unavailable, invalid_input, error, ...
    decision = Column(String(20), nullable=False)                # proceed, otp_required
    reasons = Column(Text, nullable=True)                        # comma-separated
    model_version = Column(String(64), nullable=True)
    threshold = Column(Numeric(8, 6), nullable=True)
    challenge_id = Column(Integer, ForeignKey("payment_otp_challenges.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class PaymentOtpChallenge(Base):
    """Email OTP step-up for one ride payment. Money moves only after a correct OTP.
    Only an HMAC of the code is stored. status: pending -> completed | failed | expired | cancelled."""
    __tablename__ = "payment_otp_challenges"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    public_id = Column(String(36), nullable=False, unique=True, index=True)   # the challenge_id clients see
    passenger_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(10), nullable=False)                 # qr, nfc, wallet
    idempotency_key = Column(String(128), nullable=False, index=True)   # the route's scoped key
    amount = Column(Numeric(12, 2), nullable=False)
    card_uid = Column(String(32), nullable=True)
    payment_request_id = Column(Integer, ForeignKey("payment_requests.id"), nullable=True, index=True)
    otp_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    resend_count = Column(Integer, nullable=False, default=0)
    last_sent_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    failure_code = Column(String(40), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    resolved_at = Column(DateTime, nullable=True)


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    # The transaction that represents the held/reserved balance deduction
    hold_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    destination_desc = Column(Text, nullable=False)
    reference = Column(String(64), nullable=False, unique=True, index=True)
    otp_verified = Column(Boolean, nullable=False, default=True)
    # pending → approved → paid | pending → rejected | paid → refunded
    status = Column(String(20), nullable=False, default="pending", index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    admin_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(128), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

