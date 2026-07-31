"""Unit tests for the pure CSV validation helpers in inventory_upload_routes.py.

`_validate_row` is the single shared validator called by both csv-validate (preview) and
csv-commit (server-side re-validation) — AC21/AC23. A defect in any of these helpers
silently affects both paths at once, and none of them need a DB or a running server, so
they belong here rather than behind an authenticated route call.
"""

from datetime import date

from app.core.backend.inventory_upload_routes import (
    _allowed_units_list,
    _parse_date,
    _parse_quantity,
    _sanitize,
    _unit_to_canonical,
    _validate_row,
)
from app.core.utils.unit_conversion import CONVERSION_FACTORS

# --- _allowed_units_list ----------------------------------------------------------------


def test_allowed_units_list_matches_conversion_factors_keys():
    """The dropdown list must be derived from CONVERSION_FACTORS, not a separate hand-kept
    list — this IS the single-source-of-truth contract AC27 depends on."""
    values = {u["value"].lower() for u in _allowed_units_list()}
    assert values == set(CONVERSION_FACTORS.keys())


def test_allowed_units_list_prefers_display_case_for_l_and_ml():
    out = {u["value"] for u in _allowed_units_list()}
    assert "L" in out
    assert "mL" in out
    assert "l" not in out
    assert "ml" not in out


# --- _unit_to_canonical ------------------------------------------------------------------


def test_unit_to_canonical_accepts_known_unit_case_insensitively():
    assert _unit_to_canonical("KG") == "kg"
    assert _unit_to_canonical("  kg  ") == "kg"


def test_unit_to_canonical_maps_l_and_ml_to_display_form():
    assert _unit_to_canonical("l") == "L"
    assert _unit_to_canonical("ML") == "mL"


def test_unit_to_canonical_accepts_already_display_cased_l_and_ml():
    assert _unit_to_canonical("L") == "L"
    assert _unit_to_canonical("mL") == "mL"


def test_unit_to_canonical_rejects_unit_outside_conversion_factors():
    assert _unit_to_canonical("furlongs") is None
    assert _unit_to_canonical("") is None
    assert _unit_to_canonical(None) is None


# --- _parse_quantity -----------------------------------------------------------------------


def test_parse_quantity_accepts_positive_numeric_string():
    ok, value = _parse_quantity("10.5")
    assert ok is True
    assert value == "10.5"


def test_parse_quantity_rejects_zero():
    ok, value = _parse_quantity("0")
    assert ok is False
    assert value is None


def test_parse_quantity_rejects_negative():
    ok, value = _parse_quantity("-5")
    assert ok is False


def test_parse_quantity_rejects_blank():
    ok, value = _parse_quantity("   ")
    assert ok is False


def test_parse_quantity_rejects_non_numeric():
    ok, value = _parse_quantity("not-a-number")
    assert ok is False


def test_parse_quantity_preserves_original_precision_string():
    """The sanitized string is stored verbatim (not re-rendered) — precision must survive."""
    ok, value = _parse_quantity("3.140000")
    assert ok is True
    assert value == "3.140000"


# --- _validate_row (the shared preview/commit validator) ----------------------------------


def test_validate_row_ok_for_a_clean_row():
    status, message, canonical_unit, quantity_str = _validate_row("Widget", "5", "kg")
    assert status == "ok"
    assert message == ""
    assert canonical_unit == "kg"
    assert quantity_str == "5"


def test_validate_row_rejects_blank_name():
    status, message, _canonical_unit, _quantity_str = _validate_row("", "5", "kg")
    assert status == "error"
    assert message == "Item name is required"


def test_validate_row_rejects_blank_quantity_with_specific_message():
    status, message, _u, _q = _validate_row("Widget", "", "kg")
    assert status == "error"
    assert message == "Quantity is required"


def test_validate_row_rejects_non_numeric_quantity_with_specific_message():
    status, message, _u, _q = _validate_row("Widget", "abc", "kg")
    assert status == "error"
    assert message == "Invalid quantity (must be a positive number)"


def test_validate_row_rejects_zero_quantity_with_specific_message():
    status, message, _u, _q = _validate_row("Widget", "0", "kg")
    assert status == "error"
    assert message == "Invalid quantity (must be a positive number)"


def test_validate_row_rejects_blank_unit():
    status, message, _u, _q = _validate_row("Widget", "5", "")
    assert status == "error"
    assert message == "Unit is required"


def test_validate_row_rejects_unit_outside_conversion_factors():
    status, message, _u, _q = _validate_row("Widget", "5", "furlongs")
    assert status == "error"
    assert message == "Unit not allowed"


def test_validate_row_name_error_takes_precedence_over_other_fields():
    """Row-level validation stops at the first failing field (name), matching the CSV
    preview's per-row single-message contract."""
    status, message, _u, _q = _validate_row("", "not-a-number", "furlongs")
    assert status == "error"
    assert message == "Item name is required"


# --- _parse_date (three accepted formats) -------------------------------------------------


def test_parse_date_accepts_iso_format():
    assert _parse_date("2026-03-05") == date(2026, 3, 5)


def test_parse_date_accepts_day_first_format():
    assert _parse_date("05/03/2026") == date(2026, 3, 5)


def test_parse_date_accepts_month_first_format():
    """MM/DD/YYYY is the third format tried, so it must be reached by an input the first
    two reject: "03/13/2026" fails %d/%m/%Y (month 13 doesn't exist) and falls through.

    The previous input here was "13/03/2026", which %d/%m/%Y parses on its own — so
    deleting %m/%d/%Y support entirely left this test green (test-evaluator round 3,
    caught by executed mutation).
    """
    assert _parse_date("03/13/2026") == date(2026, 3, 13)


def test_parse_date_returns_none_for_unparseable_string():
    assert _parse_date("not a date") is None


def test_parse_date_returns_none_for_blank_or_none():
    assert _parse_date("") is None
    assert _parse_date(None) is None


# --- _sanitize (control-char stripping + length truncation) -------------------------------


def test_sanitize_strips_control_characters():
    assert _sanitize("Wid\x01get\x1f") == "Widget"


def test_sanitize_preserves_tab_newline_and_printable_chars():
    """Only the C0 control range minus \\t\\n\\r is stripped — see the regex's explicit gaps.

    The characters the name promises must actually be in the input: the previous version
    passed only "Café Ünïcode", so a mutation stripping ALL C0 controls (tab and newline
    included) left it green (test-evaluator round 3, caught by executed mutation).
    Internal tabs/newlines survive; leading and trailing ones are removed by strip(),
    which is what test_sanitize_strips_surrounding_whitespace covers.
    """
    assert _sanitize("Café\tÜnïcode\nBatch\r\n7") == "Café\tÜnïcode\nBatch\r\n7"
    assert _sanitize("Widget\x00\x07Batch") == "WidgetBatch", "C0 controls outside \\t\\n\\r must go"


def test_sanitize_strips_surrounding_whitespace():
    assert _sanitize("  Widget  ") == "Widget"


def test_sanitize_truncates_to_default_500_chars():
    long_name = "a" * 600
    result = _sanitize(long_name)
    assert len(result) == 500


def test_sanitize_truncates_to_explicit_255_chars():
    long_name = "b" * 300
    result = _sanitize(long_name, 255)
    assert len(result) == 255


def test_sanitize_returns_empty_string_for_none():
    assert _sanitize(None) == ""


def test_sanitize_does_not_truncate_short_strings():
    assert _sanitize("short", 255) == "short"
