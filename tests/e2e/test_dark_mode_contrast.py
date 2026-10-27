"""GL-U04: dark mode keeps text readable. The house tokens (--ui-text and friends) resolve to the
dark values inside the page, and no visible text on these pages falls under 3:1 against what is
behind it (the near-invisible Record step headings, the white-on-white buttons)."""

import pytest

pytestmark = pytest.mark.e2e

PAGES = ["/core/dashboard", "/core/inventory/add/csv", "/core/cases/new", "/core/flows/create/template-catalog"]

LOW_CONTRAST = """() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = (el) => { for (let n = el; n; n = n.parentElement) { const st = getComputedStyle(n); const c = parse(st.backgroundColor); if (c && c.a > 0.5) return c; if (st.backgroundImage.includes('gradient') && !st.backgroundImage.includes('to right')) { const g = parse(st.backgroundImage); if (g) return g; } } return { r: 0, g: 0, b: 0 }; };
  const low = [];
  document.querySelectorAll('#page-content h1, #page-content h2, #page-content h3, #page-content label, #page-content p, #page-content a, #page-content button, #page-content span').forEach((el) => {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === 'hidden' || Number(st.opacity) < 0.5) return;
    if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim().length > 1)) return;
    const fg = parse(st.color); if (!fg) return;
    const a = lum(fg), b = lum(bgOf(el)); const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    if (ratio < 3) low.push(el.tagName + ' "' + el.textContent.trim().slice(0, 30) + '" ' + ratio.toFixed(2));
  });
  return low;
}"""


@pytest.mark.parametrize("path", PAGES)
def test_dark_mode_text_is_readable(logged_in_page, path):
    page = logged_in_page
    page.goto(path)
    page.wait_for_load_state("networkidle")
    page.evaluate("document.documentElement.setAttribute('data-spa-theme', 'dark')")
    page.wait_for_timeout(600)
    tokens = page.evaluate(
        "() => { const s = getComputedStyle(document.getElementById('page-content'));"
        " return [s.getPropertyValue('--ui-text').trim(), s.getPropertyValue('--text-primary').trim()]; }"
    )
    assert tokens[0] == tokens[1], f"--ui-text should follow the dark --text-primary, got {tokens}"
    assert page.evaluate(LOW_CONTRAST) == []
