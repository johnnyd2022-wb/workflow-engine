"""Separate portal realm, immutable publications and hostile route isolation."""

import hashlib
import io
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError, InternalError

from app.core.db.models.user import User, UserRole
from app.core.security.access_policy import POLICY, PORTAL_SIGNED_IN, PUBLIC, allows, requirement_for
from app.features.contract_manufacturing.models.portal import (
    PortalDocument,
    PortalInvite,
    PortalPrincipal,
    PortalPublication,
    PortalSession,
)
from app.features.contract_manufacturing.portal_security import COOKIE_NAME, PORTAL_ENDPOINTS
from app.features.contract_manufacturing.routes import portal as portal_routes
from app.features.contract_manufacturing.services.portal_auth import token_hash
from tests.factories import UserFactory
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixtures
from tests.test_contract_orders import _customer, _login, _order, world  # noqa: F401 -- fixtures

PASSWORD = "A-portal-password-2026"


def _portal_limiters(app):
    """The app's limiter and the one the portal routes were decorated with. They are the
    same object in production, but test_auth_rate_limit_gating reloads auth_routes, which
    leaves routes imported before the reload bound to the previous Limiter."""
    return {id(limiter): limiter for limiter in (app.limiter, portal_routes.limiter)}.values()


@pytest.fixture
def portal_world(world, db):  # noqa: F811 -- imported fixture
    limiters = [(limiter, limiter.enabled) for limiter in _portal_limiters(world["app"])]
    for limiter, _ in limiters:
        limiter.enabled = False
    customers = [
        _customer(world["clients"][0], "Brand A"),
        _customer(world["clients"][0], "Brand B"),
        _customer(world["clients"][1], "Brand C"),
    ]
    orders = [_order(world["clients"][0 if i < 2 else 1], customer["id"]) for i, customer in enumerate(customers)]
    world.update(customers=customers, orders=orders)
    yield world
    for limiter, was_enabled in limiters:  # shared app: later suites expect a live limiter
        limiter.enabled = was_enabled
    db.rollback()
    org_ids = [org.id for org in world["orgs"]]
    for model in (PortalSession, PortalInvite, PortalPublication, PortalDocument, PortalPrincipal):
        db.query(model).filter(model.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


def _invite(context, index=0):
    response = context["clients"][0 if index < 2 else 1].post(
        f"/api/core/contract-customers/{context['customers'][index]['id']}/portal-invites",
        json={"email": f"owner{index}@brand.test"},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["invite_link"].split("#")[1]


def _client(context):
    client = context["app"].test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return client


def _accept(context, index=0):
    client = _client(context)
    response = client.post("/portal/api/accept", json={"token": _invite(context, index), "password": PASSWORD})
    assert response.status_code == 200, response.get_json()
    return client


def _publish(context, index=0, **data):
    response = context["clients"][0 if index < 2 else 1].post(
        f"/api/core/contract-orders/{context['orders'][index]['id']}/portal-publications", json=data
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _upload(context, index=0, content=b"%PDF-1.4\nshared result"):
    response = context["clients"][0 if index < 2 else 1].post(
        f"/api/core/contract-orders/{context['orders'][index]['id']}/portal-documents",
        data={"title": "Shared CoA", "document": (io.BytesIO(content), "result.pdf", "application/pdf")},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["document"]


def test_invitation_session_separation_and_one_use(portal_world, db):
    w = portal_world
    users_before = db.query(User).count()
    raw = _invite(w)
    invite = db.query(PortalInvite).filter_by(token_hash=token_hash(raw)).one()
    assert invite.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in repr(invite.__dict__)
    client = w["clients"][0]
    response = client.post("/portal/api/accept", json={"token": raw, "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers.getlist("Set-Cookie")
    assert any(
        COOKIE_NAME in value and "Secure" in value and "HttpOnly" in value and "SameSite=Strict" in value
        for value in cookie
    )
    nonce = client.get_cookie(COOKIE_NAME).value
    principal = db.query(PortalPrincipal).filter_by(email="owner0@brand.test").one()
    assert not hasattr(principal, "role") and not hasattr(principal, "user_id")
    assert db.query(User).count() == users_before
    with client.session_transaction() as state:
        assert not set(state) & {"user_id", "org_id", "pending_2fa_user_id", "_user_cache"}
    assert db.query(PortalSession).filter_by(token_hash=token_hash(nonce)).one().principal_id == principal.id
    assert _client(w).post("/portal/api/accept", json={"token": raw, "password": PASSWORD}).status_code == 410
    assert client.get("/portal/api/orders").status_code == 200
    assert client.post("/portal/api/logout", json={}).status_code == 200
    client.set_cookie(COOKIE_NAME, nonce)
    assert client.get("/portal/api/orders").status_code == 401


def test_invite_reissue_expiry_revocation_and_password_policy(portal_world, db):
    w = portal_world
    first = _invite(w)
    second = _invite(w)
    client = _client(w)
    assert client.post("/portal/api/accept", json={"token": first, "password": PASSWORD}).status_code == 410
    for password in ("short", "é" * 40, None):
        assert client.post("/portal/api/accept", json={"token": second, "password": password}).status_code == 400
    row = db.query(PortalInvite).filter_by(token_hash=token_hash(second)).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.post("/portal/api/accept", json={"token": second, "password": PASSWORD}).status_code == 410
    third = _invite(w)
    row = db.query(PortalInvite).filter_by(token_hash=token_hash(third)).one()
    assert (
        w["clients"][0]
        .delete(f"/api/core/contract-customers/{w['customers'][0]['id']}/portal-invites/{row.id}")
        .status_code
        == 204
    )
    assert client.post("/portal/api/accept", json={"token": third, "password": PASSWORD}).status_code == 410


def test_immutable_projection_and_explicit_unavailable_fields(portal_world, db):
    w = portal_world
    document = _upload(w)
    first = _publish(
        w,
        stage_label="Packed <script>alert(1)</script>",
        actual_abv="40.2",
        spec_abv="40",
        document_ids=[document["id"]],
    )
    client = _accept(w)
    order_id = w["orders"][0]["id"]
    response = client.get(f"/portal/api/orders/{order_id}")
    payload = response.get_json()["order"]
    assert payload["quality"]["actual_abv"] == "40.2"
    assert set(payload) == {
        "schema_version",
        "order_id",
        "reference",
        "customer_name",
        "producer_name",
        "status",
        "due_date",
        "shared_at",
        "revision",
        "progress",
        "timing",
        "quantities",
        "batches",
        "quality",
        "materials",
        "yield",
        "delivery",
        "documents",
        "waiting_on_you",
    }
    for key in ("timing", "materials", "yield", "delivery", "waiting_on_you"):
        assert payload[key]["available"] is False
    assert payload["timing"]["forecast_ready_date"] is None and payload["quality"]["qc_passed"] is None
    assert all(
        key not in response.get_data(as_text=True)
        for key in (
            "process_id",
            "process_version_id",
            "spec_reference",
            "execution_data",
            "cost",
            "password_hash",
            "token_hash",
        )
    )
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert (
        w["clients"][0]
        .patch(f"/api/core/contract-orders/{order_id}", json={"reference": "Changed private order"})
        .status_code
        == 200
    )
    assert client.get(f"/portal/api/orders/{order_id}").get_json()["order"]["reference"] == payload["reference"]
    page = client.get(f"/portal/orders/{order_id}").get_data(as_text=True)
    assert "&lt;script&gt;" in page and "<script>alert(1)</script>" not in page
    assert "1. Where" in page and "10. What" in page
    second = _publish(w, stage_label="Ready")
    assert second["revision"] == first["revision"] + 1
    assert client.get(f"/portal/api/orders/{order_id}").get_json()["order"]["reference"] == "Changed private order"
    assert w["clients"][0].delete(f"/api/core/contract-orders/{order_id}/portal-publications").status_code == 204
    assert client.get(f"/portal/api/orders/{order_id}").status_code == 404
    assert client.get("/portal/api/orders").get_json()["orders"] == []
    publication = db.query(PortalPublication).filter_by(id=UUID(first["publication_id"])).one()
    publication.payload = {"evil": True}
    with pytest.raises(InternalError):
        db.flush()
    db.rollback()


def test_complete_hostile_portal_route_walk(portal_world):
    w = portal_world
    docs = [_upload(w, index=i) for i in range(3)]
    for index in range(3):
        _publish(w, index, stage_label=f"Private customer {index}", document_ids=[docs[index]["id"]])
    client = _accept(w)
    own, same_org_other, other_org = [o["id"] for o in w["orders"]]
    assert [o["order_id"] for o in client.get("/portal/api/orders").get_json()["orders"]] == [own]
    assert same_org_other not in client.get("/portal").get_data(as_text=True)
    adapter = w["app"].url_map.bind("localhost")
    walked = set()
    for rule in w["app"].url_map.iter_rules():
        if (
            not rule.endpoint.startswith("contract_portal.")
            or requirement_for(rule.endpoint, "GET") != PORTAL_SIGNED_IN
        ):
            continue
        assert getattr(w["app"].view_functions[rule.endpoint], "portal_guarded", False)
        walked.add(rule.endpoint)
        if "order_id" in rule.arguments:
            for index, foreign in ((1, same_org_other), (2, other_org)):
                values = {"order_id": foreign}
                if "document_id" in rule.arguments:
                    values["document_id"] = docs[index]["id"]
                path = adapter.build(rule.endpoint, values)
                assert client.get(path).status_code == 404, path
        if "document_id" in rule.arguments:
            for index in (1, 2):
                path = adapter.build(rule.endpoint, {"order_id": own, "document_id": docs[index]["id"]})
                assert client.get(path).status_code == 404
    assert walked == {endpoint for endpoint in PORTAL_ENDPOINTS if requirement_for(endpoint, "GET") == PORTAL_SIGNED_IN}
    own_doc = client.get(f"/portal/api/orders/{own}/documents/{docs[0]['id']}")
    assert own_doc.status_code == 200 and own_doc.data.startswith(b"%PDF")
    assert "attachment" in own_doc.headers["Content-Disposition"]
    assert own_doc.headers["X-Content-Type-Options"] == "nosniff"
    for index in (1, 2):
        other = _accept(w, index)
        assert other.get(f"/portal/api/orders/{own}").status_code == 404


def test_portal_credentials_rejected_on_every_staff_route(portal_world):
    w = portal_world
    portal = _accept(w)
    raw = portal.get_cookie(COOKIE_NAME).value
    # Include simultaneous valid staff credentials to prove realm isolation runs
    # before staff tenant resolution and permission checks.
    staff = w["clients"][0]
    staff.set_cookie(COOKIE_NAME, raw)
    adapter = w["app"].url_map.bind("localhost")
    checked = 0
    for rule in w["app"].url_map.iter_rules():
        if (
            rule.endpoint in PORTAL_ENDPOINTS
            or rule.endpoint == "static"
            or rule.endpoint.endswith(".static")
            or rule.endpoint == "favicon"
        ):
            continue
        values = {}
        for name, converter in rule._converters.items():
            converter_name = type(converter).__name__
            values[name] = uuid4() if "UUID" in converter_name else 1 if "Integer" in converter_name else "hostile"
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            path = adapter.build(rule.endpoint, values, method=method)
            response = staff.open(path, method=method, json={})
            assert response.status_code == 403, (rule.endpoint, method, path, response.status_code)
            assert response.get_json()["code"] == "portal_realm_only"
            checked += 1
    assert checked > 200
    staff.delete_cookie(COOKIE_NAME)


def test_expiry_deactivation_revocation_and_login_rotation(portal_world, db):
    w = portal_world
    client = _accept(w)
    raw = client.get_cookie(COOKIE_NAME).value
    principal = db.query(PortalPrincipal).filter_by(email="owner0@brand.test").one()
    row = db.query(PortalSession).filter_by(token_hash=token_hash(raw)).one()
    row.last_seen_at = datetime.now(UTC) - timedelta(minutes=31)
    db.commit()
    assert client.get("/portal/api/orders").status_code == 401
    body = {"customer_id": w["customers"][0]["id"], "email": "owner0@brand.test", "password": PASSWORD}
    assert client.post("/portal/api/login", json=body).status_code == 200
    second = client.get_cookie(COOKIE_NAME).value
    assert client.post("/portal/api/login", json=body).status_code == 200
    other = _client(w)
    other.set_cookie(COOKIE_NAME, second)
    assert other.get("/portal/api/orders").status_code == 401
    newest = client.get_cookie(COOKIE_NAME).value
    row = db.query(PortalSession).filter_by(token_hash=token_hash(newest)).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get("/portal/api/orders").status_code == 401
    assert client.post("/portal/api/login", json=body).status_code == 200
    newest = client.get_cookie(COOKIE_NAME).value
    assert (
        w["clients"][0]
        .delete(f"/api/core/contract-customers/{w['customers'][0]['id']}/portal-people/{principal.id}")
        .status_code
        == 204
    )
    assert client.get("/portal/api/orders").status_code == 401
    assert client.post("/portal/api/login", json=body).status_code == 401
    assert _accept(w).get("/portal/api/orders").status_code == 200
    old = _client(w)
    old.set_cookie(COOKIE_NAME, newest)
    assert old.get("/portal/api/orders").status_code == 401


def test_account_throttle_and_real_ip_rate_limit(portal_world, db):
    w = portal_world
    client = _accept(w)
    principal = db.query(PortalPrincipal).filter_by(email="owner0@brand.test").one()
    body = {"customer_id": w["customers"][0]["id"], "email": "owner0@brand.test", "password": "incorrect"}
    for _ in range(5):
        assert client.post("/portal/api/login", json=body).status_code == 401
    assert client.post("/portal/api/login", json={**body, "password": PASSWORD}).status_code == 401
    db.refresh(principal)
    assert principal.locked_until > datetime.now(UTC)
    principal.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.post("/portal/api/login", json={**body, "password": PASSWORD}).status_code == 200
    for limiter in _portal_limiters(w["app"]):
        limiter.enabled = True
        limiter.storage.reset()
    stranger = _client(w)
    statuses = [
        stranger.post("/portal/api/login", json={**body, "email": f"unknown{n}@brand.test"}).status_code
        for n in range(11)
    ]
    assert statuses[:10] == [401] * 10 and statuses[-1] == 429
    for limiter in _portal_limiters(w["app"]):
        limiter.enabled = False


def test_staff_sharing_permissions_and_cross_tenant_references(portal_world, db):
    w = portal_world
    for role in (UserRole.SALES, UserRole.PRODUCTION, UserRole.AUDITOR):
        user = UserFactory(org_id=w["orgs"][0].id, role=role, email=f"portal-{uuid4()}@test.com")
        client = _login(w["app"], user)
        assert (
            client.post(
                f"/api/core/contract-customers/{w['customers'][0]['id']}/portal-invites",
                json={"email": "denied@test.com"},
            ).status_code
            == 403
        )
        status = client.post(
            f"/api/core/contract-orders/{w['orders'][0]['id']}/portal-publications", json={}
        ).status_code
        assert status == (201 if role == UserRole.PRODUCTION else 403)
    foreign = _upload(w, 2)
    order_id = w["orders"][0]["id"]
    base = f"/api/core/contract-orders/{order_id}/portal-publications"
    assert w["clients"][0].post(base, json={"document_ids": [foreign["id"]]}).status_code == 404
    for data in (
        {"execution_data": {}},
        {"recipe": "private"},
        {"forecast_ready_date": "2026-12-01"},
        {"bottling_dates": {str(uuid4()): "2026-12-01"}},
        {"actual_abv": "NaN"},
        {"progress_percent": True},
    ):
        assert w["clients"][0].post(base, json=data).status_code == 400
    assert w["clients"][1].post(base, json={}).status_code == 404
    assert (
        w["clients"][1]
        .post(
            f"/api/core/contract-customers/{w['customers'][0]['id']}/portal-invites", json={"email": "foreign@test.com"}
        )
        .status_code
        == 404
    )
    pub = PortalPublication(
        org_id=w["orgs"][0].id,
        order_id=UUID(order_id),
        customer_id=UUID(w["customers"][1]["id"]),
        revision=99,
        payload={},
        published_by=w["clients"][0].get("/auth/me").get_json()["user"]["id"],
    )
    pub.published_by = UUID(pub.published_by)
    db.add(pub)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_real_csrf_for_accept_login_logout_and_staff_publication(portal_world):
    w = portal_world
    token = _invite(w)
    app = w["app"]
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = _client(w)
        page = client.get("/portal/invite")
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        referer = {"Referer": "https://localhost/portal/invite"}
        body = {"token": token, "password": PASSWORD}
        assert client.post("/portal/api/accept", json=body, headers=referer).status_code == 400
        assert client.post("/portal/api/accept", json=body, headers={**referer, "X-CSRFToken": csrf}).status_code == 200
        page = client.get("/portal")
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        assert client.post("/portal/api/logout", json={}, headers=referer).status_code == 400
        assert client.post("/portal/api/logout", json={}, headers={**referer, "X-CSRFToken": csrf}).status_code == 200
        login = {"customer_id": w["customers"][0]["id"], "email": "owner0@brand.test", "password": PASSWORD}
        page = client.get("/portal/login")
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        assert client.post("/portal/api/login", json=login, headers=referer).status_code == 400
        assert client.post("/portal/api/login", json=login, headers={**referer, "X-CSRFToken": csrf}).status_code == 200
        assert (
            w["clients"][0]
            .post(f"/api/core/contract-orders/{w['orders'][0]['id']}/portal-publications", json={}, headers=referer)
            .status_code
            == 400
        )
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_explicit_route_classification_and_no_staff_fallback(portal_world):
    app = portal_world["app"]
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("contract_portal.") and not rule.endpoint.endswith(".static"):
            assert any(pattern == rule.endpoint for pattern, _, _ in POLICY)
            if requirement_for(rule.endpoint, "GET") == PORTAL_SIGNED_IN:
                assert getattr(app.view_functions[rule.endpoint], "portal_guarded", False)
                for role in UserRole:
                    assert not allows(type("Staff", (), {"role": role})(), rule.endpoint, "GET")
            else:
                assert requirement_for(rule.endpoint, "GET") == PUBLIC
    # A staff cookie by itself cannot resolve a portal principal.
    assert portal_world["clients"][0].get("/portal/api/orders").status_code == 403


def test_linked_batch_ids_are_copied_without_private_execution_data(portal_world, db):
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from tests.test_contract_orders import _recipe

    w = portal_world
    org_id = w["orgs"][0].id
    process, _, _ = _recipe(db, org_id, "Secret botanical recipe")
    batch = ExecutionRepository(db).create_execution(org_id=org_id, process_id=process.id)
    step = db.query(ExecutionStep).filter_by(org_id=org_id, execution_id=batch.id).first()
    step.execution_data = {"secret_supplier_cost": "999", "recipe_instructions": "Private juniper proportion"}
    db.commit()
    order = w["orders"][0]
    response = w["clients"][0].post(
        f"/api/core/contract-orders/{order['id']}/lines/{order['lines'][0]['id']}/batches",
        json={"execution_id": str(batch.id)},
    )
    assert response.status_code == 201
    _publish(w, bottling_dates={str(batch.id): "2026-12-01"})
    client = _accept(w)
    body = client.get(f"/portal/api/orders/{order['id']}").get_json()["order"]
    assert body["batches"]["items"] == [{"batch_id": str(batch.id), "bottling_date": "2026-12-01"}]
    assert all(value not in str(body) for value in ("999", "Private juniper", "Secret botanical"))


def test_document_opt_in_withdrawal_formats_and_immutable_copy(portal_world, db):
    w = portal_world
    first, second = _upload(w), _upload(w)
    order_id = w["orders"][0]["id"]
    _publish(w, document_ids=[first["id"]])
    client = _accept(w)
    assert client.get(f"/portal/api/orders/{order_id}/documents/{second['id']}").status_code == 404
    assert (
        w["clients"][0].delete(f"/api/core/contract-orders/{order_id}/portal-documents/{first['id']}").status_code
        == 204
    )
    assert client.get(f"/portal/api/orders/{order_id}/documents/{first['id']}").status_code == 404
    base = f"/api/core/contract-orders/{order_id}/portal-documents"
    for content, mime in (
        (b"<script>alert(1)</script>", "text/html"),
        (b"<svg></svg>", "image/svg+xml"),
        (b"fake pdf", "application/pdf"),
    ):
        assert (
            w["clients"][0]
            .post(base, data={"title": "unsafe", "document": (io.BytesIO(content), "bad", mime)})
            .status_code
            == 400
        )
    row = db.query(PortalDocument).filter_by(id=UUID(second["id"])).one()
    row.content = b"modified"
    with pytest.raises(InternalError):
        db.flush()
    db.rollback()
    response = w["clients"][0].post(
        base, data={"title": "oversized", "document": (io.BytesIO(b"x" * (6 * 1024 * 1024)), "large.txt", "text/plain")}
    )
    assert response.status_code == 413


def test_customer_boundary_ignores_future_private_snapshot_fields(portal_world, db):
    from app.features.contract_manufacturing.services.portal_sharing import publication_dto

    first = _publish(portal_world)
    row = db.query(PortalPublication).filter_by(id=UUID(first["publication_id"])).one()
    payload = dict(row.payload)
    payload.update(private_recipe="secret", execution_data={"secret": "cost"})
    payload["quality"] = {**payload["quality"], "supplier_cost": "secret"}
    payload["quantities"] = {
        **payload["quantities"],
        "lines": [{**payload["quantities"]["lines"][0], "recipe_instructions": "secret"}],
    }
    payload["waiting_on_you"] = {**payload["waiting_on_you"], "messages": [{"private_notes": "secret"}]}
    assert "secret" not in str(publication_dto(payload))
