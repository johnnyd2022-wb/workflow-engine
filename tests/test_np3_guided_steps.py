"""Guided next steps show a few prioritised, collapsed rows, not every outstanding item."""

from app.features.compliant.modules.nz_alcohol.np3_audit import build_guided_steps, prioritise_work_queue


def _item(kind, severity, control_id, category_key="section-0", **extra):
    return {
        "kind": kind,
        "severity": severity,
        "control_id": control_id,
        "category_key": category_key,
        "title": f"{kind}: {control_id}",
        "description": "d",
    } | extra


def test_queue_is_sorted_overdue_then_attention_then_due_soon_and_stable_within_a_severity():
    queue = [
        _item("due-soon-review", "due-soon", "a"),
        _item("open-remediation", "attention", "b"),
        _item("overdue-review", "overdue", "c"),
        _item("guidance-update", "attention", "d"),
    ]

    assert [i["control_id"] for i in prioritise_work_queue(queue)] == ["c", "b", "d", "a"]


def test_same_kind_items_collapse_into_one_row_that_opens_the_filtered_register():
    queue = [_item("open-remediation", "attention", f"c{n}", f"section-{n % 2}") for n in range(9)]

    (step,) = build_guided_steps(queue)

    assert step["title"] == "9 open records need follow-up"
    assert (step["count"], step["opens"], step["filter"]) == (9, "register", "remediation")
    assert step["category_key"] == "section-0"


def test_a_single_item_keeps_its_own_title_and_opens_its_check():
    (step,) = build_guided_steps([_item("overdue-review", "overdue", "delegation")])

    assert step["title"] == "overdue-review: delegation"
    assert (step["count"], step["opens"], step["control_id"]) == (1, "check", "delegation")


def test_several_items_on_one_control_open_that_check_rather_than_the_register():
    queue = [_item("open-remediation", "attention", "staff-competency") for _ in range(2)]

    (step,) = build_guided_steps(queue)

    assert step["title"] == "2 open records need follow-up"
    assert step["opens"] == "check"


def test_only_the_top_three_kinds_are_shown_most_urgent_first():
    queue = [
        _item("due-soon-review", "due-soon", "a"),
        _item("guidance-update", "attention", "b"),
        _item("open-remediation", "attention", "c"),
        _item("overdue-review", "overdue", "d"),
    ]

    assert [s["kind"] for s in build_guided_steps(queue)] == ["overdue-review", "guidance-update", "open-remediation"]
    assert build_guided_steps([]) == []
