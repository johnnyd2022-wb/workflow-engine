# Observability Decision Rule: Events vs Logs

Use this rule in code review for any new telemetry write.

## Rule

- If it is a durable business fact about customer data: write an `entity_event`.
- If it is system behavior (performance, retries, failures, infrastructure): write a structured log.
- If it is a security/compliance signal (for example login or lockout): write both.

## Examples

- `entity_event`: invoice authorised, CRM task completed, product mapping changed.
- `log`: request latency, transient Xero API retry, collector/export failure.

## Data boundaries

- `entity_events` are the long-lived audit system of record in Postgres.
- Logs are operational telemetry; do not place customer content or secrets in logs.

## `audit_logs` legacy policy

- Freeze policy (non-destructive): do not add new `log_action` calls for CRM flows.
- Keep existing `audit_logs` table and legacy writers in place for backward compatibility.
