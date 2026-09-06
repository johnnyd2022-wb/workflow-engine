# TEST-EVALUATOR: execution
date: 2026-08-02
verdict: invalid (pre-patch) — see Resolution

Stage ran on Codex (`gpt-5.6-sol`, `--sandbox read-only`). Per
`.agents/verification-chain.md` §5, a read-only Codex sandbox cannot write its own
report file (`patch rejected: writing is blocked by read-only sandbox`); this file is
the orchestrator's verbatim transcription of the stage's final message, not something
the orchestrator wrote independently.

## Verbatim findings

> The date-comparison tests are substantive: they independently move `completed_at` to
> today versus ten days earlier while fixing expiry at yesterday, and assert opposite
> inclusion outcomes. The class's no-cross-tenant-test rationale also holds — the
> forward traversal first limits steps to `Execution.org_id` and only admits output
> items whose source step is in that org, so a foreign-step item cannot reach the later
> lookup.
>
> The expired-raw date tests are substantive, and their cross-tenant-unreachability
> reasoning holds. The Playwright redirect delay is legitimate determinism
> infrastructure and does not alter completion or upload behavior.
>
> Nine runnable pure helper tests passed. DB-backed mutation reruns were blocked by
> sandbox network restrictions; existing review records supply the pre-fix/post-fix
> evidence.

Blocking findings:

- `tests/test_evidence.py:666` — traversal test never reaches the containment guard.
  The 2026-08-02 fix planted a real file at the traversal target, but that was still
  insufficient: `read_file_path` joins `root/"org1"/"../../outside"/<file>` and the
  kernel cannot resolve the `org1/..` segment unless `root/"org1"` exists, so
  `candidate.is_file()` stayed False and the function still short-circuited *before*
  `relative_to()`. Fixed 2026-09-06 by findings-sweep:
  `test_read_file_path_rejects_traversal_outside_storage_root` now also `mkdir`s
  `tmp_path/"org1"`, so `is_file()` is True and the containment check is what returns
  `None`. Falsifiability re-confirmed by mutation — with the `relative_to()` guard
  commented out in `evidence_storage.py`, the test now fails (it passed before this
  change) (verified 2026-09-06 by findings-sweep).
- `tests/test_evidence.py:555` — finalize-failure test never checks whether the
  temporary upload file is removed. Already fixed:
  `test_finalize_from_temp_failure_leaves_no_orphan_record` now captures the temp path
  via the `_boom` mock and asserts `not captured_temp_path["path"].exists()` with an
  explicit message (verified 2026-09-06 by findings-sweep).
- `tests/test_evidence.py:403` — idempotency test uses two different UUIDs instead of
  retrying the same deletion. Already fixed:
  `test_delete_is_idempotent_on_missing` now reuses the same `missing_id` for both
  delete calls (verified 2026-08-25 by findings-sweep).

VERDICT (as returned by the stage): invalid

## Resolution (orchestrator)

All three findings confirmed correct on inspection and patched — see
`.agents/reports/execution/review.md` for the fix details and re-run confirmation. This
review's own regression tests (the 5 bug-fix tests written directly by this review, not
by test-author) were separately verified pre-fix-fails/post-fix-passes via `git stash`
at the time each was written (documented inline in this session); the stage's inability
to re-run DB-backed mutations under its network-restricted sandbox does not apply to
those.
