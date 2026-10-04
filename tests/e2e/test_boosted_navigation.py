"""A page reached by an in-app (htmx-boosted) click must equal the same page after a full load.

Boost swaps only `#page-content`, so anything a page keeps outside it (its CSS, its scripts, its
`DOMContentLoaded` init) is silently dropped -- the page comes up unstyled, stuck on "Loading…",
or half empty, and only a refresh fixes it. This walks every page in `app/ui/page_registry.py`:
load it directly, then reach it by a boosted click from the dashboard, and require that the
boosted render

* has about as many elements as the full load (within 10%, plus a few for live regions),
* has every stylesheet and every element id the full load has (the page's key selectors),
* has no "Loading…" left once the network is idle, and
* raised no console error the full load did not.

CI skips e2e in `relevant_tests`, so run this locally:
`env -u ENVIRONMENT uv run pytest tests/e2e/test_boosted_navigation.py`. `BOOST_BROKEN` is the
shrinking list of pages not yet fixed; each is a *strict* xfail, so fixing one without removing it
from the list fails the run.
"""

import re

import pytest

from app.ui.page_registry import PAGES
from tests.e2e.conftest import PageProbe

pytestmark = pytest.mark.e2e

# Pages whose boosted render is still wrong (docs/ux-overhaul-plan.md, step 1). Remove a path here
# in the same change that fixes it.
BOOST_BROKEN: set[str] = set()

_SNAPSHOT_JS = """() => {
  const root = document.querySelector('#page-content');
  // Count what the user can get: not asset tags (a boosted swap carries them in a hidden
  // [data-page-assets] holder and htmx removes executed scripts) and not the test's own link.
  const elements = [...root.querySelectorAll('*')].filter(
    (el) => !el.closest('[data-page-assets]') && el.id !== '__boost_probe' && !/^(SCRIPT|LINK|STYLE|META)$/.test(el.tagName)
  );
  const leaf = (el) => el.children.length === 0;
  return {
    path: location.pathname,
    elements: elements.length,
    sheets: [...document.querySelectorAll('link[rel~="stylesheet"]')].map((el) => new URL(el.href).pathname),
    ids: elements.map((el) => el.id).filter((id) => id && !/[0-9a-f]{8}-|\\d{5,}/.test(id)),
    loading: elements.filter((el) => leaf(el) && /^\\s*Loading(…|\\.\\.\\.)?\\s*$/i.test(el.textContent)).length,
  };
}"""

# What the audit did by hand: put a real link in the swapped region, let htmx process it, click it.
_BOOSTED_CLICK_JS = """(path) => {
  window.__boostSettled = false;
  document.body.addEventListener('htmx:afterSettle', () => { window.__boostSettled = true; }, { once: true });
  const host = document.querySelector('#page-content');
  const link = document.createElement('a');
  link.href = path;
  link.id = '__boost_probe';
  link.textContent = path;
  host.prepend(link);
  window.htmx.process(link);
  link.click();
}"""


@pytest.fixture(scope="module", autouse=True)
def _compliant_subscription(e2e_user):
    from app.core.db import db_session
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository

    FeatureSubscriptionRepository(db_session()).grant(e2e_user["org_id"], "compliant")
    db_session().commit()


def _errors(page) -> list[str]:
    probe: PageProbe = page.probe
    return [*probe.console_errors]


def _settle(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)


def _params():
    for entry in PAGES:
        marks = []
        if entry.path in BOOST_BROKEN:
            marks.append(pytest.mark.xfail(reason="boosted render differs from a full load", strict=True))
        yield pytest.param(entry.path, id=entry.path, marks=marks)


@pytest.mark.parametrize("path", list(_params()))
def test_boosted_click_renders_the_same_page_as_a_full_load(logged_in_page, path):
    page = logged_in_page

    page.goto(path)
    _settle(page)
    full = page.evaluate(_SNAPSHOT_JS)
    full_errors = _errors(page)

    page.goto("/core/dashboard")
    _settle(page)
    before = len(_errors(page))
    page.evaluate(_BOOSTED_CLICK_JS, path)
    page.wait_for_function("window.__boostSettled === true", timeout=15_000)
    _settle(page)
    boosted = page.evaluate(_SNAPSHOT_JS)
    new_errors = _errors(page)[before:]

    assert boosted["path"] == full["path"], "boosted click landed on a different page"
    tolerance = max(3, round(full["elements"] * 0.10))
    assert abs(boosted["elements"] - full["elements"]) <= tolerance, (
        f"{boosted['elements']} elements boosted vs {full['elements']} on a full load"
    )
    no_sheets = sorted(set(full["sheets"]) - set(boosted["sheets"]))
    assert not no_sheets, f"stylesheets a full load has but the boosted page lacks: {no_sheets}"
    missing = sorted(set(full["ids"]) - set(boosted["ids"]))
    assert not missing, f"elements missing after a boosted click: {missing[:15]}"
    assert boosted["loading"] <= full["loading"], f"{boosted['loading']} 'Loading…' left after a boosted click"
    unexpected = [e for e in new_errors if e not in full_errors]
    assert not unexpected, "console errors only on the boosted render:\n  - " + "\n  - ".join(unexpected)


def test_registry_paths_are_distinct_from_assets():
    assert all(re.fullmatch(r"/[a-z0-9/_-]*", page.path) for page in PAGES)


def test_back_and_forward_restore_working_pages(logged_in_page):
    """htmx would restore a cached DOM snapshot on back/forward, which comes back inert (no
    handlers, no data). base_spa.html sets `historyCacheSize: 0` + `refreshOnHistoryMiss`, so the
    browser's own back/forward reloads the page from the server."""
    page = logged_in_page
    page.goto("/core/dashboard")
    _settle(page)
    page.evaluate(_BOOSTED_CLICK_JS, "/core/stocktake")
    page.wait_for_function("window.__boostSettled === true", timeout=15_000)
    _settle(page)
    assert page.locator("[data-stocktake-root]").count() == 1
    assert page.locator("[data-stocktake-root]").get_attribute("data-st-bound") == "1"

    page.go_back()
    _settle(page)
    assert page.url.endswith("/core/dashboard")
    assert page.locator("[data-dashboard-root]").count() == 1
    assert page.locator("#page-content").get_by_text("Loading…", exact=True).count() == 0

    page.go_forward()
    _settle(page)
    assert page.url.endswith("/core/stocktake")
    assert page.locator("[data-stocktake-root]").get_attribute("data-st-bound") == "1"
    assert page.locator("#page-content").get_by_text("Loading…", exact=True).count() == 0


def test_back_arrow_goes_up_one_level_on_every_kind_of_page(logged_in_page):
    """The arrow in the top bar follows the breadcrumb (shared/breadcrumbs.html): hidden on a tab's own
    page, one level up elsewhere, the same whether the page came from a full load or a boosted click."""
    page = logged_in_page
    arrow = page.locator("#spa-banner-back")

    page.goto("/core/planner")
    _settle(page)
    assert "spa-banner-back--hidden" in (arrow.get_attribute("class") or "")

    page.evaluate(_BOOSTED_CLICK_JS, "/core/planner/board")
    page.wait_for_function("window.__boostSettled === true", timeout=15_000)
    _settle(page)
    assert "spa-banner-back--hidden" not in (arrow.get_attribute("class") or "")
    assert arrow.get_attribute("href") == "/core/planner"
    arrow.click()
    page.wait_for_url("**/core/planner")
    _settle(page)
    assert "spa-banner-back--hidden" in (arrow.get_attribute("class") or "")

    page.goto("/core/go-live")
    _settle(page)
    assert arrow.get_attribute("href") == "/core/dashboard"
    assert page.locator(".breadcrumbs li").all_inner_texts() == ["Dashboard", "Go live"]
