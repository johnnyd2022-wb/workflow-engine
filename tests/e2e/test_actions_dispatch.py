"""GL-S03 step 2: app/ui/shared/actions.js stands in for inline on*="" handlers. These drive it on
a real page, under the enforced policy that now forbids handler attributes."""

import pytest

pytestmark = pytest.mark.e2e

SETUP = """() => {
  window.__calls = [];
  window.toggleStep = (...a) => window.__calls.push(['toggleStep', a.map((v) => (v instanceof Element ? 'EL:' + v.id : v))]);
  window.notAllowed = () => window.__calls.push(['notAllowed']);
  const box = document.createElement('div');
  box.id = 'actions-fixture';
  box.innerHTML = `
    <div id="parent">
      <button id="args" data-action="toggleStep" data-action-args='["a", 2, "$el"]'>args</button>
      <button id="blocked" data-action="notAllowed">blocked</button>
      <button id="stop" data-action-stop data-action="toggleStep" data-action-args='["stopped"]'>stop</button>
      <button id="fallback" data-action="handleAccountInfoLogoutMissing" data-action-fallback-href="#fell-back">fallback</button>
    </div>
    <div id="modal" style="display:flex">modal <button id="dismiss" data-dismiss="modal">close</button></div>
    <form id="form" data-submit-action="none" action="/nowhere"><button id="submit" type="submit">go</button></form>`;
  document.querySelector('#page-content').prepend(box);
  document.getElementById('parent').addEventListener('click', () => window.__calls.push(['parent']));
}"""


def test_the_dispatcher_runs_allowed_actions_and_nothing_else(logged_in_page):
    page = logged_in_page
    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")
    page.evaluate(SETUP)

    page.click("#args")
    assert page.evaluate("window.__calls") == [["toggleStep", ["a", 2, "EL:args"]], ["parent"]]

    page.evaluate("window.__calls = []")
    page.click("#blocked")
    assert page.evaluate("window.__calls") == [["parent"]], "a name off the allowlist must not run"

    page.evaluate("window.__calls = []")
    page.click("#stop")
    assert page.evaluate("window.__calls") == [["toggleStep", ["stopped"]]], "stop keeps the click from its parent"

    page.click("#dismiss")
    assert page.evaluate("getComputedStyle(document.getElementById('modal')).display") == "none"

    page.click("#submit")
    page.wait_for_timeout(300)
    assert page.url.endswith("/core/dashboard"), "data-submit-action='none' never submits natively"


def test_an_inline_handler_is_blocked_by_the_enforced_policy(logged_in_page):
    page = logged_in_page
    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")
    ran = page.evaluate("""() => new Promise((resolve) => {
      window.__inline = false;
      const b = document.createElement('button');
      b.setAttribute('onclick', 'window.__inline = true');
      document.body.appendChild(b);
      b.click();
      setTimeout(() => resolve(window.__inline), 50);
    })""")
    assert ran is False
