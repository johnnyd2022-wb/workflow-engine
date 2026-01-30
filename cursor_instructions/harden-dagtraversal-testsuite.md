# DAG Traversal – Test Suite Hardening (Production-Grade Guarantees)

## Scope (IMPORTANT)

⚠️ **These instructions apply to the TEST SUITE ONLY.**

- ❌ Do NOT modify DAG traversal implementation code
- ❌ Do NOT refactor traversal logic, SQL, or algorithms
- ❌ Do NOT change production behavior

✅ The purpose of this work is to **harden the test suite** so that:
- Performance regressions are detected
- Correctness invariants are enforced
- Future refactors are constrained and safe

The tests should *fail loudly* if the traversal ever becomes incorrect, non-deterministic, or inefficient.

---

## Goal

Upgrade the DAG traversal test suite to enforce **production-grade guarantees** around:

- Graph correctness
- Deterministic output
- Cycle safety
- Query efficiency (no N+1 regressions)
- Data integrity (ID-based lineage only)

The test suite should encode the *rules of reality* for this system.

---

## 1. Enforce Graph Correctness Invariants in Tests

For **every traversal result**, add assertions enforcing:

### Node / Edge Consistency
- Every `edge.from_id` MUST exist in `nodes`
- Every `edge.to_id` MUST exist in `nodes`
- No dangling edges are allowed

### Uniqueness
- Nodes are unique by `id`
- Edges are unique by `(from_id, to_id, execution_id)`

### Execution Integrity
- Every edge references a valid `execution_id`
- All nodes and edges in a result belong to the same traversal context

These checks must live in shared test helpers and be reused across traversal tests.

---

## 2. Add Synthetic DAG Fixtures (Tests Only)

Do NOT rely on demo, reset, or seed data.

Create **small, deterministic, synthetic DAGs** directly in tests.

### Required Test DAGs

#### A. Linear DAG
R1 -> W1 -> F1


Assertions:
- Nodes == `{R1, W1, F1}`
- Edges == `{R1->W1, W1->F1}`
- Forward traversal from `R1` returns all nodes
- Backward traversal from `F1` returns all nodes
- No extra nodes or edges

---

#### B. Branching DAG
  -> W2 ->
R1 -> W1 -> F1
-> W3 ->


Assertions:
- All branches are included
- No duplicate nodes or edges
- Traversal includes shared ancestors only once

---

## 3. Explicit Cycle Safety Test

Create a **known cyclic graph** in test data:

A -> B -> C -> A


Test expectations:
- Traversal terminates
- Each node appears exactly once
- Each edge appears exactly once
- No recursion error or infinite loop

This test exists solely to **catch regressions** if cycle protection is ever removed.

---

## 4. Enforce Deterministic Output (Tests Must Prove This)

Traversal results must be deterministic.

### Required Test Assertions
- Running the same traversal twice produces:
  - Identical node order
  - Identical edge order

### Notes
- Tests should explicitly compare ordered outputs
- Do NOT rely on DB row ordering
- If traversal output is unstable, the test should fail

---

## 5. Guard Against Recursive Traversal Regressions

Even though traversal is currently implemented safely:

- Add tests that traverse **large synthetic DAGs**
- Assert traversal completes without recursion errors or stack overflow

This test ensures future refactors don’t accidentally reintroduce unsafe recursion.

---

## 6. Enforce ID-Only Lineage (No Name-Based Matching)

### Hard Rule (Tests Only)
- Traversal correctness must depend **only on IDs**
- Name-based matching is forbidden

### Test Requirement
- Add a test where:
  - Names overlap or are misleading
  - IDs are distinct
- Assert traversal uses IDs and produces correct lineage

This test must fail if name-based fallback logic is reintroduced.

---

## 7. Detect N+1 Query Regressions

Traversal must not issue per-node or per-edge queries.

### Examples of N+1 Patterns to Guard Against
- Querying executions inside a traversal loop
- Fetching steps one-by-one
- Lazy-loading relationships during traversal

### Test Strategy
- Instrument DB query counting during traversal
- Assert total query count stays below a fixed threshold

This is a **regression sentinel**, not a performance benchmark.

---

## 8. Harden Enrichment Tests

Traversal enrichment must be resilient.

Add tests that assert:
- Traversal succeeds when enrichment data exists
- Traversal succeeds when enrichment data is missing
- Missing enrichment does NOT break graph correctness

Do NOT assume demo data completeness.

---

## 9. Eliminate Silent Test Skips

Traversal tests must not be skipped due to missing data.

If required data is missing:
- Create it explicitly in the test
- Or use synthetic fixtures

Silent skips are not acceptable for core DAG correctness.

---

## 10. Acceptance Criteria (Tests Only)

This work is complete only when:

- All traversal invariants are enforced in tests
- Cycles are explicitly tested
- Deterministic output is asserted
- ID-only lineage is enforced
- N+1 regressions are guarded
- No production traversal code was modified

If any of these fail, the test suite should fail loudly.