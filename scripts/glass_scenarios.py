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
    "g2": ["/core/processes", "/core/flows", "/core/flows?id=e6fa9c72-d1fc-4152-a1a5-ebd571bae9bd", "/core/flows/create/start", "/core/flows/create/template-catalog"],
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
    "g8": ["/core/contracts", "/core/contracts/materials"],
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
    src, sel = ("/core", "a.gpo-rec") if path == "@batch-start" else ("/core/record", "a.rs-batch")
    page.goto(src)
    page.wait_for_load_state("networkidle")
    link = page.locator(sel).first
    link.wait_for(timeout=15000)
    return link.get_attribute("href")


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
