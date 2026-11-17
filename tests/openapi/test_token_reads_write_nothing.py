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
from tests.costing_helpers import login, lot, new_org, price, purge
from tests.factories import UserFactory
from tests.mcp_oauth.support import TEST_NAME_PREFIX, bearer, make_client, mint_grant, unique_addr
from tests.openapi.seeds import SEEDS

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
    purge(db, org)
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

# The only writes a token request may make, each named with why. The bearer path stamps the grant's
# ``last_used_at`` (``GrantRepository.touch_last_used``, at most once a minute) so Settings can show
# when an assistant last connected. Nothing else: not a snapshot, not a cache row, not a log row.
ALLOWED_WRITES = (re.compile(r"^UPDATE oauth_grants SET last_used_at=", re.IGNORECASE),)
_WRITE = re.compile(r"^\s*(?:WITH\b.*?\b)?(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", re.IGNORECASE | re.DOTALL)


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
}


def _url(world, oid, path, op):
    seeded = SEEDS[oid](world) if oid in SEEDS else None
    values, query = {}, (seeded.query if seeded else {})
    for parameter in op.get("parameters", []):
        if parameter["in"] != "path":
            continue
        name = parameter["name"]
        if seeded and name in seeded.params:
            values[name] = seeded.params[name]
        elif name in _SEEDED_PARAMS and _SEEDED_PARAMS[name] in world.ids:
            values[name] = world.ids[_SEEDED_PARAMS[name]]
        else:
            schema = parameter.get("schema", {})
            values[name] = 1 if schema.get("type") == "integer" else FIXED_UUID
    return path.format(**values), query


@contextmanager
def _recording_writes():
    seen: list[str] = []

    def before(_conn, _cursor, statement, _params, _context, _many):
        if _WRITE.match(statement) and not any(rule.match(statement.strip()) for rule in ALLOWED_WRITES):
            seen.append(" ".join(statement.split())[:200])

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


@pytest.fixture(scope="module")
def guarded_world(showcase_world):
    """The showcase org, plus one manual snapshot so the snapshot routes have something to read."""
    from app.features.costing import stock_value

    stock_value.take_snapshot(showcase_world.db, showcase_world.org.id, kind="manual", trigger="manual")
    showcase_world.db.commit()
    snapshot = stock_value.list_snapshots(showcase_world.db, showcase_world.org.id)[0]
    showcase_world.ids["snapshot"] = str(snapshot.id)
    return showcase_world


def test_s2_the_guard_covers_the_token_reachable_reads():
    oids = {oid for oid, _p, _o in TOKEN_GETS}
    assert len(oids) > 50
    assert {"costing_get_stock_value", "costing_get_bridge", "core_list_inventory"} <= oids


def test_s2_the_recorder_sees_a_write_and_lets_the_bearer_stamp_through(db):
    from sqlalchemy import text

    with _recording_writes() as seen:
        db.execute(text("UPDATE oauth_grants SET last_used_at=now() WHERE false"))
        db.execute(text("UPDATE organisations SET name=name WHERE false"))
    db.rollback()
    assert seen == ["UPDATE organisations SET name=name WHERE false"]


@pytest.mark.parametrize("oid,path,op", TOKEN_GETS, ids=[oid for oid, _p, _o in TOKEN_GETS])
def test_s2_a_token_get_writes_nothing(guarded_world, monkeypatch, oid, path, op):
    import app.app as app_module

    monkeypatch.setattr(rate_limit, "BEARER_REQUESTS_PER_MINUTE", 10_000_000)
    _clock(monkeypatch, _two_months_on())  # a month has ended since the seed: a costing read could close it
    url, query = _url(guarded_world, oid, path, op)
    client = _client(app_module.app)
    with _recording_writes() as seen:
        resp = client.get(url, query_string=query, headers=guarded_world.token_headers)
    assert resp.status_code < 500, f"{url}: {resp.status_code} {resp.get_data(as_text=True)[:300]}"
    assert resp.status_code != 401, f"{url}: the token was refused, so the route never ran"
    assert seen == [], f"{oid} ({url}) wrote on a read-only token: {seen}"
