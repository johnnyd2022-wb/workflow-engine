"""GL-S03 in the browser: every page runs under the strict policy on full and boosted loads."""

import pytest
from playwright.sync_api import expect

from app.ui.page_registry import PAGES
from tests.e2e.test_boosted_navigation import _compliant_subscription  # noqa: F401 -- autouse: Compliance pages

pytestmark = pytest.mark.e2e

# Collects every violation the browser raises, enforced or report-only, for the whole tab.
_LISTEN = """
window.__csp = window.__csp || [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push({disposition: e.disposition, directive: e.effectiveDirective,
                     blocked: e.blockedURI, sample: e.sample, page: location.pathname});
});
"""

_BOOST = """(path) => {
  document.body.dataset.boostSettled = 'false';
  document.body.addEventListener('htmx:afterSettle', () => { document.body.dataset.boostSettled = 'true'; }, { once: true });
  const link = document.createElement('a');
  link.href = path;
  document.querySelector('#page-content').prepend(link);
  window.htmx.process(link);
  link.click();
}"""


def _violations(page) -> list[dict]:
    return page.evaluate("window.__csp || []")


def _inline_script_blocks(violations):
    """An inline <script> the nonce policy would block: it has no nonce, or the wrong one."""
    return [v for v in violations if v["directive"] == "script-src-elem" and v["blocked"] == "inline"]


@pytest.mark.parametrize("path", [entry.path for entry in PAGES], ids=lambda p: p)
def test_a_page_runs_under_the_policy_and_its_inline_scripts_carry_the_nonce(strict_csp_page, path):
    page = strict_csp_page
    page.add_init_script(_LISTEN)

    page.goto(path)
    page.wait_for_load_state("networkidle")
    full = _violations(page)

    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")
    page.evaluate("window.__csp = []")
    page.evaluate(_BOOST, path)
    expect(page.locator("body")).to_have_attribute("data-boost-settled", "true", timeout=15_000)
    page.wait_for_load_state("networkidle")
    boosted = _violations(page)

    for how, seen in (("full load", full), ("boosted", boosted)):
        enforced = [v for v in seen if v["disposition"] == "enforce"]
        assert not enforced, f"{path} ({how}): the enforced policy blocked {enforced}"
        report_only = [v for v in seen if v["disposition"] == "report"]
        assert not report_only, f"{path} ({how}): the report-only policy blocked {report_only}"
        assert not _inline_script_blocks(seen), f"{path} ({how}): inline script without the nonce"
