"""Live-cogs 8.1b: purchase tables and the purchases list — tenant isolation, permissions, schema.

Spec .agents/specs/live-cogs.md, "Data model" (purchase_documents, purchase_lines, xero_accounts),
"Users & permissions", AC40-AC42 patterns applied to the 8.1b route, AC74.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.user import UserRole
from tests.costing_helpers import new_org, purge, user_client
from tests.costing_purchase_helpers import (
    D,
    FakeXero,
    _connect,
    line,
    line_by_key,
    purchase_documents,
    purchase_lines,
    transaction,
)
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


def make_world(db, flask_app, monkeypatch, *, grant=True):  # noqa: F811
    org = new_org(db, grant=grant)
    _connect(db, org.id)
    return SimpleNamespace(org=org, admin=user_client(db, flask_app, org), fake=FakeXero(monkeypatch))


@pytest.fixture
def world(db, flask_app, monkeypatch):  # noqa: F811
    w = make_world(db, flask_app, monkeypatch)
    w.fake.transactions = [transaction("t1", [line(line_id="A")])]
    assert w.fake.sync(db, w.org).success
    yield w
    purge(db, w.org)


# --- AC73/AC40-42 patterns on the list route ------------------------------------------------


def test_ac73_roles_and_permissions_on_the_list(world, db, flask_app):  # noqa: F811
    path = f"{API}/purchases?tab=to_record"
    assert user_client(db, flask_app, world.org, role=UserRole.PRODUCTION).get(path).status_code == 403
    assert user_client(db, flask_app, world.org, role=UserRole.MEMBER).get(path).status_code == 200
    viewer = user_client(db, flask_app, world.org, permissions=["costs.view"])
    assert viewer.get(path).status_code == 200
    manager_only = user_client(db, flask_app, world.org, permissions=["costs.manage"])
    assert manager_only.get(path).status_code == 403


def test_ac73_the_list_is_read_only(world):
    assert world.admin.post(f"{API}/purchases", json={}).status_code in (403, 404, 405)
    assert world.admin.delete(f"{API}/purchases").status_code in (403, 404, 405)


def test_ac73_unauthenticated_requests_get_401(world, flask_app):  # noqa: F811
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.get(f"{API}/purchases").status_code in (401, 403)


def test_ac73_without_the_costing_feature_the_list_is_404_for_an_admin(db, flask_app, monkeypatch):  # noqa: F811
    w = make_world(db, flask_app, monkeypatch, grant=False)
    try:
        assert w.admin.get(f"{API}/purchases").status_code == 404
    finally:
        purge(db, w.org)


def test_ac73_another_organisations_purchases_are_never_listed(world, db, flask_app, monkeypatch):  # noqa: F811
    other = make_world(db, flask_app, monkeypatch)
    try:
        other.fake.transactions = [transaction("t1", [line(line_id="A", amount="11.50", tax="1.50")])]
        assert other.fake.sync(db, other.org).success  # the same Xero ids as the first organisation

        mine = world.admin.get(f"{API}/purchases?tab=to_record").get_json()
        theirs = other.admin.get(f"{API}/purchases?tab=to_record").get_json()

        assert [i["amount_ex_tax"] for i in mine["items"]] == ["90.0000"]
        assert [i["amount_ex_tax"] for i in theirs["items"]] == ["10.0000"]
        assert not {i["id"] for i in mine["items"]} & {i["id"] for i in theirs["items"]}
    finally:
        purge(db, other.org)


# --- AC74: isolation in the data model ----------------------------------------------------------


def test_ac74_syncing_one_organisation_never_touches_anothers_lines(world, db, flask_app, monkeypatch):  # noqa: F811
    other = make_world(db, flask_app, monkeypatch)
    try:
        other.fake.transactions = [transaction("t1", [line(line_id="A", amount="11.50", tax="1.50")])]
        other.fake.sync(db, other.org)
        before = line_by_key(db, world.org.id, "A").amount_ex_tax

        other.fake.transactions = [transaction("t1", [line(line_id="A", amount="230.00", tax="30.00")])]
        other.fake.sync(db, other.org)

        assert line_by_key(db, world.org.id, "A").amount_ex_tax == before == D("90")
        assert line_by_key(db, other.org.id, "A").amount_ex_tax == D("200")
        assert len(purchase_documents(db, world.org.id)) == len(purchase_documents(db, other.org.id)) == 1
    finally:
        purge(db, other.org)


def test_ac74_a_line_cannot_point_at_another_organisations_document(world, db, flask_app, monkeypatch):  # noqa: F811
    from app.features.costing.purchase_models import PurchaseLine

    other = make_world(db, flask_app, monkeypatch)
    try:
        foreign_document = purchase_documents(db, world.org.id)[0]
        db.add(
            PurchaseLine(
                org_id=other.org.id,
                document_id=foreign_document.id,
                line_key="forged",
                amount_ex_tax=D("1"),
                tax_amount=D("0"),
                treatment="stock",
                state="open",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    finally:
        purge(db, other.org)


def test_ac74_the_upsert_keys_are_unique_per_organisation(world, db):
    from app.features.costing.purchase_models import PurchaseDocument, PurchaseLine

    doc = purchase_documents(db, world.org.id)[0]
    db.add(
        PurchaseDocument(
            org_id=world.org.id,
            source=doc.source,
            external_id=doc.external_id,
            kind="spend",
            document_date=date(2026, 11, 3),
            status="active",
            currency_code="NZD",
            currency_rate=D("1"),
            total_ex_tax=D("1"),
            total_tax=D("0"),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    db.add(
        PurchaseLine(
            org_id=world.org.id,
            document_id=doc.id,
            line_key="A",
            amount_ex_tax=D("1"),
            tax_amount=D("0"),
            treatment="stock",
            state="open",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize(
    "bad",
    [
        {"treatment": "gift"},
        {"state": "done"},
        {"review_reason": "because"},
        {"not_stock_amount": D("500")},  # more than the line's 90
    ],
)
def test_ac74_the_database_refuses_nonsense_values(world, db, bad):
    row = purchase_lines(db, world.org.id)[0]
    for key, value in bad.items():
        setattr(row, key, value)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac74_a_document_source_and_kind_are_from_the_known_lists(world, db):
    doc = purchase_documents(db, world.org.id)[0]
    doc.source = "quickbooks"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    doc = purchase_documents(db, world.org.id)[0]
    doc.kind = "gift"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ac74_lines_go_with_their_document_and_an_organisation_with_its_purchases(db, flask_app, monkeypatch):  # noqa: F811
    from app.features.costing.purchase_models import PurchaseDocument, PurchaseLine
    from app.features.crm.models.xero_account import XeroAccount

    w = make_world(db, flask_app, monkeypatch)
    w.fake.transactions = [transaction("t1", [line(line_id="A")])]
    w.fake.sync(db, w.org)
    org_id = w.org.id
    db.query(PurchaseDocument).filter(PurchaseDocument.org_id == org_id).delete(synchronize_session=False)
    db.commit()
    assert db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id).count() == 0  # cascade

    w.fake.sync(db, w.org)
    purge(db, w.org)  # the org purge walks every table with an org_id

    assert db.query(PurchaseDocument).filter(PurchaseDocument.org_id == org_id).count() == 0
    assert db.query(XeroAccount).filter(XeroAccount.org_id == org_id).count() == 0


def test_ac74_account_codes_are_unique_per_organisation(world, db):
    from app.features.crm.models.xero_account import XeroAccount

    db.expire_all()
    existing = db.query(XeroAccount).filter(XeroAccount.org_id == world.org.id).first()
    db.add(
        XeroAccount(
            org_id=world.org.id,
            xero_account_id=existing.xero_account_id,
            code=f"x{uuid4().hex[:4]}",
            name="Clone",
            type="EXPENSE",
            account_class="EXPENSE",
            status="ACTIVE",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
