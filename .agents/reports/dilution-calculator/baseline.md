# BASELINE: dilution-calculator
date: 2026-08-21
branch: mc/review-feature-20260821-080440-d97b90

## git status
clean (no uncommitted changes at review start)

## preflight
- initial run: blocked (`.venv` missing, `deps` unknown) — fixed via `uv sync --extra dev`
- re-run: `ok: true`, no blockers
- `verification_mode: herdr-tabs`, `grader_engine: codex`
- `live_server_tests: skip` (no app server listening — e2e/live-server suites will auto-skip on connection, not assertions)

## spec check
`.agents/specs/dilution_calculator.md` exists, `status: built`. Read against live code
(`app/features/dilution_calculator/services/dilution_service.py`,
`routes/api_routes.py`) — matches: exact (a,b,c,d) identity, contraction-aware
`water_to_add_ml` via bisection, AC5 direction + divisor guard, disclaimer, no
server-side rounding (AC9), no persistence (AC7). No drift found. Trusted as-is for
this review.

## test baseline
```
uv run pytest tests/test_dilution_calculator.py -v
35 passed, 9 warnings in 4.57s
```
All green — no pre-existing failures to report.

## scope
Single leaf slice (`app/features/dilution_calculator/`), no models/repos, no tenant
data, `depended on by: (leaf)`. Blast radius is contained to this slice.
