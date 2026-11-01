-- Admin hardening (Tap&Go backend, Supabase Postgres). NOT executed automatically by anyone but the app at startup.
-- Every statement is additive and idempotent: safe to run more than once, nothing is dropped, renamed or altered.
-- The app runs the same statements itself on start-up (app/main.py, run_database_migrations); running this file
-- first in the Supabase SQL editor is optional and means the deploy changes nothing at start-up.

-- Phase 3: optional rejection reason on edit requests.
ALTER TABLE edit_requests ADD COLUMN IF NOT EXISTS admin_note TEXT NULL;

-- Phase 3: repair rows written by the old admin review bug ("reject" + "d" = "rejectd"). Idempotent.
UPDATE edit_requests SET status = 'rejected' WHERE status = 'rejectd';

-- Phase 4: payout reference (UTR) recorded when an administrator marks a withdrawal as paid.
ALTER TABLE withdrawal_requests ADD COLUMN IF NOT EXISTS payout_reference VARCHAR(64) NULL;

-- Phase 6: POS device registry. (Also created at start-up by Base.metadata.create_all when missing.)
CREATE TABLE IF NOT EXISTS pos_devices (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL UNIQUE,
    label VARCHAR(100) NULL,
    driver_id INTEGER NULL REFERENCES users(id),
    vehicle_ref VARCHAR(100) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_seen_at TIMESTAMP WITHOUT TIME ZONE NULL,
    firmware_version VARCHAR(40) NULL,
    battery_pct INTEGER NULL,
    notes TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_pos_devices_device_id ON pos_devices(device_id);
CREATE INDEX IF NOT EXISTS ix_pos_devices_driver_id ON pos_devices(driver_id);
CREATE INDEX IF NOT EXISTS ix_pos_devices_status ON pos_devices(status);
