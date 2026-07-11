# Local Observability Stacks

This repo contains two Docker Compose definitions, managed together as one
complete local stack by `uv run workflow observability`:

- `docker-compose.observability-grafana.yml` for Grafana LGTM + Alloy (+ Pyroscope)
- `docker-compose.observability-posthog.yml` for self-hosted PostHog

Both stacks join the same Docker network: `workflow-observability`.

Images that previously tracked `latest` or `master` are pinned by digest as of
2026-07-10. Upgrade them deliberately as a compatible set, validate with
`docker compose ... config -q`, and complete the browser/collector smoke test
before changing a digest.

Alloy's OTLP-to-Prometheus delta conversion currently uses its explicitly
enabled experimental processor. Treat an Alloy upgrade as a pipeline change and
re-run the native Alloy configuration validation as part of that upgrade.

## Start, Stop, and Reset

Run these repository commands from the project root:

```bash
uv run workflow observability secrets  # verify required KeePassXC entries exist
uv run workflow observability help     # list commands and browser URLs
uv run workflow observability start    # start Grafana, Alloy, Loki, Tempo, Mimir, Pyroscope, and PostHog
uv run workflow observability status
uv run workflow observability logs -f alloy
uv run workflow observability stop     # stop containers but retain their data
uv run workflow observability reset    # recreate containers while preserving all observability data volumes
uv run workflow observability reset --volumes  # explicitly delete volumes as well, then recreate cleanly
uv run workflow observability reset --volumes --rotate-secrets  # wipe data and rotate the three KeePassXC stack secrets
```

`workflow observability reset` resets only Docker resources belonging to this observability stack
while retaining Grafana, Loki, Tempo, Mimir, Pyroscope, and PostHog data.
It does not alter KeePassXC entries, project source, or unrelated containers.
Use `reset --volumes` only when you intentionally want a blank stack.
Use `--rotate-secrets` only with `--volumes`: rotating PostHog's encryption
values while retaining its data would make existing encrypted values unreadable.

## KeePassXC setup

The launcher reads the following local KeePassXC entries. Store each value in
the entry's **Password** field; do not put them in `.bashrc` or a tracked file.
Their paths, Grafana username, and local PostHog URL are configured in the
`[observability]` section of `app/config/local.ini`, so local deployments have
one non-secret source of truth.

| KeePassXC entry | Purpose | When needed |
| --- | --- | --- |
| `workflow-engine/observability/posthog_secret` | PostHog Django secret | Before `workflow observability start` |
| `workflow-engine/observability/posthog_encryption_salt_keys` | PostHog encryption salt | Before `workflow observability start` |
| `workflow-engine/observability/grafana_admin_password` | Grafana `admin` password | Before `workflow observability start` |
| `workflow-engine/observability/posthog_project_api_key` | Browser PostHog project API key | After creating a PostHog project |

Generate the first three values with `openssl rand -hex 32`, then create the
entries in KeePassXC. Confirm the CLI can access them with `workflow observability secrets`.

For a new or intentionally wiped stack, this is automated instead:

```bash
uv run workflow observability reset --volumes --rotate-secrets
```

That command runs `openssl rand -hex 32` three times, creates or updates the
configured KeePassXC entries, self-checks them, then creates
a blank stack. It intentionally requires `--volumes`, because rotating PostHog
encryption values without deleting its stored data is unsafe.

After the first `workflow observability start`:

1. Sign in to Grafana at `http://localhost:3000` as `admin` using the KeePassXC
   password.
2. Open PostHog at `http://localhost:8000`, create the initial PostHog user and
   project, then copy that project's public API key into the
   `posthog_project_api_key` KeePassXC entry.
3. Restart the local Flask app. With `ENVIRONMENT=local` or `ENVIRONMENT=test`,
   the config loader reads that entry automatically and supplies it to the RUM
   bootstrap. The test environment sends browser telemetry to the local stack,
   but continues to disable backend OpenTelemetry exporters so pytest does not
   emit backend telemetry.

The old `observability/posthog-stack/.env` pattern is not used by this local
CLI. The `.env.example` remains only as a reference for a
non-KeePassXC deployment.

## 1) Start Grafana Stack (LGTM + Alloy)

```bash
uv run workflow observability start
```

Services and default ports:

- Grafana: `http://localhost:3000` (user `admin`; password from KeePassXC)
- Alloy OTLP gRPC: `localhost:4317`
- Alloy OTLP HTTP: `localhost:4318`
- Alloy Faro receiver: `http://localhost:12347`
- Loki: `http://localhost:3100`
- Tempo: `http://localhost:3200`
- Mimir: `http://localhost:9009`
- Pyroscope: `http://localhost:4040`

## 2) PostHog UI

PostHog starts as part of `workflow observability start`.

- `http://localhost:8000`

Supporting services exposed:

- Redpanda Kafka external listener: `localhost:19092`
- MinIO API: `http://localhost:19000`
- MinIO Console: `http://localhost:19001`

## 3) App Telemetry Proxy (Same-Origin)

The Flask app exposes constrained same-origin telemetry ingest endpoints:

- `POST /telemetry` (Faro `/collect` only)
- `GET|POST /telemetry/posthog/e/`, `/flags/`, and `/s/` (the vendored PostHog SDK endpoints)

These endpoints are CSRF-exempt because browser telemetry SDKs cannot send the
app CSRF token. They are deliberately endpoint-allowlisted and rate-limited;
they are not a general upstream proxy.

Local observability config is pre-wired in `app/config/local.ini`:

- `otel_exporter_endpoint = http://localhost:4317`
- `rum_collector_url = /telemetry`
- `rum_faro_upstream = http://localhost:12347`
- `rum_posthog_upstream = http://localhost:8000`
- `rum_posthog_api_key` is read from the KeePassXC PostHog project API-key entry

The Dockerised test deployment also sends browser telemetry to this local stack.
`scripts/run_test.sh` and `scripts/deploy_test_simple.sh` join it to the
`workflow-observability` network, pass the KeePassXC project token as a
container environment variable, and use `http://alloy:12347` and
`http://posthog-web:8000` as internal collector addresses. Do not use
`localhost` for those test-container upstreams: it refers to the test
container itself.

Frontend SDK bundles are vendored in `app/ui/shared/` and loaded from `base_spa.html` when `rum_enabled=true`:

- `faro-web-sdk.iife.js`
- `faro-web-tracing.iife.js`
- `posthog-array.full.js`
- `observability-rum.js` bootstrap (standard PostHog `$pageview`/`$pageleave`, HTMX dwell,
  JS errors, web-vitals, trace header helper). PostHog feature flags are not
  enabled, so the optional remote-configuration loader is disabled.

Python structured logs are exported as OTLP logs alongside traces and metrics.
Alloy keeps only bounded resource labels (`service`, namespace, and environment)
in Loki; correlation, user, organisation, span, and trace IDs remain searchable
JSON fields rather than Loki labels.

## 4) Basic Health Checks

```bash
uv run workflow observability status
```

In Grafana (`http://localhost:3000`), the datasources are auto-provisioned:

- `Loki` (default)
- `Tempo`
- `Mimir`
- `Pyroscope`

## 5) Stop Stacks

```bash
uv run workflow observability stop
```

To wipe volumes:

```bash
uv run workflow observability reset --volumes
```
