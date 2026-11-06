"""GL-C03: the inventory import's template, preview summary and error report.

The template comes from the server (the validator's own columns, plus Site when multiple
sites are on); the preview says how many rows are ready before the row-by-row review; the
error report is a CSV of just the problem rows with what is wrong, safe to open in a
spreadsheet.
"""

import csv
import io

from tests.test_sites import _add, _enable, flask_app, world  # noqa: F401 -- shared fixtures

GOOD_AND_BAD = (
    "Item Name,Quantity,Unit,Supplier Name\n"
    "Juniper,5,kg,Moore Wilson\n"
    ",3,kg,Nobody\n"
    "Coriander,-2,kg,Davis Trading\n"
    'Orris,1,furlongs,=HYPERLINK("http://evil")\n'
    "Angelica,2,kg,\n"
)


def _csv(resp):
    body = resp.get_data(as_text=True)
    assert body.startswith("﻿"), "BOM so Excel reads UTF-8"
    return list(csv.reader(io.StringIO(body[1:])))


def test_template_lists_the_columns_the_validator_reads(world):  # noqa: F811
    _, admin, _, _ = world
    resp = admin.get("/api/core/inventory/csv-template")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert 'filename="inventory_template.csv"' in resp.headers["Content-Disposition"]
    header, example = _csv(resp)
    assert header == ["Item Name", "Quantity", "Unit", "Supplier Name", "Purchase Date", "Batch Number", "Expiry Date"]
    # The template's own example row must pass the validator it was made for.
    text = ",".join(header) + "\n" + ",".join(example) + "\n"
    check = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert check["summary"] == {"rows": 1, "ready": 1, "problems": 0}


def test_template_gains_a_site_column_with_a_real_site_when_sites_are_on(world):  # noqa: F811
    _, admin, _, _ = world
    default = _enable(admin)
    _add(admin, name="Bond store")
    header, example = _csv(admin.get("/api/core/inventory/csv-template"))
    assert header[-1] == "Site"
    assert example[-1] == default["name"]
    text = ",".join(header) + "\n" + ",".join(example) + "\n"
    check = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert check["summary"]["problems"] == 0


def test_preview_summary_counts_ready_and_problem_rows(world):  # noqa: F811
    _, admin, _, _ = world
    res = admin.post("/api/core/inventory/csv-validate", data=GOOD_AND_BAD.encode(), content_type="text/csv").get_json()
    assert res["summary"] == {"rows": 5, "ready": 2, "problems": 3}


def test_error_report_has_only_the_problem_rows_with_their_problem_and_original_cells(world):  # noqa: F811
    _, admin, _, _ = world
    resp = admin.post("/api/core/inventory/csv-error-report", data=GOOD_AND_BAD.encode(), content_type="text/csv")
    assert resp.status_code == 200
    assert 'filename="inventory_import_problems.csv"' in resp.headers["Content-Disposition"]
    assert resp.headers["Cache-Control"] == "no-store"
    rows = _csv(resp)
    assert rows[0] == ["Row", "Problem", "Item Name", "Quantity", "Unit", "Supplier Name"]
    assert rows[1:] == [
        ["3", "Item name is required", "", "3", "kg", "Nobody"],
        ["4", "Invalid quantity (must be a positive number)", "Coriander", "'-2", "kg", "Davis Trading"],
        # A formula in the uploaded file comes back as text, never as a live formula.
        ["5", "Unit not allowed", "Orris", "1", "furlongs", '\'=HYPERLINK("http://evil")'],
    ]


def test_error_report_for_a_clean_file_is_just_the_header(world):  # noqa: F811
    _, admin, _, _ = world
    clean = "Item Name,Quantity,Unit\nJuniper,5,kg\n"
    rows = _csv(admin.post("/api/core/inventory/csv-error-report", data=clean.encode(), content_type="text/csv"))
    assert rows == [["Row", "Problem", "Item Name", "Quantity", "Unit"]]


def test_error_report_refuses_what_validate_refuses(world):  # noqa: F811
    _, admin, _, _ = world
    no_unit = admin.post(
        "/api/core/inventory/csv-error-report", data=b"Item Name,Quantity\nJuniper,5\n", content_type="text/csv"
    )
    assert no_unit.status_code == 400
    assert "Missing required columns" in no_unit.get_json()["error"]
    bad_utf8 = admin.post(
        "/api/core/inventory/csv-error-report", data=b"Item Name,Quantity,Unit\n\xff,1,kg\n", content_type="text/csv"
    )
    assert bad_utf8.status_code == 400


def test_preview_flags_an_unknown_site_the_way_commit_would(world):  # noqa: F811
    """Before this, a bad Site name passed the preview and only failed after the review."""
    _, admin, _, _ = world
    _enable(admin)
    text = "Item Name,Quantity,Unit,Site\nCassia,1,kg,Petone\nCumin,1,kg,main site\n"
    res = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert [v["message"] for v in res["validation"]] == ["No active site called Petone", ""]
    report = _csv(admin.post("/api/core/inventory/csv-error-report", data=text.encode(), content_type="text/csv"))
    assert report[1][:2] == ["2", "No active site called Petone"]


def test_preview_flags_a_site_column_while_sites_are_off(world):  # noqa: F811
    _, admin, _, _ = world
    text = "Item Name,Quantity,Unit,Site\nCassia,1,kg,Main site\n"
    res = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert res["validation"][0]["status"] == "error"
    assert "multiple sites are off" in res["validation"][0]["message"]


def test_a_blank_site_column_is_still_flagged_while_sites_are_off(world):  # noqa: F811
    """The Site check is per column: blank cells used to pass it (breaker-codex, !634 round 1)."""
    _, admin, _, _ = world
    text = "Item Name,Quantity,Unit,Site\nCassia,1,kg,\nCumin,1,kg,Main site\n"
    res = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert [v["status"] for v in res["validation"]] == ["error", "error"]
    assert all("multiple sites are off" in v["message"] for v in res["validation"])
    assert res["summary"]["ready"] == 0


def test_a_blank_site_cell_is_fine_while_sites_are_on(world):  # noqa: F811
    _, admin, _, _ = world
    _enable(admin)
    text = "Item Name,Quantity,Unit,Site\nCassia,1,kg,\n"
    res = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert res["validation"][0]["status"] == "ok"


def test_another_orgs_site_name_is_unknown_here(world):  # noqa: F811
    _, admin, _, neighbour = world
    _enable(admin)
    _enable(neighbour)
    _add(neighbour, name="Neighbour bond")
    text = "Item Name,Quantity,Unit,Site\nCassia,1,kg,Neighbour bond\n"
    res = admin.post("/api/core/inventory/csv-validate", data=text.encode(), content_type="text/csv").get_json()
    assert res["validation"][0]["message"] == "No active site called Neighbour bond"
    header, example = _csv(admin.get("/api/core/inventory/csv-template"))
    assert example[-1] != "Neighbour bond"
