## Round-2 verification

1. **Resolved — unresolved same-name outputs.** [`engine.py:668`](/home/johnny/wt-live-cogs/app/features/costing/engine.py:668) assigns unidentified outputs per-flow identity instead of grouping by name. Regression: [`test_costing_engine.py:1057`](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:1057).

2. **Resolved — node budget.** [`engine.py:269`](/home/johnny/wt-live-cogs/app/features/costing/engine.py:269) charges unique lots and executions; internal steps no longer consume the budget. Regression: [`test_costing_engine.py:1081`](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:1081).

3. **Resolved — incomplete execution-flow provenance.** The model and migration require execution, step, and step number for execution-backed flows at [`models.py:71`](/home/johnny/wt-live-cogs/app/features/costing/models.py:71) and [`costing_engine_001.py:78`](/home/johnny/wt-live-cogs/app/core/db/migrations/versions/costing_engine_001.py:78). ORM metadata now declares the composite target constraint at [`execution_step.py:33`](/home/johnny/wt-live-cogs/app/core/db/models/execution_step.py:33). Regression: [`test_costing_engine.py:1098`](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:1098).

4. **Resolved — concurrent first settings writes.** [`service.py:204`](/home/johnny/wt-live-cogs/app/features/costing/service.py:204) uses PostgreSQL `INSERT … ON CONFLICT DO UPDATE`. Concurrent-session regression: [`test_costing_engine.py:1132`](/home/johnny/wt-live-cogs/tests/test_costing_engine.py:1132).

Fresh adversarial review of `origin/main...HEAD -- app/` found no remaining HIGH-severity defect.

Verification notes: Ruff passed. The committed suite record shows 4,211 passing tests with two registry failures that HEAD subsequently addresses; the staff registry regression now passes directly. Database-backed reruns could not connect because `host.docker.internal` is unresolvable in this sandbox, so the four round-2 tests errored during fixture setup rather than reaching assertions.

VERDICT: pass
