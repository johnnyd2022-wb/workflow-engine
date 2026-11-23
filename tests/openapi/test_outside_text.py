"""Design review S6: text written outside the organisation is listed, by origin, on every assistant operation.

`.agents/reports/design-review/2026-11-17-mcp-costing-planning-analytics.md` §S6: customer names, invoice
references and descriptions and supplier names come from Xero's contacts and bills, not from the organisation's
own staff, and the only defence was one sentence in each tool description. An assistant that also has email or
web tools can be steered by such text.

Each assistant operation now declares ``x-bize.outside_text`` (a list of ``{path, origin}``). Declaring is only
worth something if the list is complete, so the sweep below does not trust it: it plants a distinct marker in
every column Xero text lands in, calls every operation a token can reach, and fails if a marker turns up at a
path the operation does not declare. Portal-authored text is the other half of the finding ("leave it out by
default"): no operation may declare it, and nothing outside ``contract_manufacturing`` may read the tables it
is written to, so an operation cannot start returning it without this file going red.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.openapi.overlay import OverlayError, load_overlay
from app.features.mcp_oauth.services import rate_limit
from tests.openapi.test_token_reads_write_nothing import (  # noqa: F401  (guarded_world is a fixture)
    EXPECTED_NON_2XX,
    TOKEN_GETS,
    _client,
    _recording_xero,
    _url,
    guarded_world,
)
from tests.test_excise import world as excise_world  # noqa: F401  (a fixture: an org with spirits and a rate)

REPO = Path(__file__).resolve().parents[2]
MARKER = re.compile(r"S6CANARY:([a-z_]+):")


def plant(kind: str) -> str:
    return f"S6CANARY:{kind}:"


def markers_in(value, path: str = "", found: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """``{field path: {marker kinds}}`` for every string in ``value`` that carries a planted marker."""
    found = {} if found is None else found
    if isinstance(value, str):
        for kind in MARKER.findall(value):
            found.setdefault(path, set()).add(kind)
    elif isinstance(value, list):
        for item in value:
            markers_in(item, f"{path}[]", found)
    elif isinstance(value, dict):
        for key, item in value.items():
            markers_in(item, f"{path}.{key}" if path else key, found)
    return found


@pytest.fixture(scope="module")
def canary_world(guarded_world):  # noqa: F811
    """The guarded showcase org with a marker in every column Xero text lands in."""
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.costing.actions import get_created_cost_flow
    from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine
    from app.features.crm.models.product_mapping import ProductMapping
    from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
    from app.features.crm.models.xero_account import XeroAccount
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem

    world = guarded_world
    db, org_id = world.db, world.org.id
    contact = db.get(XeroContact, world.ids["contact"])
    contact.name = plant("contact_name")
    contact.first_name, contact.last_name = plant("contact_first_name"), plant("contact_last_name")
    contact.email_address, contact.phone_number = plant("contact_email"), plant("contact_phone")
    contact.addresses = [{"type": "STREET", "line1": plant("contact_address")}]
    invoice = db.get(XeroInvoice, world.ids["invoice"])
    invoice.invoice_number, invoice.reference = plant("invoice_number"), plant("invoice_reference")
    invoice.currency_code, invoice.sub_total, invoice.total_tax = "NZD", 87, 13
    line_id = f"line-{uuid4().hex[:8]}"
    db.add(
        XeroInvoiceLineItem(
            org_id=org_id,
            invoice_id=invoice.id,
            xero_line_item_id=line_id,
            description=plant("line_description"),
            item_code=plant("item_code"),
            quantity=2,
            unit_amount=50,
            line_amount=87,
            tax_amount=13,
            account_code="200",
        )
    )
    db.add(
        SalesFifoAllocation(
            org_id=org_id,
            xero_invoice_id=invoice.xero_invoice_id,
            xero_line_key=line_id,
            inventory_item_id=world.ids["gin_lot"],
            product_name=plant("allocation_product"),
            quantity=2,
            unit="bottles",
        )
    )
    # A lot's supplier is copied from a bill's payee when stock is added from that bill, so every lot carries it.
    for item in db.query(InventoryItem).filter(InventoryItem.org_id == org_id).all():
        item.supplier = plant("supplier")
    juniper = db.get(InventoryItem, world.ids["juniper"])
    juniper.expiry_date = date.today() - timedelta(days=30)  # an expired raw material, used by the gin batch

    # The sale maps to a product, so the margins report lists it as a line (its reference is the invoice number).
    db.add(
        ProductMapping(
            org_id=org_id,
            biz_e_product_name="Gin",
            xero_description_pattern=plant("line_description"),
            match_type="exact",
            is_active=True,
        )
    )

    # A bill recorded into the juniper lot: the lot-cost panel names its payee.
    account = XeroAccount(org_id=org_id, xero_account_id=f"acct-{uuid4().hex[:8]}")
    db.add(account)
    bill = PurchaseDocument(
        org_id=org_id,
        source="xero_bill",
        external_id=f"bill-{uuid4().hex[:8]}",
        kind="spend",
        payee_name=plant("payee"),
        reference=plant("bill_reference"),
        document_date=date.today(),
        status="active",
    )
    db.add(bill)
    db.flush()
    purchase_line = PurchaseLine(
        org_id=org_id,
        document_id=bill.id,
        account_id=account.id,
        line_key=f"line-{uuid4().hex[:8]}",
        position=1,
        fingerprint=uuid4().hex,
        treatment="stock",
        description=plant("bill_line_description"),
    )
    db.add(purchase_line)
    db.flush()
    db.add(
        PurchaseAllocation(
            org_id=org_id,
            purchase_line_id=purchase_line.id,
            inventory_item_id=juniper.id,
            cost_flow_id=get_created_cost_flow(db, org_id, juniper.id).id,
            amount=10,
            quantity=1,
            status="active",
        )
    )
    db.commit()
    return world


@pytest.fixture(scope="module")
def sweep(canary_world):
    """Every token-reachable GET once, as the assistant: ``{operation id: (status, markers found)}``."""
    import app.app as app_module

    patch = pytest.MonkeyPatch()
    patch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    _recording_xero(patch)  # no operation may reach Xero; a call that is swallowed is still refused
    client = _client(app_module.app)
    results = {}
    try:
        for oid, path, op in TOKEN_GETS:
            url, query = _url(canary_world, oid, path, op)
            response = client.get(url, query_string=query, headers=canary_world.token_headers)
            body = response.get_json(silent=True)
            results[oid] = (response.status_code, markers_in(body) if body is not None else {})
    finally:
        patch.undo()
    failed = {
        oid: status
        for oid, (status, _found) in results.items()
        if not 200 <= status < 300 and oid not in EXPECTED_NON_2XX
    }
    assert not failed, (
        f"these operations did not answer 2xx on the seeded org, so the sweep proved nothing for them: {failed}. "
        "A 401 means the assistant's OAuth client or grant was removed under it (another run purging the shared "
        "test database); rerun."
    )
    return results


def declared(op: dict) -> dict[str, str]:
    return {entry["path"]: entry["origin"] for entry in op["x-bize"].get("outside_text", [])}


def test_the_sweep_actually_reaches_the_xero_text(sweep):
    """A seed that quietly produced nothing must not pass for proof."""
    surfaced = {oid: set(found) for oid, (_status, found) in sweep.items() if found}
    assert {
        "crm_crm_api_get_org_invoices",
        "core_list_inventory",
        "core_trace_inventory_backward",
        "core_trace_inventory_to_sale_graph",
    } <= set(surfaced), sorted(surfaced)
    assert {"invoices[].contact_name", "invoices[].reference", "invoices[].line_items[].description"} <= surfaced[
        "crm_crm_api_get_org_invoices"
    ]
    assert "inventory_items[].supplier" in surfaced["core_list_inventory"]
    assert {"all_items[].customer_name", "all_items[].customer_email"} <= surfaced["core_trace_inventory_to_sale_graph"]


@pytest.mark.parametrize("oid,path,op", TOKEN_GETS, ids=[oid for oid, _p, _o in TOKEN_GETS])
def test_xero_text_only_appears_at_paths_the_operation_declares(sweep, oid, path, op):
    _status, found = sweep[oid]
    undeclared = {field: sorted(kinds) for field, kinds in found.items() if field not in declared(op)}
    assert not undeclared, (
        f"{oid} returns text from Xero at {sorted(undeclared)} but does not list it under x-bize.outside_text "
        f"in app/api/openapi/overlay/*.yaml: {undeclared}"
    )


def test_every_assistant_operation_declares_its_outside_text(full_doc):
    """The 28 operations each answer the question, with ``[]`` as a stated "none"; a new one cannot skip it."""
    from app.api.openapi.coverage import mcp_problems

    operations = [
        op
        for item in full_doc["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and op.get("x-bize", {}).get("mcp") is True
    ]
    assert len(operations) >= 28
    assert all(isinstance(op["x-bize"].get("outside_text"), list) for op in operations)
    assert not [p for problems in mcp_problems(full_doc).values() for p in problems if "outside_text" in p]


def test_an_operation_that_does_not_say_what_is_outside_text_is_a_coverage_problem(full_doc):
    import copy

    from app.api.openapi.coverage import mcp_problems

    doc = copy.deepcopy(full_doc)
    op = next(
        op for item in doc["paths"].values() for op in item.values() if op.get("operationId") == "core_list_inventory"
    )
    del op["x-bize"]["outside_text"]
    assert any("outside_text must list" in p for p in mcp_problems(doc)["core_list_inventory"])


def _operation(doc, operation_id):
    return next(op for item in doc["paths"].values() for op in item.values() if op.get("operationId") == operation_id)


@pytest.mark.parametrize(
    "operation_id,path",
    [
        ("crm_crm_api_monthly_sales", "months[].no_such_field"),  # a closed object: a typo is caught
        ("crm_crm_api_monthly_sales", "months[].invoice_count"),  # a number is not text
        ("core_list_inventory", "total_count"),
        ("core_list_inventory", "nope"),
    ],
)
def test_a_declared_path_that_is_not_a_text_field_of_the_response_is_a_coverage_problem(full_doc, operation_id, path):
    """A typo, or a number, listed as outside text would look like coverage and protect nothing."""
    import copy

    from app.api.openapi.coverage import mcp_problems

    doc = copy.deepcopy(full_doc)
    _operation(doc, operation_id)["x-bize"]["outside_text"] = [{"path": path, "origin": "xero"}]
    assert any(f"outside_text path {path!r}" in p for p in mcp_problems(doc)[operation_id])


def test_a_path_inside_an_object_the_schema_leaves_open_is_accepted_and_left_to_the_sweep(full_doc):
    """``additionalProperties: true`` objects cannot be checked against the schema: the canary sweep is the check."""
    import copy

    from app.api.openapi.coverage import mcp_problems

    doc = copy.deepcopy(full_doc)
    _operation(doc, "costing_get_lot_cost")["x-bize"]["outside_text"] = [{"path": "provenance.name", "origin": "xero"}]
    assert not [p for p in mcp_problems(doc).get("costing_get_lot_cost", []) if "outside_text" in p]


# Declared from reading the code, but not reached by the token sweep. The excise period needs its own org (an
# excise profile, a rate, a lodged month), so ``test_excise_period_text_from_xero_is_declared`` below seeds it at
# the service level and checks the three removal paths there. The two CCA-transfer paths need a stock transfer
# as well and are reached by neither: each is a promise a reviewer can check at the cited line. A path leaves
# this list the day the sweep reaches it (the test below fails if it already does).
UNSEEDED = {
    "compliant_compliant_api_get_excise_period": {
        "draft.lines[].removals[].customer": "checked at the service level by the excise test below (excise.py:663)",
        "draft.lines[].removals[].reference": "checked at the service level by the excise test below (excise.py:662)",
        "draft.adjustments[].reference": "checked at the service level by the excise test below (excise.py:1100)",
        "draft.cca_transfers[].customer": "not exercised: app/features/compliant/modules/nz_alcohol/cca_transfers.py:305",
        "draft.cca_transfers[].reference": "not exercised: cca_transfers.py:304 (Xero invoice number)",
    },
}


def test_every_declared_path_was_seen_by_the_sweep_or_is_named_unseeded(sweep):
    """A declaration nothing ever exercised could be dead: either the sweep saw it, or it says why it did not."""
    unseen, stale = {}, []
    for oid, _path, op in TOKEN_GETS:
        seen = set(sweep[oid][1])
        listed = UNSEEDED.get(oid, {})
        missing = [p for p in declared(op) if p not in seen and p not in listed]
        if missing:
            unseen[oid] = missing
        stale += [f"{oid}: {p}" for p in listed if p not in declared(op) or p in seen]
    assert not unseen, f"declared but never seen holding a planted marker (seed it, or add it to UNSEEDED): {unseen}"
    assert not stale, f"UNSEEDED entries that are no longer declared or are now reached (remove them): {stale}"


def test_excise_period_text_from_xero_is_declared(excise_world):  # noqa: F811
    """The period's removals carry the customer's name and the invoice number; a late sale reappears as an adjustment."""
    from datetime import date

    from app.features.compliant.modules.nz_alcohol import excise
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice

    w = excise_world
    db, org = w["db"], w["org"]
    contact = XeroContact(org_id=org.id, xero_contact_id=f"c-{uuid4().hex[:8]}", name=plant("excise_customer"))
    db.add(contact)
    db.commit()

    def sell(number, day, quantity="2"):
        invoice = w["sell"](vat, quantity, day, plant(number))
        db.query(XeroInvoice).filter(XeroInvoice.id == invoice.id).update({"contact_id": contact.id})
        db.commit()

    vat = w["lot"]("VAT44", 50)
    sell("excise_invoice", date(2026, 9, 10), "12")
    september = excise.draft(db, org.id, date(2026, 9, 1), "monthly", today=date(2026, 10, 5))
    excise.lodge(db, org.id, date(2026, 9, 1), "monthly", date(2026, 10, 16), None, None, today=date(2026, 10, 16))
    sell("excise_late_invoice", date(2026, 9, 28))  # entered after September was lodged
    october = excise.draft(db, org.id, date(2026, 10, 1), "monthly", today=date(2026, 11, 5))

    op = next(op for oid, _p, op in TOKEN_GETS if oid == "compliant_compliant_api_get_excise_period")
    seen = {}
    for period in (september, october):
        for path, kinds in markers_in({"draft": period}).items():
            seen.setdefault(path, set()).update(kinds)
    assert {
        "draft.lines[].removals[].customer",
        "draft.lines[].removals[].reference",
        "draft.adjustments[].reference",
    } <= set(seen), f"the seed no longer reaches the excise text: {seen}"
    undeclared = {path: sorted(kinds) for path, kinds in seen.items() if path not in declared(op)}
    assert not undeclared, f"the excise period returns text from Xero at {undeclared} without declaring it"


def test_no_operation_may_declare_portal_text(tmp_path):
    """Portal-authored text is left out: it is not an origin an operation can declare."""
    (tmp_path / "x.yaml").write_text(
        "operations:\n  op_a:\n    summary: A\n    x-bize:\n      outside_text:\n"
        "        - {path: body, origin: portal}\n"
    )
    with pytest.raises(OverlayError, match="origin 'portal' must be one of"):
        load_overlay(tmp_path)


@pytest.mark.parametrize(
    "value,message",
    [
        ("invoices", "must be a list"),
        ([{"path": "a"}], "entries are"),
        ([{"path": "a b", "origin": "xero"}], "not a field path"),
        ([{"path": "a[0]", "origin": "xero"}], "not a field path"),
        ([{"path": "a", "origin": "xero"}, {"path": "a", "origin": "xero"}], "twice"),
    ],
)
def test_a_malformed_outside_text_is_refused(tmp_path, value, message):
    import json

    (tmp_path / "x.yaml").write_text(
        "operations:\n  op_a:\n    summary: A\n    x-bize:\n      outside_text: " + json.dumps(value) + "\n"
    )
    with pytest.raises(OverlayError, match=message):
        load_overlay(tmp_path)


# Portal-authored text lives in these tables (a portal user's message, a proof approval's response note, a
# reorder enquiry's note). Nothing outside the contract-manufacturing feature may read them: an assistant
# operation that did would hand a customer's free text to the model, which is what S6 says to leave out.
# The names come from the models, so renaming one cannot leave this test passing for the wrong reason.
ALLOWED_OUTSIDE = (
    "app/features/contract_manufacturing/",
    "app/core/db/migrations/",
)


def _portal_authored_names() -> tuple[str, ...]:
    from app.features.contract_manufacturing.models.portal import PortalApproval, PortalMessage, PortalReorderRequest

    models = (PortalMessage, PortalApproval, PortalReorderRequest)
    return (*(m.__name__ for m in models), *(m.__tablename__ for m in models))


def test_nothing_outside_contract_manufacturing_reads_portal_authored_text():
    names = _portal_authored_names()
    offenders = []
    for root in ("app", "bize_mcp"):
        for file in (REPO / root).rglob("*.py"):
            relative = file.relative_to(REPO).as_posix()
            if relative.startswith(ALLOWED_OUTSIDE):
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
            if any(re.search(rf"\b{name}\b", text) for name in names):
                offenders.append(relative)
    assert not offenders, (
        f"{offenders} read portal-authored text. Customer-typed portal text must stay out of assistant results "
        "(design review S6): keep the read inside contract_manufacturing, or decide on purpose how it is marked."
    )
