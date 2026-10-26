# Tastings observability

Existing structured request logging, correlation IDs, OTel middleware and masked browser RUM apply to the new routes. No new collector or external integration was added. `workflow observability status` ran; local collector containers are stopped, so no claim of live Grafana/PostHog ingestion is made.

The HTTP boundary logs successful committed operations as `tastings_operation_recorded` with org/user/tasting IDs, operation and resulting state; service validation rejects as `tastings_request_rejected` with operation/status/actor IDs; the extra dispatch permission denial logs `tastings_access_denied`. No form body, venue, notes, token or customer name is emitted in these lines. Normal global policy handles other role denials.

Transactional EntityEvents record tasting created/updated/dispatched/completed/cancelled, linked CRM task changes and signed inventory quantity adjustments, with actor and source evidence. Existing regression `test_dispatch_signed_movement_and_livesync_events_are_atomic_and_replay_safe` verifies event identity/actor and one replay-safe signed debit. Rollback tests verify failed operations commit no stock changes. HTTP INFO is emitted only after successful commit; retries can log multiple successful requests while the underlying movement remains idempotent.

VERDICT: clean
