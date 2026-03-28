-- Optional retention for api_idempotency_keys (idempotent POST replay cache).
-- Run periodically (e.g. weekly cron) or via job scheduler. Adjust interval as needed.
-- Requires table api_idempotency_keys (see migration api_idempotency_keys_001).

DELETE FROM api_idempotency_keys
WHERE created_at < (NOW() AT TIME ZONE 'UTC') - INTERVAL '30 days';
