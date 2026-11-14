from ui_shots import DESKTOP, settle

def dbg(page, out):
    page.set_viewport_size(DESKTOP)
    page.on("pageerror", lambda e: print("PAGEERROR", e.stack if hasattr(e, "stack") else e))
    page.goto("/core/costing/costs")
    settle(page, 2000)
    print("HTML", page.locator("[data-stock]").count(), page.locator("[data-stock]").first.get_attribute("hidden"))
    print("ME", page.evaluate("fetch('/api/core/costing/me').then(r=>r.json())"))
