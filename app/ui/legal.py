"""Pricing, terms and privacy: public pages linked from sign-up, the landing page and Settings
(GL-C01, GL-C02).

All three are **placeholders** until the founder confirms the prices and a lawyer reviews the
terms. Each page says so at the top. ``TERMS_VERSION`` is recorded with every sign-up, so we
know which text an account agreed to when the reviewed version replaces it.
"""

from __future__ import annotations

from flask import Blueprint, render_template

TERMS_VERSION = "draft-2026-10-26"
UPDATED = "26 October 2026"

# Founder, 2026-10-26: Compliance (NZ Alcohol) at NZD 250 + GST a month. The rest is placeholder.
PLANS = [
    {
        "name": "Compliance (NZ Alcohol)",
        "price": "NZD 250",
        "per": "a month + GST",
        "for": "Licensed New Zealand producers of beer, wine, spirits and RTDs.",
        "includes": [
            "Production records: workflows, batches and every step recorded",
            "Stock: raw materials, finished goods, opening stock and stocktakes",
            "Trace and recall from an ingredient to every customer, and back",
            "Xero sales matched to the batches they came from",
            "Customs excise entry drafts from recorded removals, and CCA movements",
            "NP3 and food-safety evidence, licensing register and premises",
            "Unlimited users at one site",
        ],
    },
]

# GL-P07: say what is and isn't in the offer rather than imply a full planner or multi-site system.
NOT_INCLUDED = [
    "Recording production at more than one site (sites can be listed and transfers recorded)",
    "Material planning and promise dates",
    "Purchasing and purchase orders",
    "Accounting: invoices and payments stay in Xero",
]

legal_bp = Blueprint("legal", __name__)


@legal_bp.route("/pricing")  # nosemgrep: route-missing-requires-auth -- public marketing page
def pricing():
    return render_template("legal/pricing.html", plans=PLANS, not_included=NOT_INCLUDED, updated=UPDATED)


@legal_bp.route("/terms")  # nosemgrep: route-missing-requires-auth -- public legal page
def terms():
    return render_template("legal/terms.html", updated=UPDATED, version=TERMS_VERSION)


@legal_bp.route("/privacy")  # nosemgrep: route-missing-requires-auth -- public legal page
def privacy():
    return render_template("legal/privacy.html", updated=UPDATED, version=TERMS_VERSION)
