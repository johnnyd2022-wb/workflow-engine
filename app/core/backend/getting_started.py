"""Getting started: one resumable path from sign-up to a traced sale (GL-P09).

Every step's state is read from what the org has actually done (a workflow, a go-live
date, a completed step, a Xero connection, a mapping, a matched sale), so the guide never
needs to be ticked and can't drift from the data. A step whose module the org doesn't have
(Compliance, Sales) is left out rather than shown as undone. A step that needs an earlier
one says which, and is "blocked" until then.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, render_template

from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.security.permissions import requires_auth
from app.observability import get_logger

logger = get_logger(__name__)

DONE, TODO, BLOCKED = "done", "todo", "blocked"

# key, group, title, why, where to do it, the button's words. Order is the suggested order.
STEPS = (
    (
        "business",
        "Your business",
        "Tell us what you make",
        "Gin, beer, wine or more: it decides which rules and records Compliance shows you.",
        "/compliant/nz-alcohol",
        "Choose your products",
    ),
    (
        "workflow",
        "Production",
        "Set up a product workflow",
        "The steps a batch goes through, from raw materials to bottles. Start from a template.",
        "/core/flows/create/template-catalog",
        "Pick a template",
    ),
    (
        "opening_stock",
        "Production",
        "Count the stock you hold today",
        "Count it once and tracing starts from today, with no history to rebuild.",
        "/core/go-live",
        "Start the count",
    ),
    (
        "first_batch",
        "Production",
        "Record your first batch",
        "Record a step as you make it: what went in, what came out, and when.",
        "/core/processes",
        "Start a batch",
    ),
    (
        "xero",
        "Sales",
        "Connect Xero",
        "Your invoices come in by themselves, so each sale can be traced to a batch.",
        "/crm/configuration",
        "Connect Xero",
    ),
    (
        "mappings",
        "Sales",
        "Match your Xero products to yours",
        "Tell us which invoice line is which product, once.",
        "/crm/configuration",
        "Match products",
    ),
    (
        "trace",
        "Check it works",
        "Follow a batch to its customers",
        "Open a batch in Trace and recall and see every customer who bought it.",
        "/core/sourcemap",
        "Open Trace and recall",
    ),
)

NEEDS = {
    "first_batch": ("workflow", "Set up a product workflow first."),
    "mappings": ("xero", "Connect Xero first."),
    "trace": ("mappings", "Match your Xero products first."),
}


def _modules(session, org_id: UUID) -> dict[str, bool]:
    from flask import current_app

    from app.features.compliant.service import nz_alcohol_active

    availability = current_app.extensions.get("product_availability", {})
    return {
        "compliance": bool(nz_alcohol_active(session, org_id)),
        "sales": bool(availability.get("crm")),
    }


def _facts(session, org_id: UUID, modules: dict[str, bool]) -> dict[str, tuple[bool, str | None]]:
    """(done, a short fact about it) for each step, from the org's own records."""
    org = session.get(Organisation, org_id)
    workflows = session.query(Process).filter(Process.org_id == org_id, Process.is_draft.is_(False)).count()
    recorded = (
        session.query(ExecutionStep.id)
        .join(Execution, Execution.id == ExecutionStep.execution_id)
        .filter(Execution.org_id == org_id, ExecutionStep.completed_at.isnot(None))
        .count()
    )
    facts: dict[str, tuple[bool, str | None]] = {
        "workflow": (workflows > 0, f"{workflows} workflow{'s' if workflows != 1 else ''}" if workflows else None),
        "opening_stock": (
            bool(org and org.go_live_date),
            f"Counted on {org.go_live_date:%-d %b %Y}" if org and org.go_live_date else None,
        ),
        "first_batch": (recorded > 0, f"{recorded} step{'s' if recorded != 1 else ''} recorded" if recorded else None),
    }
    if modules["compliance"]:
        from app.features.compliant.service import ComplianceService

        profile = ComplianceService(session).get_profile(org_id)
        types = ((profile.settings if profile else None) or {}).get("alcohol_product_types") or []
        facts["business"] = (bool(types), ", ".join(str(t).replace("_", " ") for t in types[:3]) or None)
    if modules["sales"]:
        from app.features.crm.models.product_mapping import ProductMapping
        from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
        from app.features.crm.services.sales_sources import XeroSalesSource

        mappings = session.query(ProductMapping).filter(ProductMapping.org_id == org_id).count()
        traced = session.query(SalesFifoAllocation.id).filter(SalesFifoAllocation.org_id == org_id).first()
        facts["xero"] = (XeroSalesSource().connected(session, org_id), None)
        facts["mappings"] = (
            mappings > 0,
            f"{mappings} product{'s' if mappings != 1 else ''} matched" if mappings else None,
        )
        facts["trace"] = (traced is not None, "A sale is traced to a batch" if traced else None)
    return facts


def getting_started(session, org_id: UUID) -> dict:
    modules = _modules(session, org_id)
    facts = _facts(session, org_id, modules)
    steps = []
    for key, group, title, why, href, action in STEPS:
        if key not in facts:
            continue  # the org doesn't have this module
        done, fact = facts[key]
        state = DONE if done else TODO
        blocked_by = needs = None
        if not done and key in NEEDS:
            need, reason = NEEDS[key]
            if need in facts and not facts[need][0]:
                state, blocked_by, needs = BLOCKED, reason, need
        steps.append(
            {
                "key": key,
                "group": group,
                "title": title,
                "why": why,
                "href": href,
                "action": action,
                "status": state,
                "fact": fact,
                "blocked_by": blocked_by,
                "needs": needs,
            }
        )
    done = sum(1 for s in steps if s["status"] == DONE)
    upcoming = next((s["key"] for s in steps if s["status"] == TODO), None)
    return {"steps": steps, "done": done, "total": len(steps), "next": upcoming, "complete": done == len(steps)}


getting_started_bp = Blueprint("getting_started", __name__)


@getting_started_bp.route("/core/getting-started", methods=["GET"])
@requires_auth
def getting_started_page():
    return render_template("getting_started/getting_started.html", active_page="core")


@getting_started_bp.route("/api/core/getting-started", methods=["GET"])
@requires_auth
def get_getting_started():
    return jsonify(getting_started(db_session, UUID(str(g.org_id)))), 200
