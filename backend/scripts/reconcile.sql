-- Read-only transaction snapshot. Zero in every category is the expected result.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT count(*) AS counter_or_bounds_mismatches
FROM events e
WHERE e.allocated_seats < 0 OR e.allocated_seats > e.capacity
   OR e.allocated_seats <> (
       SELECT count(*) FROM reservations r
       WHERE r.event_id = e.id AND r.status IN ('HELD', 'CONFIRMED')
   );
SELECT count(*) AS duplicate_active_pairs
FROM (
    SELECT user_id, event_id FROM reservations
    WHERE status IN ('HELD', 'CONFIRMED')
    GROUP BY user_id, event_id HAVING count(*) > 1
) duplicates;
SELECT count(*) AS incomplete_idempotency_claims
FROM idempotency_records WHERE completed_at IS NULL;
COMMIT;
