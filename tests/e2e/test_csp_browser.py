"""GL-S03 in the browser: every page, on a full load and on a boosted arrival, breaks nothing under
the enforced CSP, and every inline <script> it runs passes the strict nonce policy (sent
report-only). What the strict policy still reports, inline handlers and Alpine's evaluated
attributes, is the rest of the migration (docs/csp-migration-plan.md) and is printed, not failed.
"""

import pytest

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
  window.__boostSettled = false;
  document.body.addEventListener('htmx:afterSettle', () => { window.__boostSettled = true; }, { once: true });
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
def test_a_page_runs_under_the_policy_and_its_inline_scripts_carry_the_nonce(logged_in_page, path):
    page = logged_in_page
    page.add_init_script(_LISTEN)

    page.goto(path)
    page.wait_for_load_state("networkidle")
    full = _violations(page)

    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")
    page.evaluate("window.__csp = []")
    page.evaluate(_BOOST, path)
    page.wait_for_function("window.__boostSettled === true", timeout=15_000)
    page.wait_for_load_state("networkidle")
    boosted = _violations(page)

    for how, seen in (("full load", full), ("boosted", boosted)):
        enforced = [v for v in seen if v["disposition"] == "enforce"]
        assert not enforced, f"{path} ({how}): the enforced policy blocked {enforced}"
        assert not _inline_script_blocks(seen), f"{path} ({how}): inline script without the nonce"
    left = {(v["directive"], v["sample"]) for v in full + boosted}
    if left:
        print(f"{path}: {len(left)} still to migrate: {sorted(left)[:5]}")
