-- PostgreSQL Schema for Tap&Go Database (Supabase compatible)
-- Reference schema covering all 12 application tables.

-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    account_type VARCHAR(20) NOT NULL DEFAULT 'passenger',
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL UNIQUE,
    address TEXT NULL,
    city VARCHAR(100) NULL,
    pincode VARCHAR(10) NULL,
    aadhaar VARCHAR(20) NULL,
    pan VARCHAR(20) NULL,
    password_hash VARCHAR(255) NOT NULL,
    profile_photo VARCHAR(255) NULL,
    vehicle_type VARCHAR(50) NULL,
    vehicle_registration VARCHAR(50) NULL,
    vehicle_make VARCHAR(100) NULL,
    vehicle_model VARCHAR(100) NULL,
    driver_photo_url VARCHAR(500) NULL,
    vehicle_photo_url VARCHAR(500) NULL,
    driving_licence_number VARCHAR(50) NULL,
    rc_document VARCHAR(255) NULL,
    licence_document VARCHAR(255) NULL,
    insurance_document VARCHAR(255) NULL,
    signature_document VARCHAR(255) NULL,
    id_document VARCHAR(255) NULL,
    state VARCHAR(100) NULL,
    emergency_contact_name VARCHAR(100) NULL,
    emergency_contact_phone VARCHAR(20) NULL,
    bank_account_holder VARCHAR(100) NULL,
    bank_account_number VARCHAR(50) NULL,
    bank_ifsc VARCHAR(20) NULL,
    bank_upi_id VARCHAR(50) NULL,
    bank_locked INTEGER DEFAULT 0,
    bank_request_status VARCHAR(20) DEFAULT 'none',
    doc_request_status VARCHAR(20) DEFAULT 'none',
    phone_request_status VARCHAR(20) DEFAULT 'none',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    qr_identifier VARCHAR(128) NULL,
    nfc_identifier VARCHAR(128) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- 2. EMAIL OTPS
CREATE TABLE IF NOT EXISTS email_otps (
    id SERIAL PRIMARY KEY,
    email VARCHAR(120) NOT NULL,
    otp VARCHAR(10) NOT NULL,
    reason VARCHAR(32) NOT NULL DEFAULT 'create_account',
    purpose VARCHAR(32) NOT NULL DEFAULT 'create_account',
    attempts INTEGER NOT NULL DEFAULT 0,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    otp_metadata TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_otps_email ON email_otps(email);
CREATE INDEX IF NOT EXISTS idx_email_otps_reason ON email_otps(reason);
CREATE INDEX IF NOT EXISTS idx_email_otps_purpose ON email_otps(purpose);
CREATE INDEX IF NOT EXISTS idx_email_otps_used ON email_otps(used);

-- 3. ADMINS
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL DEFAULT 'Tap&Go Administrator',
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admins_email ON admins(email);

-- 4. WALLETS
CREATE TABLE IF NOT EXISTS wallets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    is_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallets_user_id ON wallets(user_id);

-- 5. PAYMENT REQUESTS
CREATE TABLE IF NOT EXISTS payment_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    wallet_id INTEGER NOT NULL REFERENCES wallets(id),
    amount NUMERIC(12, 2) NOT NULL,
    upi_uri TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    provider VARCHAR(30) NOT NULL DEFAULT 'RAZORPAY',
    provider_transaction_id VARCHAR(128) NULL,
    utr VARCHAR(128) NULL,
    payer_name VARCHAR(120) NULL,
    raw_email_id VARCHAR(255) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITHOUT TIME ZONE NULL,
    verified_at TIMESTAMP WITHOUT TIME ZONE NULL,
    last_checked_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE INDEX IF NOT EXISTS idx_payment_requests_user_id ON payment_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_status ON payment_requests(status);
CREATE INDEX IF NOT EXISTS idx_payment_requests_utr ON payment_requests(utr);

-- 6. TRANSACTIONS
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    reference VARCHAR(64) NOT NULL UNIQUE,
    passenger_id INTEGER NULL REFERENCES users(id),
    driver_id INTEGER NULL REFERENCES users(id),
    wallet_id INTEGER NULL REFERENCES wallets(id),
    amount NUMERIC(12, 2) NOT NULL,
    payment_method VARCHAR(20) NOT NULL DEFAULT 'wallet',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    otp_verified BOOLEAN NOT NULL DEFAULT FALSE,
    fraud_status VARCHAR(20) NOT NULL DEFAULT 'clear',
    transaction_type VARCHAR(30) NULL,
    description TEXT NULL,
    balance_after NUMERIC(12, 2) NULL,
    idempotency_key VARCHAR(128) NULL UNIQUE,
    related_transaction_id INTEGER NULL REFERENCES transactions(id),
    provider VARCHAR(30) NULL,
    provider_transaction_id VARCHAR(128) NULL,
    utr VARCHAR(128) NULL,
    payer_name VARCHAR(120) NULL,
    payment_request_id INTEGER NULL REFERENCES payment_requests(id),
    payment_source VARCHAR(50) NULL,
    email_received_at TIMESTAMP WITHOUT TIME ZONE NULL,
    raw_email_id VARCHAR(255) NULL,
    failure_code VARCHAR(40) NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_reference ON transactions(reference);
CREATE INDEX IF NOT EXISTS idx_transactions_passenger_id ON transactions(passenger_id);
CREATE INDEX IF NOT EXISTS idx_transactions_driver_id ON transactions(driver_id);
CREATE INDEX IF NOT EXISTS idx_transactions_idempotency_key ON transactions(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at);

-- 7. USER DOCUMENTS
CREATE TABLE IF NOT EXISTS user_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_type VARCHAR(80) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_documents_user_id ON user_documents(user_id);

-- 8. EDIT REQUESTS
CREATE TABLE IF NOT EXISTS edit_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    previous_value TEXT NULL,
    new_value TEXT NULL,
    proof_path VARCHAR(255) NULL,
    reason TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by INTEGER NULL REFERENCES admins(id),
    reviewed_at TIMESTAMP WITHOUT TIME ZONE NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_edit_requests_user_id ON edit_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_edit_requests_status ON edit_requests(status);

-- 9. FRAUD ALERTS
CREATE TABLE IF NOT EXISTS fraud_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NULL REFERENCES users(id),
    transaction_id INTEGER NULL REFERENCES transactions(id),
    risk_score INTEGER NOT NULL DEFAULT 0,
    reason TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE INDEX IF NOT EXISTS idx_fraud_alerts_user_id ON fraud_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_transaction_id ON fraud_alerts(transaction_id);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_status ON fraud_alerts(status);

-- 10. ACTIVITY LOGS
CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER NULL REFERENCES admins(id),
    user_id INTEGER NULL REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NULL,
    details TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_admin_id ON activity_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at);

-- 11. PROJECT SETTINGS (note the quoted "key" identifier)
CREATE TABLE IF NOT EXISTS project_settings (
    "key" VARCHAR(100) PRIMARY KEY,
    value TEXT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. NFC CARD ORDERS
CREATE TABLE IF NOT EXISTS nfc_card_orders (
    id SERIAL PRIMARY KEY,
    order_reference VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_type VARCHAR(50) NOT NULL DEFAULT 'standard_nfc',
    card_price NUMERIC(12, 2) NOT NULL DEFAULT 50.00,
    delivery_charge NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 50.00,
    delivery_tier VARCHAR(30) NOT NULL DEFAULT 'local',
    recipient_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    address_line1 TEXT NOT NULL,
    address_line2 TEXT NULL,
    area VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    pincode VARCHAR(10) NOT NULL,
    order_status VARCHAR(30) NOT NULL DEFAULT 'processing',
    payment_status VARCHAR(30) NOT NULL DEFAULT 'paid',
    is_demo BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nfc_card_orders_reference ON nfc_card_orders(order_reference);
CREATE INDEX IF NOT EXISTS idx_nfc_card_orders_user_id ON nfc_card_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_nfc_card_orders_order_status ON nfc_card_orders(order_status);
CREATE INDEX IF NOT EXISTS idx_nfc_card_orders_payment_status ON nfc_card_orders(payment_status);
CREATE INDEX IF NOT EXISTS idx_nfc_card_orders_created_at ON nfc_card_orders(created_at);

-- 14. EMAIL LOGS
CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    email_type VARCHAR(50) NOT NULL,
    recipient VARCHAR(120) NOT NULL,
    reference VARCHAR(64) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SENT',
    error_message TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_email_logs_recipient ON email_logs(recipient);
CREATE INDEX IF NOT EXISTS idx_email_logs_email_type ON email_logs(email_type);
CREATE INDEX IF NOT EXISTS idx_email_logs_reference ON email_logs(reference);
CREATE INDEX IF NOT EXISTS idx_email_logs_created_at ON email_logs(created_at);

-- 15. USER SESSIONS
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash ON user_sessions(token_hash);

-- 16. SUPPORT TICKETS
CREATE TABLE IF NOT EXISTS support_tickets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT 'other',
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    subject VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    admin_reply TEXT NULL,
    replied_by INTEGER NULL REFERENCES admins(id),
    replied_at TIMESTAMP WITHOUT TIME ZONE NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_support_tickets_user_id ON support_tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status);
CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at ON support_tickets(created_at);

-- 17. NFC CARDS
CREATE TABLE IF NOT EXISTS nfc_cards (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_reference VARCHAR(64) NOT NULL UNIQUE,
    card_uid VARCHAR(32) NULL,
    card_type VARCHAR(50) NOT NULL DEFAULT 'standard_nfc',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    blocked_reason TEXT NULL,
    block_requested_at TIMESTAMP WITHOUT TIME ZONE NULL,
    nfc_order_id INTEGER NULL REFERENCES nfc_card_orders(id),
    replacement_order_id INTEGER NULL REFERENCES nfc_card_orders(id),
    issued_at TIMESTAMP WITHOUT TIME ZONE NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nfc_cards_user_id ON nfc_cards(user_id);
CREATE INDEX IF NOT EXISTS idx_nfc_cards_status ON nfc_cards(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nfc_cards_ref ON nfc_cards(card_reference);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nfc_cards_card_uid ON nfc_cards(card_uid);

-- 18. WITHDRAWAL REQUESTS
CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    wallet_id INTEGER NOT NULL REFERENCES wallets(id),
    hold_transaction_id INTEGER NULL REFERENCES transactions(id),
    amount NUMERIC(12, 2) NOT NULL,
    destination_desc TEXT NOT NULL,
    reference VARCHAR(64) NOT NULL UNIQUE,
    otp_verified BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    admin_id INTEGER NULL REFERENCES admins(id),
    admin_note TEXT NULL,
    reviewed_at TIMESTAMP WITHOUT TIME ZONE NULL,
    paid_at TIMESTAMP WITHOUT TIME ZONE NULL,
    idempotency_key VARCHAR(128) NULL UNIQUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wr_user_id ON withdrawal_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_wr_status ON withdrawal_requests(status);
CREATE INDEX IF NOT EXISTS idx_wr_reference ON withdrawal_requests(reference);

-- 19. PAYMENT OTP CHALLENGES and 20. FRAUD ASSESSMENTS (fraud gate; see migrations/2026_10_fraud_gate_payment_otp.sql)
CREATE TABLE IF NOT EXISTS payment_otp_challenges (
    id SERIAL PRIMARY KEY,
    public_id VARCHAR(36) NOT NULL UNIQUE,
    passenger_id INTEGER NOT NULL REFERENCES users(id),
    driver_id INTEGER NOT NULL REFERENCES users(id),
    channel VARCHAR(10) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    card_uid VARCHAR(32) NULL,
    payment_request_id INTEGER NULL REFERENCES payment_requests(id),
    otp_hash VARCHAR(64) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    resend_count INTEGER NOT NULL DEFAULT 0,
    last_sent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_code VARCHAR(40) NULL,
    transaction_id INTEGER NULL REFERENCES transactions(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_public_id ON payment_otp_challenges(public_id);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_passenger_id ON payment_otp_challenges(passenger_id);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_driver_id ON payment_otp_challenges(driver_id);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_idempotency_key ON payment_otp_challenges(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_payment_request_id ON payment_otp_challenges(payment_request_id);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_status ON payment_otp_challenges(status);
CREATE INDEX IF NOT EXISTS ix_payment_otp_challenges_created_at ON payment_otp_challenges(created_at);

CREATE TABLE IF NOT EXISTS fraud_assessments (
    id SERIAL PRIMARY KEY,
    passenger_id INTEGER NULL REFERENCES users(id),
    driver_id INTEGER NULL REFERENCES users(id),
    channel VARCHAR(10) NOT NULL,
    idempotency_key VARCHAR(128) NULL,
    amount NUMERIC(12, 2) NOT NULL,
    assessed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    mode VARCHAR(10) NOT NULL,
    enforced_by_allowlist BOOLEAN NOT NULL DEFAULT FALSE,
    risk_score NUMERIC(8, 6) NULL,
    model_flag BOOLEAN NULL,
    rule_10min BOOLEAN NOT NULL DEFAULT FALSE,
    elapsed_seconds INTEGER NULL,
    ml_status VARCHAR(30) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    reasons TEXT NULL,
    model_version VARCHAR(64) NULL,
    threshold NUMERIC(8, 6) NULL,
    challenge_id INTEGER NULL REFERENCES payment_otp_challenges(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE fraud_assessments ADD COLUMN IF NOT EXISTS enforced_by_allowlist BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_fraud_assessments_passenger_id ON fraud_assessments(passenger_id);
CREATE INDEX IF NOT EXISTS ix_fraud_assessments_driver_id ON fraud_assessments(driver_id);
CREATE INDEX IF NOT EXISTS ix_fraud_assessments_idempotency_key ON fraud_assessments(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_fraud_assessments_created_at ON fraud_assessments(created_at);
