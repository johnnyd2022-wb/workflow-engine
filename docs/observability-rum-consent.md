# RUM Consent And Notice Posture (NZ)

This project uses self-hosted frontend telemetry for operational observability and UX improvement:

- Grafana Faro (errors, performance, frontend traces)
- PostHog (journey analytics and session replay)

## Data boundary

- IDs only: `user_id`, `org_id`, route/path, timing metrics, technical event metadata.
- Masking defaults are enabled (`rum_mask_inputs=true`, PostHog text/input masking config in `observability-rum.js`).
- `rum_sample_rate` is a session-level collection boundary: an unsampled session
  does not initialise Faro or PostHog, including autocapture and session replay.
- No customer business values or free-text form inputs should be intentionally captured.

## Customer notice requirements

Before production enablement (`rum_enabled=true` in prod), customer-facing terms/policy should state:

1. Session analytics and replay are collected for reliability, support, and product improvement.
2. Inputs and page text are masked by default.
3. Data is processed in self-hosted infrastructure controlled by us.
4. Customers can request support for privacy concerns and data handling questions.

## Operational verification (human gate)

Agent wiring is not sufficient by itself. Before release, a human must verify in browser devtools:

1. No sensitive values appear in `/telemetry` payloads.
2. Session replay renders masked content.
3. Only intended identifiers (`user_id`, `org_id`) are present.
