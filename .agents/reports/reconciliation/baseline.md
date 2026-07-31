# Baseline: reconciliation

date: 2026-07-29
branch: review-feature

## git status
Clean except two pre-existing, unrelated working-tree changes carried on this branch:
- `.claude/skills/review-feature/SKILL.md` (modified — feature-index wiring, this session)
- `.agents/specs/reconciliation.md` (new — this review's reconstructed spec)

## Test baseline
```
uv run pytest tests/test_reconciliation_routes.py -v
1 passed, 1 warning in 1.42s
```
`test_reconcile_via_execution_invalid_uuid_does_not_leak_exception_text` — regression test
for a verbose-error-to-client fix, learned from a prior review-feature audit of
`org_routes.py`. No other tests exist for this slice; `reconciliation_service.py` (889
lines) has no dedicated test file at all.

## Migration audit
Skipped. The `reconciliation` slice defines no models of its own (per spec Data model:
`changes: none`) — it operates on `InventoryItem.extra_data` (JSON) and reads
`Execution`/`ExecutionStep` via existing repositories. Nothing for migration-safety to
check.
