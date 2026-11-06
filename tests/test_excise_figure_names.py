"""GL-P05: the two excise figures are named the same way on both screens.

Sales → Excise is a *sales estimate* from invoices; Compliance → Customs is the *filing draft*
built from removals, which is what gets lodged. Each screen names its own figure, links to
the other by that name, and says why they can differ.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALES = (ROOT / "app/features/crm/frontend/templates/crm/excise.html").read_text()
CUSTOMS = (ROOT / "app/features/compliant/frontend/static/excise.js").read_text()


def test_sales_screen_calls_its_figure_the_sales_estimate_and_points_at_the_filing_draft():
    assert ">Sales estimate</span>" in SALES
    assert "filing draft in Compliance → Customs</a>" in SALES
    assert "tastings, samples and moves under bond" in SALES


def test_customs_screen_tags_the_filing_draft_and_links_to_the_sales_estimate():
    assert "'Filing draft'" in CUSTOMS and "'Lodged return'" in CUSTOMS
    assert "Compare with the sales estimate for " in CUSTOMS
    assert "Sales behind " not in CUSTOMS


def test_customs_says_why_the_figures_differ_in_visible_text_not_a_tooltip():
    # Breaker review of !627: a title= tooltip can't be read on a phone or by keyboard.
    assert "'aria-describedby': 'excise-estimate-why'" in CUSTOMS
    assert "id: 'excise-estimate-why', className: 'excise-hint'" in CUSTOMS
    assert "title: 'An estimate from invoices" not in CUSTOMS
