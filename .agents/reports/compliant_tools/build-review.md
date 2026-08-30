# build-review — compliant_tools (advisory, Codex gpt-5.6-sol)

Reviewed `git diff main...HEAD` on `nz-alc-tools`. Advisory stage — findings fixed inline
by the orchestrator, not blocking.

## Findings (8) — all in the overflow/underflow edge class + 2 minor

| # | sev | file | finding | resolution |
|---|---|---|---|---|
| 1 | med | lal.py | `lal*100` → inf, returns `{"volume_l": Infinity}` HTTP 200 | `finalise()` guard rejects any non-finite result → `CalculatorValidationError` → 400 |
| 2 | med | standard_drinks.py | inverse: denormal `abv_pct` underflows divisor → `ZeroDivisionError` → 500 | `@guarded` decorator maps `ZeroDivisionError`/`OverflowError` → `CalculatorValidationError`; route also catches them → 400 |
| 3 | med | tank_volume.py | `diameter_m=1e308` → `r**2` `OverflowError` → 500 | `@guarded` |
| 4 | med | yeast_pitch.py | overflow → `math.ceil(inf)` `OverflowError` → 500 | `@guarded` |
| 5 | med | keg_fill.py | overflow → `math.floor(inf)` `OverflowError` → 500 | `@guarded` |
| 6 | low | yield_loss.py | `remaining * value / 100` overflows the intermediate product before the divide → false "cumulative loss exceeds" | reordered to `remaining * (value / 100)` |
| 7 | low | tools-page.js | solve-target field never disabled/cleared on `solve_for` change → "must be omitted" errors | `syncSolveTarget()` disables + clears + placeholders the target on init and on change; disabled fields excluded from the payload |
| 8 | low | feature_subscriptions_001.py | bare `except Exception` in `downgrade()` reports 0 rows for any DB error, defeating the warning | replaced with an explicit `to_regclass` existence check; a real count error now propagates |

Regression coverage added: `tests/test_compliant_tools.py::test_ac13_extreme_finite_inputs_are_rejected_not_crashed` (every Tier-1 calculator, the exact build-review payloads); `functools` added to the AC14 import allowlist (`_validate.py` now uses `functools.wraps`).

No tenant-isolation, auth/role, blueprint-gate, XSS, CSP, or migration-chain defect found.
Codex could not run pytest in its read-only sandbox; the 46 DB-independent calculator
tests it did run passed.
