"""The Batches page's redesign (docs/batches-redesign-plan.md): every workflow's batches at once,
the time each has waited at its step, filters kept in the URL, and the selected lanes layout. Two tests pin bugs the old board had: searching by workflow name matched nothing (the
search read a field the executions list never sends), and in the dark theme batch titles were
pale text on white cards."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui

pytestmark = pytest.mark.e2e

PAGE = "/core/executions/live"


@pytest.fixture
def floor(fresh_user, db):
    """Two workflows and three batches: one recorded three days ago (waiting), one recorded
    two hours ago, and one in the second workflow with nothing recorded yet."""
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.process import ProcessCategory
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository

    user = fresh_user(UserRole.ADMIN)
    org_id = UUID(user["org_id"])
    procs, execs = ProcessRepository(db), ExecutionRepository(db)
    now = datetime.now(UTC)

    def workflow(name, steps):
        process = procs.create_process(org_id, name, category=ProcessCategory.MANUFACTURING, is_draft=False)
        for number, step in enumerate(steps, start=1):
            procs.add_step(
                process_id=process.id,
                org_id=org_id,
                step_number=number,
                position=number * 1000,
                name=step,
                inputs=[],
                outputs=[],
            )
        db.commit()
        return process

    def batch(process, code=None, recorded_hours_ago=None, started_hours_ago=1):
        execution = execs.create_execution(org_id, process.id)
        if recorded_hours_ago is not None:
            first = (
                db.query(ExecutionStep)
                .filter(ExecutionStep.execution_id == execution.id)
                .order_by(ExecutionStep.step_number)
                .first()
            )
            execs.complete_step(
                first.id,
                org_id,
                actual_inputs=[],
                actual_outputs=[{"name": "Spirit", "quantity": 40, "unit": "L", "batch_id": code}],
                execution_data={"completed_by": "Aroha Ngata"},
                completed_at_override=now - timedelta(hours=recorded_hours_ago),
            )
        db.query(Execution).filter(Execution.id == execution.id).update(
            {"started_at": now - timedelta(hours=started_hours_ago)}
        )
        db.commit()
        return str(execution.id)

    gin = workflow("Batch Test Gin", ["Macerate", "Distil", "Bottle"])
    cello = workflow("Batch Test Limoncello", ["Infuse", "Blend"])
    return {
        "user": user,
        "gin": str(gin.id),
        "cello": str(cello.id),
        "waiting": batch(gin, "GIN-0001", recorded_hours_ago=72, started_hours_ago=90),
        "moving": batch(gin, "GIN-0002", recorded_hours_ago=2, started_hours_ago=5),
        "fresh": batch(cello, started_hours_ago=1),
    }


def _open(browser, app_url, floor, width=1440, query=""):
    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": width, "height": 900})
    page = context.new_page()
    login_through_ui(page, floor["user"]["email"], floor["user"]["password"])
    page.goto(PAGE + query)
    # A batch card, not the new root, so the two bug tests below also run against the old board.
    page.locator("#core2-active-pipeline-grid [data-core2-execution-id]").first.wait_for()
    return context, page


def _card(page, execution_id):
    return page.locator(f'#core2-active-pipeline-grid [data-core2-execution-id="{execution_id}"]')


def test_every_workflow_shows_at_once_with_time_at_step(browser, app_url, floor):
    context, page = _open(browser, app_url, floor)
    try:
        expect(page.get_by_role("heading", name="Under way", exact=True)).to_be_visible()
        # No workflow to pick first: both workflows' batches are on the page.
        for key in ("waiting", "moving", "fresh"):
            expect(_card(page, floor[key])).to_be_visible()
        expect(page.locator("#core2-active-process-select")).to_have_value("")
        # Waiting is words plus colour, from when the last step was recorded, not when the batch started.
        expect(_card(page, floor["waiting"])).to_contain_text("Waiting 3 days")
        expect(_card(page, floor["moving"])).to_contain_text("2 hours at this step")
        expect(_card(page, floor["moving"])).not_to_contain_text("Waiting")
        expect(page.locator("[data-batches-waiting-count]")).to_have_text("1")
        expect(page.locator("[data-core2-inflight-count]")).to_have_text("3")
    finally:
        context.close()


def test_search_finds_batches_by_workflow_name(browser, app_url, floor):
    """Failed before: the search read execution.process_name, which the list never returns."""
    context, page = _open(browser, app_url, floor)
    try:
        page.locator("#core2-active-search").fill("limoncello")
        expect(_card(page, floor["fresh"])).to_be_visible()
        expect(_card(page, floor["waiting"])).to_have_count(0)
        expect(_card(page, floor["moving"])).to_have_count(0)
    finally:
        context.close()


def test_filters_live_in_the_url_and_clear_together(browser, app_url, floor):
    context, page = _open(browser, app_url, floor)
    try:
        page.locator("#core2-active-process-select").select_option(floor["gin"])
        page.get_by_role("button", name="Waiting", exact=True).click()
        query = parse_qs(urlsplit(page.url).query)
        assert query.get("workflow") == [floor["gin"]] and query.get("show") == ["waiting"], page.url
        expect(_card(page, floor["waiting"])).to_be_visible()
        expect(_card(page, floor["moving"])).to_have_count(0)

        page.locator("#core2-active-search").fill("no such batch")
        expect(page.locator("[data-batches-message]")).to_contain_text("No batches match these filters.")
        page.get_by_role("button", name="Clear filters").click()
        for key in ("waiting", "moving", "fresh"):
            expect(_card(page, floor[key])).to_be_visible()
        cleared = parse_qs(urlsplit(page.url).query)
        assert "workflow" not in cleared and "show" not in cleared and "q" not in cleared, page.url

        # A shared link opens on the same view.
        page.goto(f"{PAGE}?workflow={floor['cello']}")
        page.locator('[data-batches-root][data-state="ready"]').wait_for()
        expect(_card(page, floor["fresh"])).to_be_visible()
        expect(_card(page, floor["waiting"])).to_have_count(0)
    finally:
        context.close()


def test_detail_sheet_records_the_next_step(browser, app_url, floor):
    context, page = _open(browser, app_url, floor)
    try:
        _card(page, floor["waiting"]).click()
        sheet = page.locator("#core2-active-detail-overlay")
        expect(sheet).to_be_visible()
        expect(sheet.locator("#core2-active-detail-id")).to_have_text("GIN-0001")
        expect(sheet).to_contain_text("Batch Test Gin · Step 2 of 3 · Distil")
        record = sheet.get_by_role("link", name="Record Distil")
        href = record.get_attribute("href")
        assert href.startswith("/core/flows/batches/start?"), href
        params = parse_qs(urlsplit(href).query)
        assert params["id"] == [floor["gin"]] and params["execution_id"] == [floor["waiting"]], href
        page.keyboard.press("Escape")
        expect(sheet).to_be_hidden()
    finally:
        context.close()


def _contrast(page, selector):
    """WCAG contrast between an element's text colour and the first opaque background behind it."""
    return page.evaluate(
        """sel => {
          const el = document.querySelector(sel);
          const rgb = c => (c.match(/[\\d.]+/g) || []).map(Number);
          const lum = ([r, g, b]) => {
            const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          let bg = null;
          for (let n = el; n && !bg; n = n.parentElement) {
            const c = rgb(getComputedStyle(n).backgroundColor);
            const img = getComputedStyle(n).backgroundImage;
            // A gradient paints over the colour: read the colour its last stop ends on.
            const stops = img && img !== 'none' ? img.match(/rgba?\\([^)]*\\)/g) : null;
            if (stops) bg = rgb(stops[stops.length - 1]).slice(0, 3);
            else if (c.length >= 3 && (c.length < 4 || c[3] > 0.9)) bg = c.slice(0, 3);
          }
          const fg = lum(rgb(getComputedStyle(el).color)), b = lum(bg || [255, 255, 255]);
          return (Math.max(fg, b) + 0.05) / (Math.min(fg, b) + 0.05);
        }""",
        selector,
    )


def test_batch_titles_stay_readable_in_the_dark_theme(browser, app_url, floor):
    """Failed before: cards kept a white gradient background while the title turned pale."""
    context, page = _open(browser, app_url, floor)
    try:
        page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
        page.wait_for_timeout(200)
        ratio = _contrast(
            page, f'#core2-active-pipeline-grid [data-core2-execution-id="{floor["waiting"]}"] .core2-active-card-id'
        )
        assert ratio >= 4.5, f"batch title contrast {ratio:.2f} in the dark theme"
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 1024, 1440, 1920])
def test_lanes_hold_together_at_every_width_even_with_an_old_preview_link(browser, app_url, floor, width):
    context, page = _open(browser, app_url, floor, width=width, query="?style=3")
    try:
        expect(page.get_by_role("group", name="Batches design concepts")).to_have_count(0)
        expect(page.locator(".batches-lane")).to_have_count(2)
        expect(page.locator('link[href*="/batches.css"]')).to_have_count(1)
        assert page.locator(".batches-sr").first.evaluate("el => getComputedStyle(el).position") == "absolute"
        for key in ("waiting", "moving", "fresh"):
            expect(_card(page, floor[key])).to_be_visible()
        expect(page.locator("#core2-active-search")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "page scrolls sideways"
        # Nothing drawn over anything else: no two batch openers overlap.
        boxes = [
            b
            for b in (c.bounding_box() for c in page.locator("#core2-active-pipeline-grid .core2-active-card").all())
            if b
        ]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                apart = (
                    a["x"] + a["width"] <= b["x"] + 1
                    or b["x"] + b["width"] <= a["x"] + 1
                    or a["y"] + a["height"] <= b["y"] + 1
                    or b["y"] + b["height"] <= a["y"] + 1
                )
                assert apart, f"batch cards overlap at {width}px"
    finally:
        context.close()
