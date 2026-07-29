"""CSV bulk-upload flow: validate (preview, no write) then commit (writes, re-validates).

AC20-AC25 (.agents/specs/inventory.md). The client's csv-validate result is advisory only
— csv-commit re-runs `_validate_row` itself and must never trust what the browser sent, so
the unhappy paths here attack that boundary directly rather than just checking shapes.
"""

import uuid

import pytest

from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

CSV_MAX_BYTES = 2 * 1024 * 1024
CSV_MAX_ROWS = 500


def _validate(page, text: str | None = None, file_bytes: bytes | None = None, filename: str = "items.csv"):
    if file_bytes is not None:
        return page.request.post(
            "/api/core/inventory/csv-validate",
            headers=csrf_headers(page),
            multipart={"file": {"name": filename, "mimeType": "text/csv", "buffer": file_bytes}},
        )
    return page.request.post(
        "/api/core/inventory/csv-validate",
        headers=csrf_headers(page),
        data=text,
    )


def _commit(page, rows: list[dict]):
    return page.request.post(
        "/api/core/inventory/csv-commit",
        headers=csrf_headers(page),
        data={"rows": rows},
    )


def test_csv_validate_happy_path_returns_per_row_status(logged_in_page):
    """AC20/AC21: valid rows preview as 'ok' with no write."""
    page = logged_in_page
    name = f"E2E CSV Valid {uuid.uuid4().hex[:8]}"
    csv_text = f"Item Name,Quantity,Unit\n{name},10,kg\n"

    resp = _validate(page, text=csv_text)
    assert resp.status == 200, f"validate failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body["validated_count"] == 1
    assert body["validation"] == [{"row_index": 2, "status": "ok", "message": ""}]
    assert body["truncated"] is False

    # No write happened — the item must not exist yet. test-evaluator round 2: the listing
    # request's own success must be checked first, or a broken/500'ing listing endpoint
    # would make `name not in listing.text()` trivially true for the wrong reason.
    listing = page.request.get("/api/core/inventory")
    assert listing.status == 200, f"listing failed: {listing.status} {listing.text()}"
    assert name not in listing.text(), "csv-validate wrote a row; it must only preview"


def test_csv_validate_row_level_errors(logged_in_page):
    """AC21: blank name, non-numeric/non-positive quantity, and disallowed unit each error
    with a specific per-row message, independent of the other rows in the batch."""
    page = logged_in_page
    csv_text = (
        "Item Name,Quantity,Unit\n"
        ",5,kg\n"
        "Bad Qty,not-a-number,kg\n"
        "Zero Qty,0,kg\n"
        "Bad Unit,5,furlongs\n"
    )
    resp = _validate(page, text=csv_text)
    assert resp.status == 200, f"validate failed: {resp.status} {resp.text()}"
    validation = resp.json()["validation"]
    assert [v["status"] for v in validation] == ["error", "error", "error", "error"]
    assert validation[0]["message"] == "Item name is required"
    assert validation[1]["message"] == "Invalid quantity (must be a positive number)"
    assert validation[2]["message"] == "Invalid quantity (must be a positive number)"
    assert validation[3]["message"] == "Unit not allowed"


def test_csv_validate_rejects_missing_required_columns(logged_in_page):
    """AC20: Item Name / Quantity / Unit are all required columns (case-insensitive).
    test-evaluator round 2: the original test only ever dropped Unit, so a regression that
    stopped checking for a missing Item Name or Quantity column would still have passed."""
    page = logged_in_page

    resp = _validate(page, text="Item Name,Quantity\nWidget,5\n")
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "unit" in resp.json()["error"].lower()

    resp = _validate(page, text="Quantity,Unit\n5,kg\n")
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "item name" in resp.json()["error"].lower()

    resp = _validate(page, text="Item Name,Unit\nWidget,kg\n")
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "quantity" in resp.json()["error"].lower()


def test_csv_validate_rejects_oversized_file(logged_in_page):
    """AC20: a file over 2MB is rejected outright."""
    page = logged_in_page
    oversized = b"Item Name,Quantity,Unit\n" + (b"a" * (CSV_MAX_BYTES + 1024))
    resp = _validate(page, file_bytes=oversized)
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "2mb" in resp.json()["error"].lower() or "large" in resp.json()["error"].lower()


def test_csv_validate_rejects_non_utf8_file(logged_in_page):
    """AC20: non-UTF-8 file content is rejected rather than silently mangled."""
    page = logged_in_page
    # 0xFF is not valid UTF-8 (nor a valid continuation byte in any sequence).
    bad_bytes = b"Item Name,Quantity,Unit\nWidget,5,kg\n" + b"\xff\xfe"
    resp = _validate(page, file_bytes=bad_bytes)
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    assert "utf-8" in resp.json()["error"].lower()


def test_csv_validate_truncates_over_max_rows(logged_in_page):
    """AC22: validate truncates at CSV_MAX_ROWS and reports truncated: true."""
    page = logged_in_page
    header = "Item Name,Quantity,Unit\n"
    rows = "".join(f"Row {i},1,kg\n" for i in range(CSV_MAX_ROWS + 5))
    resp = _validate(page, text=header + rows)
    assert resp.status == 200, f"validate failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body["truncated"] is True
    assert body["validated_count"] == CSV_MAX_ROWS


def test_csv_commit_happy_path_creates_item_with_audit_history(logged_in_page):
    """AC23/AC25: a valid row commits and records CSV provenance in inventory_audit_history
    — source_method, row index, and a UTC timestamp. The acting-user assertion (AC25's
    other requirement) is NOT checked here: `GET /api/core/inventory` deliberately strips
    `user_id` from audit-history entries for list responses
    (`_bound_inventory_extra_data_for_list_response`, backend.py — "operator UI only"), so
    it can never be observed through this endpoint. That half of AC25 is proven at the DB
    level instead — see
    test_csv_commit_records_acting_user_in_audit_history in tests/test_inventory.py."""
    page = logged_in_page
    name = f"E2E CSV Commit {uuid.uuid4().hex[:8]}"
    rows = [{"row_index": 2, "name": name, "quantity": "10", "unit": "kg"}]

    resp = _commit(page, rows)
    assert resp.status == 200, f"commit failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert len(body["created"]) == 1
    assert body["errors"] == []
    assert body["created"][0]["row_index"] == 2

    listing = page.request.get("/api/core/inventory").json()
    item = next(i for i in listing["inventory_items"] if i["id"] == body["created"][0]["id"])
    history = item["extra_data"]["inventory_audit_history"]
    entry = history[-1]
    assert entry["source_method"] == "csv_upload"
    assert entry["csv_row_index"] == 2
    assert entry["timestamp_utc"].endswith("Z"), f"AC25 requires a UTC timestamp, got {entry['timestamp_utc']!r}"


def test_csv_commit_rejects_over_max_rows(logged_in_page):
    """AC22: commit rejects outright (400) when the row count exceeds CSV_MAX_ROWS, unlike
    validate which merely truncates. test-evaluator round 2: the original test checked only
    the status code, so a partial-commit-then-400 implementation would still have passed —
    prove zero of the batch's distinctively-named rows were written."""
    page = logged_in_page
    marker = uuid.uuid4().hex[:8]
    rows = [
        {"row_index": i + 2, "name": f"E2E OverMaxRow {marker} {i}", "quantity": "1", "unit": "kg"}
        for i in range(CSV_MAX_ROWS + 1)
    ]
    resp = _commit(page, rows)
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"

    listing = page.request.get("/api/core/inventory")
    assert listing.status == 200, f"listing failed: {listing.status} {listing.text()}"
    assert marker not in listing.text(), "an over-max-rows commit still wrote some of the batch"


def test_csv_commit_revalidates_server_side_and_writes_nothing_on_failure(logged_in_page):
    """AC23: commit re-validates every row itself — a row the client never checked (or
    checked wrongly) is caught here, and when ANY row fails, nothing is written at all."""
    page = logged_in_page
    good_name = f"E2E CSV ShouldNotExist {uuid.uuid4().hex[:8]}"
    rows = [
        {"row_index": 2, "name": good_name, "quantity": "10", "unit": "kg"},
        {"row_index": 3, "name": "Bad Row", "quantity": "-5", "unit": "kg"},
    ]

    resp = _commit(page, rows)
    assert resp.status == 400, f"expected 400, got {resp.status}: {resp.text()}"
    body = resp.json()
    assert body["created"] == []
    assert any(e["row_index"] == 3 for e in body["errors"])

    listing = page.request.get("/api/core/inventory")
    assert good_name not in listing.text(), "a valid row committed even though a sibling row failed re-validation"


def test_csv_commit_skips_duplicate_batch_but_commits_the_rest(logged_in_page):
    """AC24: a row colliding on (org, item name, batch number) is skipped with a per-row
    error; the other rows in the same commit still succeed."""
    page = logged_in_page
    dup_name = f"E2E CSV Dup {uuid.uuid4().hex[:8]}"
    batch = f"BATCH-{uuid.uuid4().hex[:6]}"
    other_name = f"E2E CSV Other {uuid.uuid4().hex[:8]}"

    # Pre-create the (name, batch) combination so the CSV row collides with it.
    precreate = page.request.post(
        "/api/core/inventory",
        headers=csrf_headers(page),
        data={
            "name": dup_name,
            "quantity": 1,
            "unit": "kg",
            "inventory_type": "raw_material",
            "supplier_batch_number": batch,
        },
    )
    assert precreate.status == 201, f"setup failed: {precreate.status} {precreate.text()}"

    rows = [
        {"row_index": 2, "name": dup_name, "quantity": "5", "unit": "kg", "batch_number": batch},
        {"row_index": 3, "name": other_name, "quantity": "5", "unit": "kg"},
    ]
    resp = _commit(page, rows)
    assert resp.status == 200, f"commit failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert len(body["created"]) == 1
    assert body["created"][0]["row_index"] == 3
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row_index"] == 2
    assert "skipped" in body["error"].lower()

    listing = page.request.get("/api/core/inventory").json()["inventory_items"]
    assert other_name in [i["name"] for i in listing], "the non-duplicate row did not commit alongside the skipped one"

    # test-evaluator round 2: the original test proved the OTHER row committed but never
    # checked the colliding (org, name, batch) tuple itself — prove the pre-created row's
    # count/quantity is exactly what it was before the collision, not bumped or duplicated.
    matching = [i for i in listing if i["name"] == dup_name]
    assert len(matching) == 1, f"expected exactly one row for the colliding name, found {len(matching)}"
    assert matching[0]["quantity"] == "1", "the collided row's quantity changed even though its CSV row was skipped"
