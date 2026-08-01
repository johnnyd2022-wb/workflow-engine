"""E2E tests for untracked-inventory reconciliation (.agents/specs/reconciliation.md).

Every test traces to an AC. AC4 (Path C — triggered internally from execution's
complete_step, not a route of its own), AC5 (row-level locking under concurrency), AC6
(invariant assertions), and AC7 (audit-trail internals) are unit/integration concerns
that don't have an independent E2E-observable surface beyond what AC2/AC3 already drive
through the real HTTP routes; not claimed as covered here (the skill's rule against
marking an AC covered by a test that doesn't genuinely exercise it end to end).

AC8 (tenant isolation) is the primary target: the spec flags it explicitly as unverified
by any existing test, and org-scoped mutation of another tenant's inventory balance is
the highest-severity failure mode this slice could have.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import csrf_headers
from tests.e2e.reconciliation.conftest import add_step, create_process, create_untracked_item

pytestmark = pytest.mark.e2e


def _matching_untracked(page, name: str, unit: str = "kg"):
    resp = page.request.get(
        "/api/core/inventory/reconcile/matching-untracked",
        params={"name": name, "unit": unit},
    )
    assert resp.status == 200, f"matching-untracked failed: {resp.status} {resp.text()}"
    return resp.json()["matching_untracked"]


# ---------------------------------------------------------------------------------
# AC1 — GET matching-untracked
# ---------------------------------------------------------------------------------


def test_ac1_matching_untracked_matches_name_case_insensitively_and_unit_exactly(logged_in_page: Page):
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    name = f"Reconcile Probe {marker}"

    match_id = create_untracked_item(page, name, 5, "kg")
    # Same name, different unit -> must not be returned (unit matches exactly).
    create_untracked_item(page, name, 5, "l")

    results = _matching_untracked(page, name, "kg")
    ids = [item["id"] for item in results]
    assert match_id in ids, f"expected untracked item not returned: {results}"
    assert len(ids) == 1, f"unit-mismatched item leaked into results: {results}"

    # Case-insensitive name match.
    upper_results = _matching_untracked(page, name.upper(), "kg")
    assert match_id in [item["id"] for item in upper_results], "name match is not case-insensitive"


def test_ac1_matching_untracked_missing_params_returns_empty_list_not_400(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get("/api/core/inventory/reconcile/matching-untracked")
    assert resp.status == 200, f"missing name/unit must be 200 with an empty list, got {resp.status}"
    assert resp.json() == {"matching_untracked": []}


def test_ac1_matching_untracked_excludes_fully_reconciled_item(logged_in_page: Page):
    """Once an untracked item's balance reaches 0, it drops out of the default (no
    execution_id) query -- the quantity<=0 exclusion clause AC1 specifies."""
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    name = f"Reconcile Drain {marker}"
    item_id = create_untracked_item(page, name, 2, "kg")

    drain = page.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page),
        data={"name": "Fully covers it", "quantity": 2, "unit": "kg", "untracked_item_id": item_id},
    )
    assert drain.status == 201, f"setup reconcile failed: {drain.status} {drain.text()}"
    assert Decimal(drain.json()["remaining_untracked_balance"]) == Decimal("0")

    after = _matching_untracked(page, name, "kg")
    assert item_id not in [i["id"] for i in after], f"fully-reconciled item still returned: {after}"


# ---------------------------------------------------------------------------------
# AC2 — POST via-addition
# ---------------------------------------------------------------------------------


def test_ac2_via_addition_happy_path_reconciles_partial_balance(logged_in_page: Page):
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    untracked_id = create_untracked_item(page, f"AC2 Happy {marker}", 5, "kg")
    new_name = f"AC2 New Batch {marker}"

    resp = page.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page),
        data={"name": new_name, "quantity": 3, "unit": "kg", "untracked_item_id": untracked_id},
    )
    assert resp.status == 201, f"via-addition failed: {resp.status} {resp.text()}"
    body = resp.json()
    # The new item holds the FULL added quantity, not reduced by the reconciliation.
    assert Decimal(body["quantity"]) == Decimal("3")
    assert Decimal(body["reconciled_amount"]) == Decimal("3")
    assert Decimal(body["surplus"]) == Decimal("0")
    assert Decimal(body["remaining_untracked_balance"]) == Decimal("2")

    listing = page.request.get("/api/core/inventory")
    assert new_name in listing.text(), "new inventory item not created"


def test_ac2_via_addition_unit_mismatch_rejected(logged_in_page: Page):
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    name = f"AC2 Mismatch {marker}"
    untracked_id = create_untracked_item(page, name, 5, "kg")

    resp = page.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page),
        data={"name": "Wrong unit batch", "quantity": 3, "unit": "l", "untracked_item_id": untracked_id},
    )
    assert resp.status == 400, f"expected 400 for unit mismatch, got {resp.status}"
    assert resp.json() == {"error": "Unit mismatch: cannot reconcile with different unit"}

    # Rejected attempt must not have mutated the untracked item's balance.
    results = _matching_untracked(page, name, "kg")
    assert Decimal(results[0]["quantity"]) == Decimal("5")


def test_ac2_via_addition_zero_balance_untracked_item_rejected(logged_in_page: Page):
    """Insufficient balance: an untracked item already fully reconciled cannot be
    reconciled again."""
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    untracked_id = create_untracked_item(page, f"AC2 Drained {marker}", 1, "kg")

    drain = page.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page),
        data={"name": "Drain it", "quantity": 1, "unit": "kg", "untracked_item_id": untracked_id},
    )
    assert drain.status == 201, f"setup drain failed: {drain.status} {drain.text()}"
    assert Decimal(drain.json()["remaining_untracked_balance"]) == Decimal("0")

    resp = page.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page),
        data={"name": "Second attempt", "quantity": 1, "unit": "kg", "untracked_item_id": untracked_id},
    )
    assert resp.status == 400, f"expected 400 for zero-balance untracked item, got {resp.status}"
    assert resp.json() == {"error": "Untracked item has no balance to reconcile"}


# ---------------------------------------------------------------------------------
# AC3 — POST via-execution
# ---------------------------------------------------------------------------------


def test_ac3_via_execution_happy_path_creates_execution_and_reduces_untracked(logged_in_page: Page):
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    pid = create_process(page, f"AC3 Process {marker}", is_draft=True)
    sid = add_step(page, pid, 1, "Mix")
    output_name = f"AC3 Output {marker}"
    untracked_id = create_untracked_item(page, output_name, 5, "kg")

    resp = page.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page),
        data={
            "untracked_item_id": untracked_id,
            "process_id": pid,
            "step_id": sid,
            "output_name": output_name,
            "output_quantity": 2,
            "output_unit": "kg",
        },
    )
    assert resp.status == 201, f"via-execution failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body["inventory_created"] is True
    assert Decimal(body["reconciled_amount"]) == Decimal("2")
    assert Decimal(body["surplus"]) == Decimal("0")
    assert Decimal(body["remaining_untracked_balance"]) == Decimal("3")

    # A real execution now exists against this process.
    ex = page.request.get(f"/api/core/executions/{body['execution_id']}/with-process")
    assert ex.status == 200, f"execution not readable after reconcile: {ex.status}"

    # The declared output landed as a new inventory row.
    listing = page.request.get("/api/core/inventory")
    assert output_name in listing.text()


def test_ac3_via_execution_idempotency_guard_rejects_second_identical_reconcile(logged_in_page: Page):
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    pid = create_process(page, f"AC3 Idempotent Process {marker}", is_draft=True)
    sid = add_step(page, pid, 1, "Mix")
    output_name = f"AC3 Idempotent Output {marker}"
    untracked_id = create_untracked_item(page, output_name, 5, "kg")

    payload = {
        "untracked_item_id": untracked_id,
        "process_id": pid,
        "step_id": sid,
        "output_name": output_name,
        "output_quantity": 2,
        "output_unit": "kg",
    }
    first = page.request.post("/api/core/inventory/reconcile/via-execution", headers=csrf_headers(page), data=payload)
    assert first.status == 201, f"first reconcile failed: {first.status} {first.text()}"

    second = page.request.post("/api/core/inventory/reconcile/via-execution", headers=csrf_headers(page), data=payload)
    assert second.status == 400, f"re-submitting the same process/step must be rejected, got {second.status}"
    assert second.json() == {
        "error": "This untracked item has already been reconciled against this process step."
    }

    # The balance was only reduced once: a silent double-spend on the rejected resubmit
    # would show 1, not 3.
    results = _matching_untracked(page, output_name, "kg")
    assert Decimal(results[0]["quantity"]) == Decimal("3"), "second reconcile must not have double-spent the balance"


# ---------------------------------------------------------------------------------
# AC8 — tenant isolation (unverified per spec; the primary target of this suite)
#
# Each test compares a request naming a real object that belongs to the OTHER org
# against an otherwise-identical request naming a random id that doesn't exist anywhere.
# AC8 requires these two cases to be indistinguishable -- same status, same body -- so a
# caller can never learn "that id exists, just not for you" versus "that id doesn't
# exist". Hardcoding an expected status would test the wrong thing; the differential
# comparison is the actual requirement.
# ---------------------------------------------------------------------------------


def test_ac8_via_addition_cross_org_untracked_item_id_indistinguishable_from_nonexistent(two_org_sessions):
    page_a, page_b = two_org_sessions["a"], two_org_sessions["b"]
    marker = uuid.uuid4().hex[:8]
    name = f"AC8 Victim (via-addition) {marker}"
    victim_item_id = create_untracked_item(page_b, name, 5, "kg")

    cross_org = page_a.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page_a),
        data={"name": "Attempted steal", "quantity": 1, "unit": "kg", "untracked_item_id": victim_item_id},
    )
    nonexistent = page_a.request.post(
        "/api/core/inventory/reconcile/via-addition",
        headers=csrf_headers(page_a),
        data={"name": "Attempted steal 2", "quantity": 1, "unit": "kg", "untracked_item_id": str(uuid.uuid4())},
    )

    assert cross_org.status not in (200, 201), "org A reconciled against org B's untracked item"
    assert cross_org.status == nonexistent.status, (
        f"cross-org id gave {cross_org.status} but a nonexistent id gave {nonexistent.status} — "
        "this difference alone would let a caller distinguish 'exists in another org' from 'doesn't exist'"
    )
    assert cross_org.json() == nonexistent.json() == {"error": "Untracked item not found"}

    # Org B's actual item is untouched by org A's rejected attempt.
    victim_results = _matching_untracked(page_b, name, "kg")
    assert Decimal(victim_results[0]["quantity"]) == Decimal("5")


def test_ac8_via_execution_cross_org_untracked_item_id_indistinguishable_from_nonexistent(two_org_sessions):
    page_a, page_b = two_org_sessions["a"], two_org_sessions["b"]
    marker = uuid.uuid4().hex[:8]
    pid = create_process(page_a, f"AC8 Process For Item Probe {marker}", is_draft=True)
    sid = add_step(page_a, pid, 1, "Step")
    name = f"AC8 Victim (via-execution) {marker}"
    victim_item_id = create_untracked_item(page_b, name, 5, "kg")

    cross_org = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": victim_item_id,
            "process_id": pid,
            "step_id": sid,
            "output_name": "Attempted steal",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    nonexistent = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": str(uuid.uuid4()),
            "process_id": pid,
            "step_id": sid,
            "output_name": "Attempted steal 2",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )

    assert cross_org.status not in (200, 201), "org A reconciled against org B's untracked item"
    assert cross_org.status == nonexistent.status, (
        f"cross-org id gave {cross_org.status} but a nonexistent id gave {nonexistent.status}"
    )
    assert cross_org.json() == nonexistent.json() == {"error": "Untracked item not found"}

    victim_results = _matching_untracked(page_b, name, "kg")
    assert Decimal(victim_results[0]["quantity"]) == Decimal("5")


def test_ac8_via_execution_cross_org_step_id_indistinguishable_from_nonexistent(two_org_sessions):
    """A step_id from org B's process, submitted against org A's OWN process_id, must be
    rejected identically to a step_id that doesn't exist anywhere."""
    page_a, page_b = two_org_sessions["a"], two_org_sessions["b"]
    marker = uuid.uuid4().hex[:8]
    process_a = create_process(page_a, f"AC8 Own Process {marker}", is_draft=True)
    add_step(page_a, process_a, 1, "Own Step")
    process_b = create_process(page_b, f"AC8 Victim Process For Step {marker}", is_draft=True)
    victim_step = add_step(page_b, process_b, 1, "Victim Step")
    untracked_id = create_untracked_item(page_a, f"AC8 Step Probe {marker}", 5, "kg")

    cross_org = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": untracked_id,
            "process_id": process_a,
            "step_id": victim_step,
            "output_name": "Attempted steal",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    nonexistent = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": untracked_id,
            "process_id": process_a,
            "step_id": str(uuid.uuid4()),
            "output_name": "Attempted steal 2",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )

    assert cross_org.status not in (200, 201), "org A ran org B's step via reconcile-via-execution"
    assert cross_org.status == nonexistent.status == 400
    assert cross_org.json() == nonexistent.json() == {"error": "Step not found in this process"}


def test_ac8_via_execution_cross_org_process_id_indistinguishable_from_nonexistent(two_org_sessions):
    """org A must not be able to run org B's process via reconcile-via-execution, and a
    process_id belonging to another org must fail identically to one that doesn't exist
    at all (ExecutionRepository.create_execution's org-membership check).

    As of this audit both cases surface as an unhandled exception (HTTP 500) rather than
    the graceful 400 the untracked_item_id/step_id checks return -- see the E2E report:
    a robustness gap worth its own fix, but not itself an AC8 violation, since the two
    cases stay indistinguishable from a caller's viewpoint (asserted below).
    """
    page_a, page_b = two_org_sessions["a"], two_org_sessions["b"]
    marker = uuid.uuid4().hex[:8]
    process_b = create_process(page_b, f"AC8 Victim Process {marker}", is_draft=True)
    add_step(page_b, process_b, 1, "Victim Step")
    name = f"AC8 Own Item {marker}"
    untracked_id = create_untracked_item(page_a, name, 5, "kg")

    cross_org = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": untracked_id,
            "process_id": process_b,
            "step_id": str(uuid.uuid4()),
            "output_name": "Attempted steal",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )
    nonexistent = page_a.request.post(
        "/api/core/inventory/reconcile/via-execution",
        headers=csrf_headers(page_a),
        data={
            "untracked_item_id": untracked_id,
            "process_id": str(uuid.uuid4()),
            "step_id": str(uuid.uuid4()),
            "output_name": "Attempted steal 2",
            "output_quantity": 1,
            "output_unit": "kg",
        },
    )

    assert cross_org.status not in (200, 201), "org A ran org B's process via reconcile-via-execution"
    assert cross_org.status == nonexistent.status, (
        f"cross-org process_id gave {cross_org.status} but a nonexistent one gave {nonexistent.status} — "
        "a distinguishable failure would leak that the id exists in another org"
    )
    assert cross_org.text() == nonexistent.text(), "response bodies differ between cross-org and nonexistent process_id"

    # Org A's own untracked item balance must be untouched by either rejected attempt.
    results = _matching_untracked(page_a, name, "kg")
    assert Decimal(results[0]["quantity"]) == Decimal("5")
