-- PHASE A AUDIT for passengers 69 and 70. READ-ONLY: every statement is a SELECT (Supabase SQL editor).
-- Run before enabling anything. Output: ids, yes/no flags, counts, amounts and timestamps only
-- (no names, emails, phones or card UIDs). Run one block at a time and paste the results back.

-- A1. Accounts: type, status, email present (yes/no), wallet, NFC card.
SELECT u.id, u.account_type, u.status,
       (u.email IS NOT NULL AND btrim(u.email) <> '')            AS has_email,
       (w.id IS NOT NULL)                                         AS wallet_exists,
       w.is_frozen                                                AS wallet_frozen,
       (SELECT COUNT(*) FROM nfc_cards c WHERE c.user_id = u.id)  AS nfc_cards,
       (SELECT string_agg(DISTINCT c.status, ',') FROM nfc_cards c WHERE c.user_id = u.id) AS nfc_card_statuses,
       (SELECT bool_or(c.card_uid IS NOT NULL) FROM nfc_cards c WHERE c.user_id = u.id)    AS nfc_uid_assigned
FROM users u LEFT JOIN wallets w ON w.user_id = u.id
WHERE u.id IN (69, 70) ORDER BY u.id;

-- A2. Ride payments by status and payment method.
SELECT passenger_id, status, payment_method, COUNT(*) AS n
FROM transactions
WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- A3. Completed rides, time span, amount distribution, night/day share (IST 22:00-05:59 = night).
SELECT passenger_id,
       COUNT(*)                                                   AS completed_rides,
       GREATEST(0, 100 - COUNT(*))                                AS still_needed_for_personal_profile,
       MIN(created_at) AS first_utc, MAX(created_at) AS last_utc,
       MIN(amount) AS amt_min,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY amount)        AS amt_median,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)        AS amt_p90,
       MAX(amount) AS amt_max,
       ROUND(100.0 * AVG(CASE WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') >= 22
                               OR EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') < 6
                              THEN 1 ELSE 0 END), 1)              AS night_pct
FROM transactions
WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment' AND status = 'completed'
GROUP BY passenger_id ORDER BY passenger_id;

-- A4. Drivers they ride with, and how many have no vehicle type (the model treats NULL/unknown as "unknown").
SELECT t.passenger_id,
       COUNT(DISTINCT t.driver_id)                                                         AS distinct_drivers,
       COUNT(DISTINCT t.driver_id) FILTER (WHERE d.vehicle_type IS NULL OR btrim(d.vehicle_type) = '') AS drivers_without_vehicle_type
FROM transactions t LEFT JOIN users d ON d.id = t.driver_id
WHERE t.passenger_id IN (69, 70) AND t.transaction_type = 'ride_payment'
GROUP BY t.passenger_id ORDER BY t.passenger_id;

-- A5. Data-quality problems (every count should be 0 unless noted).
SELECT passenger_id,
       COUNT(*) FILTER (WHERE created_at > NOW() AT TIME ZONE 'UTC')                       AS future_timestamps,
       COUNT(*) FILTER (WHERE driver_id IS NULL)                                           AS null_driver,
       COUNT(*) FILTER (WHERE amount IS NULL OR amount <= 0)                               AS zero_or_negative_amount,
       COUNT(*) - COUNT(DISTINCT idempotency_key) FILTER (WHERE idempotency_key IS NOT NULL) - COUNT(*) FILTER (WHERE idempotency_key IS NULL) AS duplicate_idempotency_keys,
       COUNT(*) FILTER (WHERE created_at IS NULL)                                          AS null_timestamp
FROM transactions
WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment'
GROUP BY passenger_id ORDER BY passenger_id;

-- A6. Identical (timestamp, amount, driver) triples and tied timestamps (the scorer rejects both; the gate cleans them).
SELECT passenger_id, 'identical_triple' AS kind, COUNT(*) AS groups
FROM (SELECT passenger_id, created_at, amount, driver_id FROM transactions
      WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment'
      GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1) x GROUP BY passenger_id
UNION ALL
SELECT passenger_id, 'tied_timestamp', COUNT(*)
FROM (SELECT passenger_id, created_at FROM transactions
      WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment'
      GROUP BY 1, 2 HAVING COUNT(*) > 1) y GROUP BY passenger_id
ORDER BY 1, 2;

-- A7. Rides closer than 10 minutes to the previous COMPLETED ride, and the longest chain of such rides.
WITH c AS (
  SELECT passenger_id, created_at,
         EXTRACT(EPOCH FROM created_at - LAG(created_at) OVER (PARTITION BY passenger_id ORDER BY created_at, id)) AS gap_s
  FROM transactions
  WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment' AND status = 'completed'
), g AS (
  SELECT passenger_id, created_at, gap_s,
         SUM(CASE WHEN gap_s IS NOT NULL AND floor(gap_s) <= 600 THEN 0 ELSE 1 END)
           OVER (PARTITION BY passenger_id ORDER BY created_at) AS chain_id
  FROM c
)
SELECT passenger_id,
       COUNT(*) FILTER (WHERE gap_s IS NOT NULL AND floor(gap_s) <= 600) AS rides_within_10_min_of_previous,
       MAX(chain_len)                                                    AS longest_chain_rides
FROM (SELECT passenger_id, gap_s, COUNT(*) OVER (PARTITION BY passenger_id, chain_id) AS chain_len FROM g) z
GROUP BY passenger_id ORDER BY passenger_id;

-- A8. Do the new fraud tables exist yet? (0 rows before the migration is run.)
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name IN ('fraud_assessments', 'payment_otp_challenges');
