"""The ``select`` / ``$from`` path language: a JMESPath subset with no functions and no code."""

from __future__ import annotations

import pytest

from bize_mcp.select import SelectError, compile_expression, select

DATA = {
    "items": [
        {"id": "a", "name": "Gin", "qty": 0, "cost": None, "tags": ["x", "y"]},
        {"id": "b", "name": "Vodka", "qty": 5, "cost": "1.20", "tags": []},
        {"name": "No id"},
    ],
    "meta": {"count": 3, "next": None},
    "odd key": 7,
}


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("meta", {"count": 3, "next": None}),
        ("meta.count", 3),
        ("items[0].id", "a"),
        ("items[-1].name", "No id"),
        ("items[1].tags[0]", None),
        ("items[0].tags[1]", "y"),
        ("items[*].name", ["Gin", "Vodka", "No id"]),
        ("items[*].id", ["a", "b"]),  # an element without the field is dropped, like JMESPath
        ("items[*].qty", [0, 5]),  # zero is a value, not a missing field
        ("items[*].{id: id, n: name}", [{"id": "a", "n": "Gin"}, {"id": "b", "n": "Vodka"}, {"id": None, "n": "No id"}]),
        ("meta.{c: count, nxt: next}", {"c": 3, "nxt": None}),
        ('"odd key"', 7),
        ("items[9]", None),
        ("nothing.here", None),
        ("items[*].cost", ["1.20"]),
    ],
)
def test_the_supported_subset(expression, expected):
    assert select(expression, DATA) == expected


def test_a_missing_field_is_null_never_zero_or_empty():
    assert select("items[2].cost", DATA) is None
    assert select("items[2].qty", DATA) is None


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "max(items[*].qty)",
        "length(items)",
        "items[?qty > `1`]",
        "items[0:2]",
        "items | [0]",
        "items.*",
        "@",
        "$.items",
        "items[*",
        "items[x]",
        "{a: }",
        "{a b}",
        "a" * 400,
        "{a: {a: {a: {a: {a: {a: {a: {a: {a: {a: x}}}}}}}}}}",
    ],
)
def test_anything_outside_the_subset_is_refused(expression):
    with pytest.raises(SelectError):
        select(expression, DATA)


def test_hashes_can_be_forbidden_for_reference_paths():
    with pytest.raises(SelectError):
        compile_expression("a.{b: c}", allow_hash=False)
    assert compile_expression("a.b[0]", allow_hash=False)
