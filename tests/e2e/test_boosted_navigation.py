"""A page reached by an in-app (htmx-boosted) click must equal the same page after a full load.

Boost swaps only `#page-content`, so anything a page keeps outside it (its CSS, its scripts, its
`DOMContentLoaded` init) is silently dropped -- the page comes up unstyled, stuck on "Loading…",
or half empty, and only a refresh fixes it. This walks every page in `app/ui/page_registry.py`
plus the detail pages in `UNREGISTERED`: load it directly, then reach it by a boosted click from
the dashboard, reach it a second time, and restore it with Back, and require that each render

* has about as many elements as the full load (within 10%, plus a few for live regions),
* has at least 80% of the full load's text,
* has every stylesheet and every element id the full load has (the page's key selectors),
* left nothing on <body>'s Alpine data,
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
    // "Loading…", "Loading tasks…", "Loading inventory...": anything still waiting on its script.
    loading: elements.filter((el) => leaf(el) && el.getClientRects().length && /^\\s*Loading[\\w ]*(…|\\.\\.\\.)?\\s*$/i.test(el.textContent)).length,
    text: root.innerText.replace(/\\s+/g, ' ').length,
    // Alpine writes a component's undeclared properties onto the outermost x-data, <body>'s,
    // which outlives a boosted swap; the next visit then reads the last page's state.
    bodyData: Object.keys((document.body._x_dataStack || [{}])[0]),
    // The yellow arrow: hidden, or where it goes up to.
    back: (() => { const el = document.getElementById('spa-banner-back');
      return !el ? 'missing' : el.classList.contains('spa-banner-back--hidden') ? 'hidden' : el.getAttribute('href'); })(),
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
    from app.features.compliant.service import ComplianceService

    FeatureSubscriptionRepository(db_session()).grant(e2e_user["org_id"], "compliant")
    # Sales -> Excise is only for orgs running the NZ Alcohol module.
    ComplianceService(db_session()).upsert_profile(
        e2e_user["org_id"], {"enabled": True, "industry_module": "nz_alcohol"}
    )
    db_session().commit()


def _errors(page) -> list[str]:
    probe: PageProbe = page.probe
    return [*probe.console_errors]


def _settle(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)


# Pages the registry does not list (detail pages and flows) that render without seeded data.
UNREGISTERED = (
    "/compliant/nz-alcohol/customs/records/product-mapping",
    "/compliant/nz-alcohol/np3-audit/check/recall-policy",
    "/core/flows/create",
    "/core/inventory/add/manual",
    "/core/inventory/dispose",
)


def _params():
    for path in [entry.path for entry in PAGES] + list(UNREGISTERED):
        marks = []
        if path in BOOST_BROKEN:
            marks.append(pytest.mark.xfail(reason="boosted render differs from a full load", strict=True))
        yield pytest.param(path, id=path, marks=marks)


def _boost(page, path) -> None:
    page.evaluate(_BOOSTED_CLICK_JS, path)
    page.wait_for_function("window.__boostSettled === true", timeout=15_000)
    _settle(page)


def _same_page(full, other, how):
    assert other["path"] == full["path"], f"{how}: landed on {other['path']}"
    tolerance = max(3, round(full["elements"] * 0.10))
    assert abs(other["elements"] - full["elements"]) <= tolerance, (
        f"{how}: {other['elements']} elements vs {full['elements']} on a full load"
    )
    assert other["text"] >= full["text"] * 0.8, f"{how}: {other['text']} characters of text vs {full['text']}"
    no_sheets = sorted(set(full["sheets"]) - set(other["sheets"]))
    assert not no_sheets, f"{how}: stylesheets a full load has but this lacks: {no_sheets}"
    missing = sorted(set(full["ids"]) - set(other["ids"]))
    assert not missing, f"{how}: elements missing: {missing[:15]}"
    assert other["loading"] <= full["loading"], f"{how}: {other['loading']} 'Loading…' left"
    assert not other["bodyData"], f"{how}: properties left on <body>'s Alpine data: {other['bodyData']}"
    assert other["back"] == full["back"], (
        f"{how}: the back arrow goes to {other['back']}, on a full load {full['back']}"
    )


@pytest.mark.parametrize("path", list(_params()))
def test_boosted_click_renders_the_same_page_as_a_full_load(logged_in_page, path):
    """Reached once, reached again (its scripts run a second time in the same window), and
    restored by Back: each must match a full load."""
    page = logged_in_page

    page.goto(path)
    _settle(page)
    full = page.evaluate(_SNAPSHOT_JS)
    full_errors = _errors(page)

    page.goto("/core/dashboard")
    _settle(page)
    before = len(_errors(page))
    _boost(page, path)
    _same_page(full, page.evaluate(_SNAPSHOT_JS), "first boosted visit")

    # A second visit catches what a first cannot: a run-once flag on window, a top-level
    # const declared again, a component reading state the last visit left behind.
    _boost(page, "/core/dashboard")
    _boost(page, path)
    _same_page(full, page.evaluate(_SNAPSHOT_JS), "second boosted visit")

    _boost(page, "/core/settings")
    page.go_back()
    _settle(page)
    _same_page(full, page.evaluate(_SNAPSHOT_JS), "back after a boosted visit")

    unexpected = sorted({e for e in _errors(page)[before:] if e not in full_errors})
    assert not unexpected, "console errors only after boosted navigation:\n  - " + "\n  - ".join(unexpected)


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
    assert page.locator(".breadcrumbs li").all_inner_texts() == ["Home", "Go live"]


_LAYOUT_JS = """() => {
  const crumbs = document.querySelector('#page-content .breadcrumbs');
  return {
    mains: document.querySelectorAll('#page-content').length,
    nested: document.querySelectorAll('#page-content #page-content, main.page-content main.page-content').length,
    crumbTop: crumbs ? Math.round(crumbs.getBoundingClientRect().top) : null,
  };
}"""


@pytest.mark.parametrize("path", ["/core/go-live", "/core/stocktake"])
def test_a_boosted_page_sits_where_a_full_load_puts_it(logged_in_page, path):
    """GL-U04: hx-select="#page-content" put a second <main id="page-content"> inside the first,
    with its padding, so a page without section tabs sat 32px lower after an in-app link."""
    page = logged_in_page
    page.goto(path)
    _settle(page)
    full = page.evaluate(_LAYOUT_JS)
    page.goto("/core/dashboard")
    _settle(page)
    _boost(page, path)
    boosted = page.evaluate(_LAYOUT_JS)
    assert boosted["mains"] == 1 and boosted["nested"] == 0, boosted
    assert boosted["crumbTop"] == full["crumbTop"], (boosted, full)
