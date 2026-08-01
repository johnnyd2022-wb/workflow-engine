# FIX: cross-org process_id in reconcile_via_execution returns 500 instead of 400
date: 2026-07-31
symptom: security-audit finding F1 (`.agents/reports/reconciliation/security-audit.md`) and
         e2e-playwright's independently-reproduced AC8 finding
         (`.agents/reports/reconciliation/e2e-playwright.md`) — a `process_id` belonging to
         another org, passed to `POST /api/core/inventory/reconcile/via-execution`, produced
         an uncaught 500 instead of the clean `{"error": "..."}` 400 every other cross-org
         input on this route returns.
root_cause: `ExecutionRepository.create_execution` (`app/core/db/repositories/execution_repo.py:76`)
            raises a bare `ValueError` when `process_id` doesn't belong to `org_id`.
            `reconcile_via_execution` (`app/core/backend/reconciliation_service.py`, was
            line 564) called it inside a `try` block whose only handler was
            `except Exception: session.rollback(); raise` — it re-raised the ValueError
            unchanged instead of converting it to the `{"error": ...}` dict shape the
            `untracked_item_id`/`step_id` checks in the same function already use. The
            route (`reconciliation_routes.py:148-168`) had no `try/except` of its own
            around the service call (only `try/finally: session.close()`), so the
            exception reached Flask's default handling unconverted — a 500 in prod, a
            Werkzeug debugger traceback leak with `debug = true` (`local.ini`/`test.ini`).
repro_test: I wrote `tests/test_reconciliation_routes.py::test_reconcile_via_execution_cross_org_process_id_returns_clean_400_not_500`
            and confirmed it red pre-fix (reverting my patch via `git stash` reproduced the
            raw `ValueError` and a 500) before applying my own patch.
already_fixed_upstream: **Before this branch was rebased onto `origin/main`, main already
            carried an equivalent fix** — commit `b2b5144`
            ("fix(inventory): 500 on cross-org process_id in reconcile via-execution",
            merged 2026-07-30, i.e. before this fix-bug pass started) — with its own
            regression test in `tests/test_inventory.py`. This branch had been cut before
            that commit landed and never picked it up, so the same bug got independently
            found and fixed twice. Discovered only when rebasing this branch onto
            `origin/main` produced a merge conflict on the exact same lines of
            `reconciliation_service.py`. Resolution: kept main's version (differs only in
            error message text — `"Process not found or access denied"` vs. this pass's
            `"Process not found"`) and dropped my redundant patch, my redundant regression
            test, and the docstring/import changes that only existed to support that test.
            No functional change from this pass survives for F1 — it is fully superseded by
            `b2b5144`. `.agents/history/findings.jsonl` records this (sig `167ec038552c`).
fix: app/core/backend/reconciliation_service.py — F1 is main's `b2b5144`, not this pass's
     patch (see `already_fixed_upstream` above). What *did* survive from this pass: removed
     `reconcile_output_to_untracked` (security-audit F2: confirmed dead via
     `grep -rn "reconcile_output_to_untracked(" app/`, zero callers, own docstring said
     DEPRECATED) — a small, mechanical, low-risk cleanup, still needed since main never
     did this part.
chain: [security-audit: pre-existing finding (F1/F2), not re-run this pass;
        e2e-playwright: tests/e2e/reconciliation 12/12 passed (3 runs, no flakes) —
          AC8 process_id test unchanged and still green post-rebase, now both cross-org
          and nonexistent cases are identical 400s instead of identical 500s (main's fix,
          not mine);
        full suite: tests/ -> 590 passed, 30 skipped pre-rebase (live_server, no dev
          server flag needed for this change); full suite re-run pending post-rebase;
        ruff: clean on all touched files;
        migration-safety: n/a, no schema change;
        perf-guardrails: n/a, no route added/changed shape, only an error path;
        test-evaluator / ci-gate / merge-request: not run — this was a direct fix
          requested inline by the user, not a full unattended chain dispatch]
verdict: fixed-with-followup
followup: the F2 dead-code removal is this pass's only surviving change to production
          code; F1 needed no work here once rebased. Filing this report primarily as a
          record of the duplicate-work discovery for whoever owns branch hygiene on this
          repo — two independent sessions fixed the identical bug because this branch
          diverged from main and neither picked up the other's history before starting.
