"""The Map view of a trace is a left-to-right lineage graph: source lots, one column per
production stage, finished lots (docs/trace-and-recall-redesign-plan.md, section 3)."""

import re
from uuid import UUID

import pytest
from playwright.sync_api import expect

from tests.dag_traversal_helpers import build_branching_dag
from tests.e2e.conftest import assert_clean_page, attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


@pytest.fixture()
def branching_chain(browser, app_url, fresh_user):
    """A logged-in page on an org holding R1 -> W1 -> F1 and R1 -> W2: one source lot that
    feeds two stages."""
    from app.core.db import db_session

    user = fresh_user()
    dag = build_branching_dag(db_session(), UUID(user["org_id"]))
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])
    try:
        yield page, dag
    finally:
        context.close()


def _trace_r1(page):
    page.goto("/core/sourcemap")
    page.locator(".sm-browse-card", has_text="R1").first.click()
    expect(page.locator(".sm-lineage__node").first).to_be_visible()


def _column(page, title):
    return page.locator(".sm-lineage__column").filter(has=page.locator(".sm-lineage__title", has_text=title))


def test_each_lot_appears_once_in_the_column_after_what_it_was_made_from(branching_chain):
    page, _dag = branching_chain
    _trace_r1(page)

    nodes = page.locator(".sm-lineage__node")
    expect(nodes).to_have_count(4)
    for name in ["R1", "W1", "W2", "F1"]:
        expect(nodes.filter(has=page.locator(".sm-lineage__name", has_text=name))).to_have_count(1)

    columns = page.locator(".sm-lineage__column")
    expect(columns).to_have_count(3)
    expect(columns.nth(0).locator(".sm-lineage__title")).to_contain_text("Source lot")
    expect(columns.nth(0).locator(".sm-lineage__name")).to_have_text(["R1"])
    expect(columns.nth(1).locator(".sm-lineage__name")).to_have_text(["W1", "W2"])
    expect(columns.nth(2).locator(".sm-lineage__name")).to_have_text(["F1"])
    expect(columns.nth(2).locator(".sm-lineage__title")).to_contain_text("W1_to_F1")

    traced = page.locator(".sm-lineage__node--traced")
    expect(traced).to_have_count(1)
    expect(traced).to_contain_text("R1")
    assert_clean_page(page)


def test_an_edge_joins_each_lot_to_what_it_became_and_sits_between_the_two_nodes(branching_chain):
    page, _dag = branching_chain
    _trace_r1(page)

    edges = page.locator(".sm-lineage__edge")
    expect(edges).to_have_count(3)  # R1->W1, R1->W2, W1->F1
    expect(edges.first).to_have_attribute("d", re.compile(r"^M[\d.]+,[\d.]+ C"))

    # Every edge starts at the right edge of one node and ends at the left edge of another.
    mismatched = page.evaluate(
        """() => {
            const canvas = document.querySelector('.sm-lineage__canvas').getBoundingClientRect();
            const boxes = [...document.querySelectorAll('.sm-lineage__node')].map(n => n.getBoundingClientRect());
            const near = (a, b) => Math.abs(a - b) < 1.5;
            return [...document.querySelectorAll('.sm-lineage__edge')].filter(path => {
                const n = path.getAttribute('d').match(/-?[\\d.]+/g).map(Number);
                const [x1, y1] = [n[0] + canvas.left, n[1] + canvas.top];
                const [x2, y2] = [n[6] + canvas.left, n[7] + canvas.top];
                const starts = boxes.some(b => near(b.right, x1) && y1 > b.top && y1 < b.bottom);
                const ends = boxes.some(b => near(b.left, x2) && y2 > b.top && y2 < b.bottom);
                return !(starts && ends && x2 > x1);
            }).length;
        }"""
    )
    assert mismatched == 0


def test_pointing_at_a_lot_dims_everything_not_upstream_or_downstream_of_it(branching_chain):
    page, _dag = branching_chain
    _trace_r1(page)

    def node(name):
        return page.locator(".sm-lineage__node").filter(has=page.locator(".sm-lineage__name", has_text=name))

    node("F1").hover()
    expect(page.locator(".sm-lineage")).to_have_class(re.compile(r"\bsm-lineage--focused\b"))
    for name in ["F1", "W1", "R1"]:
        expect(node(name)).to_have_class(re.compile(r"\bis-related\b"))
    expect(node("W2")).not_to_have_class(re.compile(r"\bis-related\b"))
    expect(page.locator(".sm-lineage__edge.is-related")).to_have_count(2)  # R1->W1 and W1->F1, not R1->W2

    page.mouse.move(2, 2)
    expect(page.locator(".sm-lineage")).not_to_have_class(re.compile(r"\bsm-lineage--focused\b"))
    expect(page.locator(".sm-lineage__node.is-related")).to_have_count(0)


def test_selecting_a_lot_opens_its_history(branching_chain):
    page, _dag = branching_chain
    _trace_r1(page)

    page.locator(".sm-lineage__node").filter(has=page.locator(".sm-lineage__name", has_text="W1")).click()
    expect(page.locator(".sm-story-panel--open")).to_be_visible()
    expect(page.locator("#sm-story-panel-title")).to_have_text("W1")
    assert_clean_page(page)


def test_a_phone_opens_the_trace_on_the_timeline(browser, app_url, fresh_user):
    from app.core.db import db_session

    user = fresh_user()
    build_branching_dag(db_session(), UUID(user["org_id"]))
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        login_through_ui(page, user["email"], user["password"])
        page.goto("/core/sourcemap")
        page.locator(".sm-browse-card", has_text="R1").first.click()
        expect(page.get_by_role("tab", name="Timeline")).to_have_attribute("aria-selected", "true")
        expect(page.locator(".sm-timeline-entry").first).to_be_visible()
        expect(page.locator(".sm-lineage")).to_have_count(0)

        page.get_by_role("tab", name="Map").click()
        expect(page.locator(".sm-lineage__node").first).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "page scrolls sideways"
    finally:
        context.close()
