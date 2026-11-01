-- Admin hardening (Tap&Go backend, Supabase Postgres). NOT executed automatically by anyone but the app at startup.
-- Every statement is additive and idempotent: safe to run more than once, nothing is dropped, renamed or altered.
-- The app runs the same statements itself on start-up (app/main.py, run_database_migrations); running this file
-- first in the Supabase SQL editor is optional and means the deploy changes nothing at start-up.

-- Phase 3: optional rejection reason on edit requests.
ALTER TABLE edit_requests ADD COLUMN IF NOT EXISTS admin_note TEXT NULL;

-- Phase 3: repair rows written by the old admin review bug ("reject" + "d" = "rejectd"). Idempotent.
UPDATE edit_requests SET status = 'rejected' WHERE status = 'rejectd';
