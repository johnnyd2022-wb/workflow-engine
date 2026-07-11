# Observability Sampling Roadmap

## Stage 1: App-side head sampling (current)
- Sampler: `ParentBased(TraceIdRatioBased(otel_sample_rate))` in `app/observability/tracing.py`.
- Environment defaults:
  - `local`: `otel_sample_rate=1.0`
  - `test`: `otel_enabled=false` (no exporter dependency in test suite)
  - `prod`: `otel_sample_rate=0.1` to start
- Outcome: deterministic, config-only tuning with no deploy required for sampling changes.

## Stage 2: Collector-side tail sampling (next)
- Add Alloy tail sampling policy after OTLP ingress is stable.
- Keep 100% of:
  - error traces (`status_code=ERROR`)
  - slow traces (latency above agreed p95/p99 threshold)
- Downsample healthy low-latency traces to manage cost.
- Continue honoring upstream sampling decisions via W3C `traceparent`.

## Stage 3: Policy tuning loop
- Weekly review:
  - trace volume by feature
  - error-trace retention hit rate
  - slow-trace capture coverage
- Adjust only via config:
  - app `otel_sample_rate`
  - Alloy tail-sampling policy weights/conditions
