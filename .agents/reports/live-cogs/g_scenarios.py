from ui_shots import DESKTOP, LAPTOP, PHONE, settle, shot, theme

PAGE = "/core/costing/costs"


def _open(page, viewport=None):
    if viewport:
        page.set_viewport_size(viewport)
    page.goto(PAGE)
    page.locator("[data-stock]:not([hidden])").wait_for()
    settle(page, 400)


def _snapshots(page, n=2):
    btn = page.get_by_role("button", name="Take a snapshot")
    have = page.locator("[data-stock-list] > li").count()
    for _ in range(max(0, n - have)):
        btn.click()
        settle(page, 600)


def _scroll(page):
    page.locator("[data-stock]").scroll_into_view_if_needed()
    settle(page, 200)


def desktop_now(page, out):
    _open(page, DESKTOP)
    _scroll(page)
    shot(page, out, "desktop-stock-empty")
    _snapshots(page)
    _scroll(page)
    shot(page, out, "desktop-stock")


def desktop_bridge(page, out):
    _open(page, DESKTOP)
    _snapshots(page)
    page.locator("[data-stock-list] > li").first.get_by_role("button").first.click()
    settle(page, 500)
    page.get_by_role("button", name="Compare with Xero").first.click()
    settle(page, 800)
    _scroll(page)
    shot(page, out, "desktop-bridge", full=True)


def laptop(page, out):
    _open(page, LAPTOP)
    _snapshots(page)
    page.locator("[data-stock-list] > li").first.get_by_role("button").first.click()
    settle(page, 500)
    _scroll(page)
    shot(page, out, "laptop-stock")


def phone(page, out):
    _open(page, PHONE)
    _snapshots(page)
    page.locator("[data-stock-list] > li").first.get_by_role("button").first.click()
    settle(page, 500)
    page.get_by_role("button", name="Compare with Xero").first.click()
    settle(page, 800)
    _scroll(page)
    shot(page, out, "phone-stock", full=True)


def phone_dark(page, out):
    _open(page, PHONE)
    page.evaluate("localStorage.setItem('spa-theme','dark')")
    page.reload()
    page.locator("[data-stock]:not([hidden])").wait_for()
    settle(page, 400)
    _scroll(page)
    shot(page, out, "phone-dark-stock", full=True)


def desktop_dark(page, out):
    _open(page, DESKTOP)
    page.evaluate("localStorage.setItem('spa-theme','dark')")
    page.reload()
    page.locator("[data-stock]:not([hidden])").wait_for()
    settle(page, 400)
    page.locator("[data-stock-list] > li").first.get_by_role("button").first.click()
    settle(page, 500)
    _scroll(page)
    shot(page, out, "desktop-dark-stock")
