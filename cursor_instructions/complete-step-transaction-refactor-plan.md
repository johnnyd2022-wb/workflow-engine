# Plan: `complete_step` transaction boundaries (`session.begin()`, fewer manual rollbacks)

**Status:** Draft · **Owner:** TBD · **Review refs:** `flows-and-batches-review.md` (CRITICAL #2, HIGH follow-ons)

## Why this exists

The flows/batches review flagged that **`complete_step`** (`POST /api/core/executions/<id>/steps/<id>/complete`) still uses a **partial-commit mental model**: `repo.complete_step(..., commit=False)`, **`flush`**, then validation, then **`rollback()`** on errors after work may already be flushed to the DB transaction (but uncommitted). That is fragile under concurrency and failure injection.

This document is the **tracked execution plan** for refactoring toward an **explicit atomic boundary**: one transaction per successful completion, failure paths rolled back by **one** mechanism (transaction context / exception), not scattered `rollback()` calls.

---

## Goals

| Goal | Success criterion |
|------|-------------------|
| **Single atomic unit** | Either the step completes **and** consumption/output side effects persist together, **or** none of them persist (same DB transaction). |
| **One rollback story** | Prefer **automatic** rollback on exception from the transaction API; reduce duplicate `rollback()` branches that can diverge. |
| **Preserved behaviour** | Same HTTP status codes and error payloads for validation failures; idempotent retries still safe where documented today. |
| **Observability** | Structured log / metric on unexpected failures during the atomic block (optional metric name TBD). |

## Non-goals (this phase)

- Rewriting business rules (quantities, ready-date checks, output typing).
- Replacing JSON `execution_data` with relational columns (separate initiative).
- Pagination / memory limits on `list_inventory` (separate).
- Denormalizing `org_id` onto `ExecutionStep` (optional future perf work).

---

## Current architecture (short)

**Primary surface:** `app/core/backend/backend.py` — `complete_step()` (~1701+).

**Flow (simplified):**

1. Merge auth into `execution_data`.
2. `ExecutionRepository.complete_step(..., commit=False)` → marks step completed, writes inputs/outputs JSON, sets `execution_data`.
3. `db_session.flush()`.
4. Consume inventory (row locks via `get_inventory_item_by_id_for_update`), build updates.
5. If `execution_errors` → **`db_session.rollback()`** → 400.
6. Create output inventory rows, expiry/custom expiry, etc.
7. More validation branches with **`rollback()`** + 400/500.
8. **`db_session.commit()`** on success.

**Repository:** `app/core/db/repositories/execution_repo.py` — `complete_step` sets state and optionally commits.

**Risk called out in review:** flush before validation completes → transaction still coherent if rollback works, but **multiple manual rollback sites** increase odds of missed paths and confusing session state after partial handler logic.

---

## Target architecture (directional)

Pick **one** pattern consistent with how `db_session` is managed app-wide (likely Flask-SQLAlchemy / scoped session):

### Option A — Explicit SQLAlchemy 2 style nested transaction

```python
with db_session.begin():
    # complete_step without internal commit
    # inventory + outputs in same block
    # commit implicit on context exit; rollback on exception
```

### Option B — Single “unit of work” function

Extract **`_complete_step_transactional(session, ...)`** that:

- Performs **all** DB mutations.
- Raises **`CompleteStepValidationError`** for expected validation failures (mapped to 400).
- Lets unexpected exceptions propagate → one rollback path.

Handler only: parse request → call unit of work → map exceptions to HTTP.

**Decision checkpoint:** Confirm whether `db_session` supports `begin()` as a nested transaction with the current engine configuration (PostgreSQL SAVEPOINT vs plain transaction). Document choice in this file under **Decisions**.

---

## Phased roadmap

Use checkboxes to track progress.

### Phase 0 — Discovery & baseline (1–2 days)

- [ ] **Inventory all call paths** that invoke `ExecutionRepository.complete_step` (including `commit=True` vs `commit=False`).
- [ ] **Map every `rollback()` / `commit()`** inside `complete_step` handler and nested helpers (grep `backend.py` around execution routes).
- [ ] **List integration tests** that cover step completion (or add a minimal smoke test if missing).
- [ ] **Document session lifecycle**: who creates `SessionLocal`, per-request scope, autocommit defaults.

**Deliverable:** Short appendix in this doc or a linked note: “touchpoints & rollback sites”.

### Phase 1 — Design sign-off

- [ ] Choose Option A vs B (or hybrid).
- [ ] Define **exception taxonomy**: validation vs programmer error vs infrastructure.
- [ ] Define **HTTP mapping** table (unchanged vs intentional tweaks).
- [ ] Resolve **flush placement**: avoid flush until validations that don’t need PK visibility are done; if flush required mid-flight, document why (e.g. FK generation).

**Deliverable:** Design section appended below **Decisions**.

### Phase 2 — Implement refactor (core)

- [ ] Introduce atomic boundary around the **whole** success path (complete step + inventory consumption + output inventory creates + audit fields).
- [ ] Replace scattered **`rollback()`** with **one** pattern (context manager or centralized `except` in handler).
- [ ] Ensure **`complete_step` repo** never commits mid-handler when used from HTTP route (single commit at end or implicit via `begin()`).
- [ ] Audit **`commit=False`** callers (reconciliation, scripts): verify they still control transaction outer boundary.

**Deliverable:** PR with focused diff; avoid unrelated refactors.

### Phase 3 — Tests

- [ ] **Happy path:** step completes, inventory consumed, outputs created, single commit.
- [ ] **Validation failure before side effects:** no partial inventory rows; step remains completable.
- [ ] **Failure after step marked completed in-session:** rollback restores prior step status (regression test for today’s comment at ~1734–1736).
- [ ] **Concurrency (optional):** two completes racing — expect one failure without corrupted quantities (best-effort depending on locks).

**Deliverable:** pytest integration tests against real DB or transactional fixtures.

### Phase 4 — Hardening & rollout

- [ ] Add **structured logging** on unexpected exceptions inside the atomic block (aligned with review MEDIUM #5).
- [ ] **Staging soak:** complete flows under load; watch DB deadlocks / lock waits.
- [ ] **Rollback plan:** tag release; if issues, revert PR (keep branch deployable).

---

## Related follow-ups (from review — not blocking this refactor)

Track separately; link PRs when started.

| Item | Notes |
|------|--------|
| **Residual N+1 on `Step.outputs`** | If `outputs` becomes a relationship without eager load, add `joinedload(ExecutionStep.step).joinedload(Step.outputs)` or confirm JSON column + no lazy load. |
| **Batch inventory join vs planner** | Consider subquery filter or future `ExecutionStep.org_id` denorm if profiling warrants. |
| **`execution_data` integrity** | Server-owned fields: schema validation / whitelist at persistence boundary (HIGH #3 in updated review). |

---

## Decisions log

| Date | Decision | Rationale |
|------|----------|-----------|
| _TBD_ | Option A vs B | _Fill after Phase 1_ |
| _TBD_ | Nested `begin()` vs flat transaction | _Depends on SQLAlchemy + Flask session setup_ |

---

## References (code)

| Area | Location |
|------|----------|
| HTTP handler | `app/core/backend/backend.py` — `complete_step` |
| Repository | `app/core/db/repositories/execution_repo.py` — `complete_step` |
| Session | `app/core/db/__init__.py` (or equivalent) — `db_session` / `SessionLocal` |
| Inventory locks | `InventoryRepository.get_inventory_item_by_id_for_update` |

---

## Review checklist (before merge)

- [ ] No new `rollback()` without pairing test or doc rationale.
- [ ] All `complete_step(..., commit=False)` call sites reviewed.
- [ ] Integration tests green in CI.
- [ ] Staging validation checklist completed.
