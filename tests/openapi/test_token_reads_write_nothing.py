"""Design review S2: a read-only assistant token never writes, and never spends the org's Xero allowance.

`.agents/reports/design-review/2026-11-17-mcp-costing-planning-analytics.md` §S2: ``GET /costing/stock-value``
took and committed the month-end snapshot (an irreversible close) for an org with no Xero, and
``GET /costing/bridge`` called Xero's P&L API on every request, both on a ``bize.read`` token.

The guard at the bottom walks every GET operation a token can reach (the generated OpenAPI document,
filtered by ``access_policy.token_scope_includes``, so it follows that rule as it changes), calls each on
seeded data with a live token, and fails if the request sends any INSERT, UPDATE or DELETE to the
database other than the one write the bearer path itself makes (``ALLOWED_WRITES``).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import event

from app.core.db import engine
from app.core.db.models.user import UserRole
from app.core.security.access_policy import token_scope_includes
from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient
from app.features.mcp_oauth.services import rate_limit
from tests.costing_helpers import login, lot, new_org, price
from tests.factories import UserFactory
from tests.mcp_oauth.support import TEST_NAME_PREFIX, bearer, make_client, mint_grant, unique_addr
from tests.openapi.seeds import SEEDS
from tests.org_purge import purge_orgs

API = "/api/core/costing"
FIXED_UUID = "00000000-0000-4000-8000-000000000000"


def _two_months_on() -> date:
    """A date in the month after next: the month that has just ended closes on the next costing read."""
    from app.features.costing.purchase_sources import nz_today

    real = nz_today()
    index = real.year * 12 + real.month - 1 + 2
    return date(index // 12, index % 12 + 1, 5)


def _clock(monkeypatch, today):
    monkeypatch.setattr("app.features.costing.purchase_sources.nz_today", lambda: today)


def _client(app):
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    client.environ_base["REMOTE_ADDR"] = unique_addr()
    return client


@pytest.fixture
def assistant_org(db, flask_app):
    """An org with costing, assistants on for admins, and an admin with a session and a read token."""
    org = new_org(db)
    org_id = org.id
    admin = UserFactory(org_id=org.id, email=f"drs2-{org.id.hex[:8]}@example.test", role=UserRole.ADMIN)
    db.add(McpOrgSettings(org_id=org.id, enabled=True))
    db.add(McpAllowedRole(org_id=org.id, role_key="builtin:admin"))
    db.commit()
    client_row = make_client(db)
    _grant, access, _refresh = mint_grant(db, admin, client_row)
    with flask_app.app_context():
        yield {
            "org": org,
            "token": _client(flask_app),
            "headers": bearer(access),
            "session": login(flask_app, admin.email),
        }
    db.rollback()
    purge_orgs(db, [org_id])
    db.query(OAuthClient).filter(OAuthClient.client_name.like(f"{TEST_NAME_PREFIX}%")).delete(synchronize_session=False)
    db.commit()


def _snapshot_count(db, org_id) -> int:
    from app.features.costing.models import StockValueSnapshot

    db.expire_all()
    return db.query(StockValueSnapshot).filter(StockValueSnapshot.org_id == org_id).count()


# --- (1) stock value -----------------------------------------------------------------------------


def test_s2_a_token_read_of_stock_value_after_a_month_end_takes_no_snapshot(assistant_org, db, monkeypatch):
    org = assistant_org["org"]
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    _clock(monkeypatch, _two_months_on())

    for path in (f"{API}/stock-value", f"{API}/stock-value/snapshots"):
        resp = assistant_org["token"].get(path, headers=assistant_org["headers"])
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert _snapshot_count(db, org.id) == 0

    # The value itself still answers: the read just doesn't close the month.
    body = assistant_org["token"].get(f"{API}/stock-value", headers=assistant_org["headers"]).get_json()
    assert body["total"] is not None and float(body["total"]) == 50.0

    # A person's session keeps today's behaviour (AC133): their first costing read closes the month.
    assert assistant_org["session"].get(f"{API}/stock-value").status_code == 200
    assert _snapshot_count(db, org.id) == 1


# --- (2) the bridge's Xero P&L -------------------------------------------------------------------


def test_s2_a_token_read_of_the_bridge_makes_no_xero_call(assistant_org, db, monkeypatch):
    from app.features.costing import stock_value
    from tests.test_costing_bridge import PL_SCOPES, install_pl, pl_rows
    from tests.test_costing_purchases import FakeXero, connect

    org = assistant_org["org"]
    connect(db, org.id, scopes=PL_SCOPES)
    fake = FakeXero().install(monkeypatch)
    install_pl(monkeypatch, fake, lambda *_: pl_rows({"Cost of Sales": []}))
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    opening = stock_value.take_snapshot(db, org.id, kind="manual", trigger="manual", as_of_date=date(2026, 10, 31))
    db.commit()
    closing = stock_value.take_snapshot(db, org.id, kind="manual", trigger="manual", as_of_date=date(2026, 11, 30))
    db.commit()
    url = f"{API}/bridge?from={opening.id}&to={closing.id}"

    resp = assistant_org["token"].get(url, headers=assistant_org["headers"])
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_json()
    assert [c for c in fake.calls if c[0] == "profit_and_loss"] == []
    assert body["xero"] == {"state": "not_available_to_assistants"}
    assert body["tie_out"] is None
    assert body["roll_forward"]["opening"] is not None  # the half that needs no Xero is still there

    # A session still gets the live tie-out.
    session = assistant_org["session"].get(url)
    assert session.status_code == 200
    assert session.get_json()["xero"]["state"] == "ok"
    assert len([c for c in fake.calls if c[0] == "profit_and_loss"]) == 1


# --- (3) every token-reachable GET writes nothing ------------------------------------------------

# The only writes a token request may make, each named with why. Nothing else: no snapshot, no record.
#
# 1. The bearer path itself: it stamps the grant's ``last_used_at`` (``GrantRepository.touch_last_used``,
#    at most once a minute) so Settings can show when an assistant last connected.
# 2. ``system_findings_cache``: a derived read-through cache of the expired-materials / stock-integrity
#    checks (``app/features/compliance_checks/system_findings_cache.py``). It holds no record of its own,
#    is invalidated by any stock or batch change and rewritten nightly; skipping the write would re-run a
#    ~1.3s DAG check on every assistant call instead.
# 3. ``audit_logs`` rows whose action is ``download_*``: an append-only note that someone downloaded a
#    document (the licensing pack for an inspector). Recording who read it is the point of the log.
ALLOWED_WRITES = (
    (re.compile(r"^UPDATE oauth_grants SET last_used_at=%\(last_used_at\)s WHERE ", re.IGNORECASE), None),
    (re.compile(r"^INSERT INTO system_findings_cache\b", re.IGNORECASE), None),
    (
        re.compile(r"^INSERT INTO audit_logs\b", re.IGNORECASE),
        lambda params: isinstance(params, dict) and str(params.get("action", "")).startswith("download_"),
    ),
)
_LEADING_COMMENTS = re.compile(r"^(?:\s+|--[^\n]*\n|/\*.*?\*/)*", re.DOTALL)
_WRITE = re.compile(
    r"^(?:WITH\b.*?\b)?(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP|COPY|REFRESH|CALL|LOCK|GRANT|REVOKE)\b",
    re.IGNORECASE | re.DOTALL,
)

# Xero operations a token GET may call, each with why. Every other Xero call from a token GET fails the
# guard (each one spends the org's Xero rate limit, the second half of S2).
ALLOWED_XERO = {
    # The operation *is* fetching one document from Xero, once per ask; nothing is stored. DR-S1 narrows
    # token routes to the x-bize.mcp catalogue, which does not include either: follow-up in the MR.
    "crm_crm_api_get_invoice_pdf": "fetches the invoice's PDF from Xero",
    "crm_crm_api_get_invoice_view_url": "fetches the invoice's online link from Xero",
}


def _token_reachable_gets():
    import app.app as app_module
    from app.api.openapi.document import build

    built = build(app_module.app)
    by_oid = {}
    for path, item in built.document["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                by_oid[op["operationId"]] = (path, method.upper(), op)
    return sorted(
        (oid, by_oid[oid][0], by_oid[oid][2])
        for oid, (endpoint, method) in built.endpoints.items()
        if method == "GET" and token_scope_includes(endpoint, method) and oid in by_oid
    )


TOKEN_GETS = _token_reachable_gets()

# A path parameter the showcase seeds, by name; anything else gets a well-formed id that matches nothing
# (the route still runs its read path up to its 404).
_SEEDED_PARAMS = {
    "inventory_item_id": "gin_lot",
    "item_id": "gin_lot",
    "raw_material_id": "juniper",
    "execution_id": "execution",
    "process_id": "process",
    "stocktake_id": "stocktake",
    "key": "product_key",
    "snapshot_id": "snapshot",
    "contact_id": "contact",
    "invoice_id": "invoice",
}


def _today() -> str:
    return date.today().isoformat()


# Path values and queries for the operations that need more than an id: (path values, query), each a
# function of the seeded ids.
_EXTRA = {
    "crm_crm_api_get_customer_invoice_defaults": lambda ids: ({}, {"invoice_date": _today()}),
    "compliant_compliant_cca_movements_get_period_review": lambda ids: ({}, {"start": "2026-01-01", "end": _today()}),
    "compliant_compliant_cca_movements_get_register": lambda ids: ({}, {"start": "2026-01-01", "end": _today()}),
    "planning_get_capacity": lambda ids: ({}, {"start": _today(), "end": _today()}),
    "crm_crm_api_product_sales_by_store": lambda ids: ({}, {"start_date": "2026-01-01", "end_date": _today()}),
    "core_evidence_list": lambda ids: ({}, {"execution_id": ids["execution"]}),
    "crm_crm_api_get_matching_candidates": lambda ids: ({}, {"product": "Gin"}),
    "core_entity_story": lambda ids: ({"entity_type": "inventory_item", "entity_id": ids["gin_lot"]}, {}),
    "core_entity_summary_detail": lambda ids: ({"entity_type": "inventory_item", "entity_id": ids["gin_lot"]}, {}),
    "costing_get_material_history": lambda ids: ({"material": "Juniper"}, {}),
}


def _url(world, oid, path, op):
    seeded = SEEDS[oid](world) if oid in SEEDS else None
    values, query = {}, dict(seeded.query if seeded else {})
    if oid in _EXTRA:
        extra_values, extra_query = _EXTRA[oid](world.ids)
        values.update(extra_values)
        query.update(extra_query)
    for parameter in op.get("parameters", []):
        if parameter["in"] != "path":
            continue
        name = parameter["name"]
        if name in values:
            continue
        if seeded and name in seeded.params:
            values[name] = seeded.params[name]
        elif name in _SEEDED_PARAMS and _SEEDED_PARAMS[name] in world.ids:
            values[name] = world.ids[_SEEDED_PARAMS[name]]
        else:
            schema = parameter.get("schema", {})
            values[name] = 1 if schema.get("type") == "integer" else FIXED_UUID
    return path.format(**values), query


def _sql(statement: str) -> str:
    return _LEADING_COMMENTS.sub("", statement, count=1)


@contextmanager
def _recording_writes():
    seen: list[str] = []

    def allowed(text, params):
        return any(rule.match(text) and (check is None or check(params)) for rule, check in ALLOWED_WRITES)

    def before(_conn, _cursor, statement, params, _context, _many):
        text = _sql(statement)
        if _WRITE.match(text) and not allowed(text, params):
            seen.append(" ".join(text.split())[:200])

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _recording_xero(monkeypatch) -> list[str]:
    """Every outbound Xero call goes through ``XeroAPIClient._get_api_client``: record it and refuse it,
    so no test ever reaches Xero and a call a route swallows is still seen."""
    from app.features.crm.services import xero_api_client

    calls: list[str] = []

    def refuse(_self):
        calls.append("xero")
        raise RuntimeError("the guard refuses outbound Xero calls")

    monkeypatch.setattr(xero_api_client.XeroAPIClient, "_get_api_client", refuse)
    return calls


@pytest.fixture(scope="module")
def guarded_world(showcase_world):
    """The showcase org, plus what the remaining token reads need to run past their lookups: a manual
    snapshot, the CRM feature, a Xero connection, a Xero customer with no payment terms stored (so the
    invoice-defaults read would ask Xero for them) and an authorised invoice."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.costing import stock_value
    from app.features.costing.models import StockValueSnapshot
    from app.features.crm.models.xero_contact import XeroContact
    from app.features.crm.models.xero_invoice import XeroInvoice
    from tests.test_costing_purchases import connect

    db, org_id = showcase_world.db, showcase_world.org.id
    for feature in ("crm", "contracts", "tastings"):
        FeatureSubscriptionRepository(db).grant(org_id, feature)
    connect(db, org_id)
    contact = XeroContact(
        org_id=org_id,
        name="Showcase Bottle Shop",
        xero_contact_id=f"xc-{uuid4().hex}",
        xero_tenant_id=f"tenant-{org_id}",
    )
    db.add(contact)
    db.flush()
    invoice = XeroInvoice(
        org_id=org_id,
        xero_invoice_id=f"xi-{uuid4().hex}",
        xero_tenant_id=f"tenant-{org_id}",
        contact_id=contact.id,
        xero_contact_id=contact.xero_contact_id,
        invoice_number="INV-S2",
        invoice_type="ACCREC",
        status="AUTHORISED",
        total=100,
        date=datetime.now(UTC).date(),
    )
    db.add(invoice)
    snapshot = stock_value.take_snapshot(db, org_id, kind="manual", trigger="manual")
    db.commit()
    showcase_world.ids.update(snapshot=str(snapshot.id), contact=str(contact.id), invoice=str(invoice.id))
    yield showcase_world
    db.rollback()
    db.query(StockValueSnapshot).filter(StockValueSnapshot.org_id == org_id).delete(synchronize_session=False)
    db.commit()


# A token GET that may answer other than 2xx on the seeded data, each with why. Anything else must come
# back 2xx, so a route can't hide a write behind a 404 the seed caused. A path id the seed has no row for
# gets ``FIXED_UUID`` and lands here, named.
_NO_ROW = "no such row is seeded: the id is FIXED_UUID, so the route answers 404 after its lookup"
EXPECTED_NON_2XX = {
    "compliant_compliant_api_download_np3_record_file": _NO_ROW,
    "compliant_compliant_api_get_report": _NO_ROW,
    "compliant_compliant_api_np3_audit_check": _NO_ROW,
    "compliant_compliant_wine_lot_trace": _NO_ROW,
    "contracts_get_order": _NO_ROW,
    "contracts_list_dispatches": _NO_ROW,
    "contracts_list_materials": _NO_ROW,
    "core_evidence_download": _NO_ROW,
    "core_process_docs_download": _NO_ROW,
    "costing_purchase_candidates": _NO_ROW,
    "crm_crm_api_get_task": _NO_ROW,
    "operational_cases_operational_cases_api_get_case": _NO_ROW,
    "operational_cases_operational_cases_api_get_case_history": _NO_ROW,
    "operational_cases_operational_cases_api_get_case_history_events": _NO_ROW,
    "operational_cases_operational_cases_api_list_case_events": _NO_ROW,
    "recalls_draft_notice": _NO_ROW,
    "recalls_get_recall": _NO_ROW,
    "recalls_get_recall_by_case": _NO_ROW,
    "site_transfers_detail": _NO_ROW,
    "crm_crm_api_get_invoice_trace_items": "the seeded invoice has no line items: 404 Invoice not found",
    "compliant_compliant_api_core_sources": "needs a search request the guard does not build: 400",
    "compliant_compliant_cca_movements_get_period_review": "needs a licence_id; no licence is seeded: 400",
    "compliant_compliant_verification_suggest_verification_step": "needs a verification outcome: 400",
    "planning_get_promise": "needs an order to promise: 400",
    "sites_site_position": "multiple sites are off for the showcase org: 400",
    "crm_crm_api_excise_month": "NZ alcohol module is not set up for the showcase org: 404",
    "crm_crm_api_excise_months": "NZ alcohol module is not set up for the showcase org: 404",
    "tastings_choices": "tastings need the NZ alcohol module: 404",
    "tastings_get_tasting": "tastings need the NZ alcohol module: 404",
    "tastings_list_tastings": "tastings need the NZ alcohol module: 404",
    "tastings_pool": "tastings need the NZ alcohol module: 404",
    "tastings_tasting_invoice_lines": "tastings need the NZ alcohol module: 404",
}


def test_s2_the_guard_covers_the_token_reachable_reads():
    oids = {oid for oid, _p, _o in TOKEN_GETS}
    assert len(oids) > 50
    assert {"costing_get_stock_value", "costing_get_bridge", "core_list_inventory"} <= oids
    assert set(EXPECTED_NON_2XX) <= oids, "an expected non-2xx entry names an operation the guard no longer runs"
    assert set(ALLOWED_XERO) <= oids


def test_s2_the_recorder_sees_a_write_and_lets_only_the_named_allowances_through(db):
    from sqlalchemy import text

    with _recording_writes() as seen:
        db.execute(text("UPDATE oauth_grants SET last_used_at=:last_used_at WHERE false"), {"last_used_at": None})
        db.execute(text("UPDATE oauth_grants SET last_used_at=now(), revoked_at=now() WHERE false"))
        db.execute(text("/* a comment */ UPDATE organisations SET name=name WHERE false"))
        db.execute(text("DELETE FROM system_findings_cache WHERE false"))  # only its upsert is allowed
        audit = text("INSERT INTO audit_logs (id, action) SELECT gen_random_uuid(), :action WHERE false")
        db.execute(audit, {"action": "download_licensing_pack"})  # a download note: allowed
        db.execute(audit, {"action": "update_licence"})  # any other audit row is a write
    db.rollback()
    assert [s.split(" WHERE")[0] for s in seen] == [
        "UPDATE oauth_grants SET last_used_at=now(), revoked_at=now()",
        "UPDATE organisations SET name=name",
        "DELETE FROM system_findings_cache",
        "INSERT INTO audit_logs (id, action) SELECT gen_random_uuid(), %(action)s",
    ]


@pytest.mark.parametrize("oid,path,op", TOKEN_GETS, ids=[oid for oid, _p, _o in TOKEN_GETS])
def test_s2_a_token_get_writes_nothing(guarded_world, monkeypatch, oid, path, op):
    import app.app as app_module

    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    _clock(monkeypatch, _two_months_on())  # a month has ended since the seed: a costing read could close it
    xero_calls = _recording_xero(monkeypatch)
    url, query = _url(guarded_world, oid, path, op)
    client = _client(app_module.app)
    with _recording_writes() as seen:
        resp = client.get(url, query_string=query, headers=guarded_world.token_headers)
    assert seen == [], f"{oid} ({url}) wrote on a read-only token: {seen}"
    if oid in ALLOWED_XERO:
        return  # the refused Xero call decides its status; that it made one is the allowance
    assert xero_calls == [], f"{oid} ({url}) called Xero on a read-only token"
    if oid in EXPECTED_NON_2XX:
        assert not 200 <= resp.status_code < 300, f"{oid} now answers {resp.status_code}: drop it from EXPECTED_NON_2XX"
        return
    assert 200 <= resp.status_code < 300, f"{oid} ({url}): {resp.status_code} {resp.get_data(as_text=True)[:200]}"
