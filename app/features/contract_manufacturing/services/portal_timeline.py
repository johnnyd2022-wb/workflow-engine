"""A customer timeline built exclusively from facts already shared in the portal."""

from datetime import UTC, datetime

from app.features.contract_manufacturing.models.portal import PortalPublication

MAX_UPDATES = 50
MAX_EVENTS = 100


def order_timeline(db, principal, order_id, visible):
    """Call only after shared_order has established a current customer publication.

    Never read staff audit events or operational records. Approval events come from
    the current document allowlist, so withdrawing a proof removes it here too.
    Historic updates expose only their revision/time, never withdrawn snapshot text.
    """
    updates = (
        db.query(PortalPublication)
        .filter_by(org_id=principal.org_id, customer_id=principal.customer_id, order_id=order_id, revoked_at=None)
        .order_by(PortalPublication.revision.desc())
        .limit(MAX_UPDATES + 1)
        .all()
    )
    events = []

    def event(key, when, kind, label):
        events.append({"id": key, "occurred_at": when, "kind": kind, "label": label})

    for update in updates[:MAX_UPDATES]:
        event(
            f"update:{update.revision}",
            update.created_at.isoformat(),
            "shared_update",
            f"Producer shared order update {update.revision}",
        )
    for approval in visible["waiting_on_you"]["approvals"]:
        event(
            "proof-request:" + approval["id"],
            approval["requested_at"],
            "proof_requested",
            "Producer requested approval: " + approval["document_title"],
        )
        if approval["responded_at"]:
            label = (
                "Customer approved proof: " if approval["decision"] == "approved" else "Customer requested changes: "
            )
            event(
                "proof-response:" + approval["id"],
                approval["responded_at"],
                "proof_response",
                label + approval["document_title"],
            )
    for message in visible["messages"]:
        sender = "Customer" if message["sender"] == "customer" else "Producer"
        event("message:" + message["id"], message["created_at"], "message", sender + " sent a message")
    reorder = visible.get("reorder_request")
    if reorder:
        event(
            "reorder:" + reorder["id"],
            reorder["requested_at"],
            "reorder_requested",
            "Customer requested a repeat order",
        )
    events.sort(key=lambda item: (datetime.fromisoformat(item["occurred_at"]).astimezone(UTC), item["id"]))
    return {
        "events": events[-MAX_EVENTS:],
        "truncated": len(events) > MAX_EVENTS or len(updates) > MAX_UPDATES or len(visible["messages"]) >= 100,
    }
