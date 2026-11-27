"""GLASS PROTOTYPE: screenshot scenarios for every signed-in page, grouped as on the wb board.

    UI_SHOTS_HOME=~/.cache/workflow-engine-ui-shots/glass env -u ENVIRONMENT uv run python \
        scripts/ui_shots.py shoot OUT --scenarios scripts/glass_scenarios.py g1 g3 2>&1 | grep '^ui-shots:'

Each group shoots every route at desktop light, desktop dark and phone (phone fails on
sideways scroll). Files are named <group>-<slug>-<view>.png.
"""

import re

from ui_shots import PHONE, settle, shot

DESKTOP = {"width": 1440, "height": 900}

GROUPS = {
    "g11": ["/core/inventory/live", "/compliant/nz-alcohol/np3-audit", "/compliant/nz-alcohol/wine", "/compliant/nz-alcohol/evidence", "/crm/tastings",
            "@customer", "@case",
            "/core/no-such-page",
            "@contract-order"],
    "g0": ["/core", "/core/dashboard"],
    "g1": [
        "/core",
        "/core?tab=batches",
        "/core/executions/live",
        "/core/tasks",
        "/core/record",
        "@batch-start",
        "@execution-step",
    ],
    "g2": [
        "/core/processes",
        "/core/flows",
        "@workflow",
        "/core/flows/create/start",
        "/core/flows/create/template-catalog",
    ],
    "g3": [
        "/core/inventory/view",
        "/core/inventory/add",
        "/core/inventory/add/manual",
        "/core/inventory/add/csv",
        "/core/inventory/add/barcode",
        "/core/inventory/dispose",
        "/core/stocktake",
        "/core/site-transfers",
        "/core/suppliers",
    ],
    "g4": ["/core/planner", "/core/planner/board", "/core/tasks/configuration", "/core/cases", "/core/cases/new"],
    "g5": [
        "/compliant",
        "/compliant/nz-alcohol",
        "/compliant/nz-alcohol/customs",
        "/compliant/nz-alcohol/customs/stock",
        "/compliant/nz-alcohol/customs/records",
        "/compliant/nz-alcohol/customs/settings",
        "/compliant/nz-alcohol/customs/transfers",
        "/compliant/nz-alcohol/food-safety",
        "/compliant/nz-alcohol/food-safety/checks",
        "/compliant/nz-alcohol/licensing",
        "/compliant/nz-alcohol/premises",
        "/compliant/nz-alcohol/food-registrations",
        "/compliant/nz-alcohol/configuration",
        "/compliant/tools",
    ],
    "g6": [
        "/crm",
        "/crm/customers",
        "/crm/tasks",
        "/crm/analytics",
        "/crm/configuration",
        "/crm/matching",
        "/crm/excise",
    ],
    "g7": [
        "/core/settings",
        "/core/people",
        "/core/sites",
        "/core/integrations",
        "/core/ai-assistants",
        "/core/getting-started",
        "/core/go-live",
        "/core/notifications",
        "/core/sourcemap",
    ],
    "g8": ["/core/contracts", "/core/contracts/materials", "@contract-order", "@contract-sharing"],
}


def _slug(path):
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "root"


def theme(page, mode):
    """Remember the theme the way the app does (localStorage), so it survives the next load."""
    page.evaluate(
        "m => { try { m === 'dark' ? localStorage.setItem('spa-theme','dark') : localStorage.removeItem('spa-theme'); } catch (e) {} }",
        mode,
    )


def _resolve(page, path):
    """'@batch-start' / '@execution-step': a real batch from the seeded org, read off the pages that link to it."""
    if not path.startswith("@"):
        return path
    src, sel = {
        "@batch-start": ("/core", "a.gpo-rec"),
        "@workflow": ("/core", "a.gpo-rec"),
        "@execution-step": ("/core/record", "a.rs-batch"),
        "@contract-order": ("/core/contracts", "a[href^='/core/contracts/']:not([href*='materials'])"),
        "@customer": ("/crm/customers", "a[href^='/crm/customers/']:not([href$='/new'])"),
        "@case": ("/core/cases", "a[href^='/core/cases/']:not([href$='/new'])"),
        "@contract-sharing": ("/core/contracts", "a[href^='/core/contracts/']:not([href*='materials'])"),
    }[path]
    page.goto(src)
    page.wait_for_load_state("networkidle")
    link = page.locator(sel).first
    link.wait_for(timeout=15000)
    href = link.get_attribute("href")
    if path == "@workflow":  # the batch's own workflow, read off its Record link (?id=<process>)
        from urllib.parse import parse_qs, urlparse

        return "/core/flows?id=" + parse_qs(urlparse(href).query)["id"][0]
    return href.split("?")[0] + "/portal-sharing" if path == "@contract-sharing" else href


def _visit(page, path):
    page.goto(_resolve(page, path))
    page.wait_for_load_state("networkidle")
    settle(page, 700)


def _group(name):
    def run(page, out):
        for path in GROUPS[name]:
            s = f"{name}-{_slug(path)}"
            page.set_viewport_size(DESKTOP)
            theme(page, "light")
            _visit(page, path)
            shot(page, out, f"{s}-desktop")
            shot(page, out, f"{s}-full", full=True)
            theme(page, "dark")
            _visit(page, path)
            shot(page, out, f"{s}-dark")
            theme(page, "light")
            page.set_viewport_size(PHONE)
            _visit(page, path)
            shot(page, out, f"{s}-phone")
        page.set_viewport_size(DESKTOP)

    run.__name__ = name
    return run


g0 = _group("g0")
g1 = _group("g1")
g2 = _group("g2")
g3 = _group("g3")
g4 = _group("g4")
g5 = _group("g5")
g6 = _group("g6")
g7 = _group("g7")
g8 = _group("g8")
g11 = _group("g11")


def tray(page, out):
    """The shared Action items tray, open, on desktop and phone."""
    for vp, tag in ((DESKTOP, "desktop"), (PHONE, "phone")):
        page.set_viewport_size(vp)
        _visit(page, "/core/inventory/view")
        page.locator("#g-act-btn").click()
        settle(page, 400)
        shot(page, out, f"tray-{tag}")
        page.keyboard.press("Escape")
    page.set_viewport_size(DESKTOP)


def boosted(page, out):
    """Boosted navigation across workspaces keeps the top bar and the tray working."""
    page.set_viewport_size(DESKTOP)
    _visit(page, "/core")
    for name in ("Compliance", "Sales", "Production"):
        link = page.locator(".g-ws a", has_text=name)
        if link.count():
            link.first.click()
            page.wait_for_load_state("networkidle")
            settle(page, 400)
    page.locator("#g-act-btn").click()
    settle(page, 300)
    shot(page, out, "boosted-tray")
    page.keyboard.press("Escape")


def _modal_shots(page, out, tag):
    """Open each shared dialog, sheet and toast in turn and shoot it."""
    _visit(page, "/core/inventory/view")
    line = page.evaluate(
        """async () => {
            const d = await window.CoreAPI.getInventory(null, null, {compact: true});
            const items = Array.isArray(d) ? d : (Object.values(d).find(Array.isArray) || []);
            const it = items.find(i => Number(i.quantity) > 0) || items[0];
            return it ? {id: it.id, name: it.name, quantity: it.quantity, unit: it.unit,
                         site_id: it.site_id, location_id: it.location_id, quality_hold: null} : null;
        }"""
    )
    steps = [
        ("move", "line => window.BizeMove && window.BizeMove.open(line, {})"),
        ("hold", "line => window.BizeHold && window.BizeHold.hold(line, {})"),
        ("recall", "line => window.BizeRecall && window.BizeRecall.start(line, {})"),
        ("help", "() => window.BizeHelp && window.BizeHelp.open()"),
    ]
    for name, js in steps:
        _visit(page, "/core/inventory/view")
        try:
            page.evaluate(js, line)
        except Exception as exc:  # noqa: BLE001 - a missing dialog is reported, not fatal
            print(f"modal {name}: {exc}")
        settle(page, 600)
        shot(page, out, f"modals-{name}-{tag}")
        page.keyboard.press("Escape")
    _visit(page, "/core/inventory/view")
    page.evaluate(
        "() => window.showNotification && window.showNotification('success', 'Saved', 'The stock line is updated.')"
    )
    settle(page, 400)
    shot(page, out, f"modals-toasts-{tag}")
    _visit(page, "/core/inventory/view")
    card = page.locator("#core2-inv-items-grid [data-group-index], #core2-inv-items-grid > *").first
    if card.count():
        card.click()
        settle(page, 600)
        shot(page, out, f"modals-item-sheet-{tag}")
        page.keyboard.press("Escape")
    _visit(page, "/core/flows")
    shot(page, out, f"modals-fixed-bar-{tag}")


def modals(page, out):
    """GLASS G10: shared dialogs, sheets, toasts and the fixed action bar on desktop, dark and phone."""
    for vp, mode, tag in ((DESKTOP, "light", "desktop"), (DESKTOP, "dark", "dark"), (PHONE, "light", "phone")):
        page.set_viewport_size(vp)
        theme(page, mode)
        _modal_shots(page, out, tag)
    theme(page, "light")
    page.set_viewport_size(DESKTOP)


G9_PAGES = [
    ("landing", "/", None),
    ("login", "/", "loginModal"),
    ("signup", "/", "signupModal"),
    ("pricing", "/pricing", None),
    ("terms", "/terms", None),
    ("invite", "/invite/not-a-real-token", None),
    ("error", "/core/no-such-page-glass", None),
    ("google", "/auth/google/callback", None),
    ("portal-login", "/portal/login", None),
    ("portal-invite", "/portal/invite", None),
]


def g9(page, out):
    """GLASS G9: pages outside the shell, signed out (a fresh context), desktop, dark and phone."""
    base = re.match(r"https?://[^/]+", page.url or "").group(0) if page.url.startswith("http") else None
    if not base:
        _visit(page, "/core")
        base = re.match(r"https?://[^/]+", page.url).group(0)
    browser = page.context.browser
    for vp, scheme, tag in ((DESKTOP, "light", "desktop"), (DESKTOP, "dark", "dark"), (PHONE, "light", "phone")):
        ctx = browser.new_context(base_url=base, ignore_https_errors=True, viewport=vp, color_scheme=scheme)
        anon = ctx.new_page()
        for name, path, modal in G9_PAGES:
            anon.goto(path)
            anon.wait_for_load_state("networkidle")
            if modal:
                anon.evaluate("m => window.openModal && window.openModal(m)", modal)
            settle(anon, 500)
            shot(anon, out, f"g9-{name}-{tag}")
            if name == "landing" and tag == "desktop":
                shot(anon, out, "g9-landing-full", full=True)
        ctx.close()

def menus(page, out):
    """GLASS-G11: the menus and popovers, opened, light, dark and phone."""
    cases = [
        ("avatar", "/core/inventory/view", ".g-av"),
        ("inv-drawer", "/core/inventory/view", "#inv-view-tbody tr"),
        ("inv-more", "/core/inventory/view", "[data-inv-more-toggle]"),
        ("notif-kebab", "/core/notifications", "#page-content button[aria-haspopup], #page-content .nt-more"),
        ("flows-manage", "@workflow", "#flows2-manage-btn, .flows2-manage-btn, [aria-controls*=manage]"),
        ("supplier-add", "/core/suppliers", "#page-content .workspace-button--primary"),
        ("crm-new-task", "/crm/tasks", "#page-content .workspace-button--primary, #page-content .crm-btn--primary"),
    ]
    for vp, mode, tag in ((DESKTOP, "light", "desktop"), (DESKTOP, "dark", "dark"), (PHONE, "light", "phone")):
        page.set_viewport_size(vp)
        theme(page, mode)
        for name, path, sel in cases:
            _visit(page, path)
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                try:
                    loc.first.click(timeout=3000)
                except Exception:
                    pass
                settle(page, 500)
            shot(page, out, f"menu-{name}-{tag}")
            page.keyboard.press("Escape")
    theme(page, "light")
    page.set_viewport_size(DESKTOP)
