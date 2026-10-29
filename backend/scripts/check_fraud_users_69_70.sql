-- READ-ONLY checks for passengers 69 and 70 after the fraud gate is deployed (Supabase SQL editor).
-- Every statement is a SELECT. Nothing here changes data. Run the blocks one at a time.
-- Output contains ids, counts, amounts, scores and timestamps only (no names, emails, phones or card UIDs).

-- 1. Completed ride payments per user, vs the 100 needed to switch on the personal profile.
SELECT passenger_id,
       COUNT(*) FILTER (WHERE status = 'completed')                         AS completed_rides,
       COUNT(*) FILTER (WHERE status = 'failed')                            AS failed_rides,
       GREATEST(0, 100 - COUNT(*) FILTER (WHERE status = 'completed'))      AS completed_rides_still_needed,
       MIN(created_at)                                                      AS first_ride_utc,
       MAX(created_at)                                                      AS last_ride_utc
FROM transactions
WHERE passenger_id IN (69, 70) AND transaction_type = 'ride_payment'
GROUP BY passenger_id
ORDER BY passenger_id;

-- 2. Latest fraud decisions for these users (newest first). mode = the mode that applied to THAT payment;
--    enforced_by_allowlist = true when TAPGO_FRAUD_ENFORCE_USER_IDS caused enforcement.
SELECT id, passenger_id, channel, amount, assessed_at AS at_utc,
       risk_score, model_flag, rule_10min, elapsed_seconds, ml_status, mode, enforced_by_allowlist,
       decision, reasons, challenge_id
FROM fraud_assessments
WHERE passenger_id IN (69, 70)
ORDER BY id DESC
LIMIT 50;

-- 3. Any decision where the model did NOT produce a score (should be empty; each of these means OTP in enforce mode).
SELECT id, passenger_id, channel, assessed_at AS at_utc, ml_status, mode, decision, reasons
FROM fraud_assessments
WHERE passenger_id IN (69, 70) AND ml_status <> 'scored'
ORDER BY id DESC;

-- 4. Decision summary per user and mode.
SELECT passenger_id, mode, enforced_by_allowlist, decision, COUNT(*) AS n,
       COUNT(*) FILTER (WHERE model_flag)  AS model_flags,
       COUNT(*) FILTER (WHERE rule_10min)  AS rule_10min_hits,
       ROUND(MAX(risk_score)::numeric, 4)  AS max_score
FROM fraud_assessments
WHERE passenger_id IN (69, 70)
GROUP BY passenger_id, mode, enforced_by_allowlist, decision
ORDER BY passenger_id, mode, decision;

-- 5. OTP challenges for these users by state (no OTP or hash is selected).
SELECT passenger_id, channel, status, failure_code, COUNT(*) AS n,
       MIN(created_at) AS first_utc, MAX(created_at) AS last_utc
FROM payment_otp_challenges
WHERE passenger_id IN (69, 70)
GROUP BY passenger_id, channel, status, failure_code
ORDER BY passenger_id, channel, status;

-- 6. Challenges still open right now (pending), oldest first. A row older than ~6 minutes is stuck and should not exist.
SELECT id, passenger_id, channel, amount, attempts, resend_count, created_at, expires_at,
       (expires_at < (NOW() AT TIME ZONE 'UTC')) AS already_expired
FROM payment_otp_challenges
WHERE passenger_id IN (69, 70) AND status = 'pending'
ORDER BY created_at;

-- 7. Money check: every OTP-verified completed payment has exactly one completed challenge, and nothing completed
--    sits behind a non-completed challenge (both counts should be 0).
SELECT
  (SELECT COUNT(*) FROM transactions t
    WHERE t.passenger_id IN (69, 70) AND t.status = 'completed' AND t.otp_verified
      AND NOT EXISTS (SELECT 1 FROM payment_otp_challenges c WHERE c.transaction_id = t.id AND c.status = 'completed')) AS verified_without_challenge,
  (SELECT COUNT(*) FROM payment_otp_challenges c JOIN transactions t ON t.id = c.transaction_id
    WHERE c.passenger_id IN (69, 70) AND c.status <> 'completed' AND t.status = 'completed')                           AS completed_behind_open_challenge;
