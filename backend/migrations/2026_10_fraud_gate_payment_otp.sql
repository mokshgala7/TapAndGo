-- Fraud gate decisions and payment OTP challenges (Tap&Go backend, Supabase Postgres).
-- Also created automatically at startup by Base.metadata.create_all (app/main.py) when the tables are missing;
-- run it once in the Supabase SQL editor BEFORE the backend redeploys if you want the tables in place first.
--
-- Two new tables, nothing existing is changed or deleted. Safe to run more than once.
--   payment_otp_challenges  one email-OTP step-up per flagged ride payment; only an HMAC of the code is stored.
--   fraud_assessments       one row per fraud-gate decision (ids, amount, scores, decision; no names, contact
--                           data or location).

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
