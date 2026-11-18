"""The overlay loader refuses the mistakes that would quietly publish a broken description, and the
generator keeps internal tracking ids out of the document (found by the 8.2f review)."""

from __future__ import annotations

import pytest

from app.api.openapi.generator import docstring_parts
from app.api.openapi.overlay import OverlayError, load_overlay


def _load(tmp_path, text):
    (tmp_path / "x.yaml").write_text(text, encoding="utf-8")
    return load_overlay(tmp_path)


def test_a_comma_in_an_unquoted_flow_description_is_refused(tmp_path):
    with pytest.raises(OverlayError, match="cut at a comma"):
        _load(tmp_path, "schemas:\n  S: {type: string, description: one, two}\n")


def test_a_bare_yes_or_on_key_is_refused(tmp_path):
    with pytest.raises(OverlayError, match="not text"):
        _load(tmp_path, "schemas:\n  S:\n    type: object\n    properties:\n      on: {type: string}\n")


def test_a_repeated_key_unknown_key_and_unquoted_date_are_refused(tmp_path):
    with pytest.raises(OverlayError):
        _load(tmp_path, "operations:\n  a: {summary: x}\n  a: {summary: y}\n")
    with pytest.raises(OverlayError, match="unknown keys"):
        _load(tmp_path, "operations:\n  a: {sumary: x}\n")
    with pytest.raises(OverlayError, match="plain JSON"):
        _load(tmp_path, "operations:\n  a:\n    response:\n      schema: {type: string}\n      example: 2026-11-16\n")


def test_a_malformed_entry_is_an_overlay_error_not_a_crash(tmp_path):
    with pytest.raises(OverlayError):
        _load(tmp_path, "operations:\n  a:\n    response: nope\n")
    with pytest.raises(OverlayError):
        _load(tmp_path, "operations:\n  a:\n    parameters: [nope]\n")


def test_the_same_operation_in_two_files_is_refused(tmp_path):
    (tmp_path / "a.yaml").write_text("operations:\n  one: {summary: x}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("operations:\n  one: {summary: y}\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="another overlay file"):
        load_overlay(tmp_path)


@pytest.mark.parametrize(
    ("doc", "summary"),
    [
        ("GL-P01b: goods customers sent back, newest first.", "goods customers sent back, newest first."),
        ("8.1f-2: margin per product per month.", "margin per product per month."),
        ("When could a new order for n be ready? (GL-P07 B5)", "When could a new order for n be ready?"),
        ("List the lots.", "List the lots."),
    ],
)
def test_internal_tracking_ids_are_not_published_in_a_summary(doc, summary):
    def view():
        pass

    view.__doc__ = doc
    assert docstring_parts(view)[0] == summary
