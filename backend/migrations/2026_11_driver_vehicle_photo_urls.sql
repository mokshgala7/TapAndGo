-- Optional display photos for the passenger's confirm-payment page (Tap&Go backend, Supabase Postgres).
-- Two NULLABLE columns on users; nothing is changed or deleted, every statement is guarded, so it is safe to run twice.
--   driver_photo_url   a public https:// URL (or a site path such as /drivers/ravi.jpg) of the driver's avatar photo.
--   vehicle_photo_url  the same for the vehicle, e.g. /vehicles/hyundai-creta.jpg (see frontend/public/vehicles/CREDITS.md).
-- When a value is empty the page shows its built-in animated cartoon avatar and a vehicle illustration chosen by
-- vehicle type. The backend reads these columns on their own and ignores them when they do not exist yet, so the
-- app works before and after this migration. The columns are deliberately NOT mapped in app/models.py: a missing
-- column must never be able to break a users query.

ALTER TABLE users ADD COLUMN IF NOT EXISTS driver_photo_url VARCHAR(500) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vehicle_photo_url VARCHAR(500) NULL;
