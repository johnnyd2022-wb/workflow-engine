"""GL-P10: one readable export of every record the business holds."""

from __future__ import annotations

import csv
import io
import zipfile
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy import MetaData

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.models import Base
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.security.auth_service import AuthService
from app.features.data_export import service
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export
from tests.test_go_live import _cleanup

URL = "/api/core/export/records.zip"


def _download(client) -> zipfile.ZipFile:
    response = client.get(URL)
    assert response.status_code == 200, response.data[:300]
    assert response.mimetype == "application/zip"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="biz-e-records-')
    assert response.headers["Cache-Control"] == "no-store"
    return zipfile.ZipFile(io.BytesIO(response.data))


def _rows(zf: zipfile.ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig"))))


def _all_text(zf: zipfile.ZipFile) -> str:
    return "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())


def _client_for(flask_app, email):  # noqa: F811
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    return client


def _item(db, org_id, name):
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
        item = InventoryItem(
            org_id=org_id, name=name, quantity=3, unit="kg", inventory_type=InventoryType.RAW_MATERIAL.value
        )
        db.add(item)
        db.commit()
    return item


@pytest.fixture
def two_orgs(db, flask_app):  # noqa: F811
    org_a, client_a = _admin_client(db, flask_app)
    org_b, _client_b = _admin_client(db, flask_app)
    yield org_a, client_a, org_b
    _cleanup(db, org_a.id)
    _cleanup(db, org_b.id)


# --- classification: a new table or secret-looking column cannot slip through -------------------


def test_every_org_table_is_exported_or_excluded_with_a_reason(db):
    """Read from the migrated database, so a table no model imports is still caught."""
    exported = {t.name for t in service.tenant_tables(db.connection())}
    for name in service.org_table_names(db.connection()):
        assert name in exported or service.EXCLUDED_TABLES.get(name), (
            f"{name} has org_id: export it or add it to EXCLUDED_TABLES with a reason"
        )
    assert service.ORG_TABLE in exported
    # Lazily imported models (planning) are exported all the same.
    assert "planning_material_commitments" in exported


def test_every_model_without_org_id_is_classified(flask_app):  # noqa: F811
    for table in Base.metadata.tables.values():
        if "org_id" not in table.c and table.name != service.ORG_TABLE:
            assert service.NON_TENANT_TABLES.get(table.name), (
                f"{table.name} has no org_id: is it a business record? classify it in NON_TENANT_TABLES"
            )


def test_every_secret_looking_column_is_dropped_or_declared_safe(db):
    for table in service.tenant_tables(db.connection()):
        for col in service.exported_columns(table):
            if service.SECRET_NAME.search(col.name):
                assert (table.name, col.name) in service.SAFE_LOOKING_SECRET, (
                    f"{table.name}.{col.name} looks secret: drop it (EXCLUDED_COLUMNS) or declare it safe"
                )


def test_classification_names_only_real_tables_and_columns(db):
    meta = MetaData()
    meta.reflect(bind=db.connection())
    tables = meta.tables
    for name in [*service.EXCLUDED_TABLES, *service.NON_TENANT_TABLES]:
        assert name in tables, f"stale entry {name}"
    for table, column in [*service.EXCLUDED_COLUMNS, *service.SAFE_LOOKING_SECRET]:
        assert column in tables[table].c, f"stale entry {table}.{column}"


# --- the download itself --------------------------------------------------------------------------


def test_admin_download_holds_own_rows_and_never_the_neighbours(db, two_orgs):
    org_a, client_a, org_b = two_orgs
    mine = f"Juniper-{uuid4().hex[:8]}"
    theirs = f"Hostile-{uuid4().hex[:8]}"
    _item(db, org_a.id, mine)
    _item(db, org_b.id, theirs)
    neighbour_email = db.query(User).filter(User.org_id == org_b.id).one().email

    zf = _download(client_a)
    names = set(zf.namelist())
    assert {"README.txt", "summary/stock.csv", "summary/batches.csv", "tables/inventory_items.csv"} <= names
    assert {f"tables/{t.name}.csv" for t in service.tenant_tables(db.connection())} <= names
    assert not any(n.startswith(f"tables/{t}.") for t in service.EXCLUDED_TABLES for n in names)

    items = _rows(zf, "tables/inventory_items.csv")
    assert [r["name"] for r in items] == [mine]
    assert {r["org_id"] for r in items} == {str(org_a.id)}
    assert [r["id"] for r in _rows(zf, "tables/organisations.csv")] == [str(org_a.id)]
    stock = _rows(zf, "summary/stock.csv")
    assert [(r["Item"], float(r["Quantity"]), r["Unit"]) for r in stock] == [(mine, 3.0, "kg")]

    everything = _all_text(zf)
    assert theirs not in everything
    assert neighbour_email not in everything
    assert str(org_b.id) not in everything


def test_every_org_scoped_csv_holds_only_this_org(db, two_orgs):
    org_a, client_a, _org_b = two_orgs
    zf = _download(client_a)
    for table in service.tenant_tables(db.connection()):
        if "org_id" not in table.c:
            continue
        for row in _rows(zf, f"tables/{table.name}.csv"):
            assert row["org_id"] == str(org_a.id), table.name


def test_secrets_never_leave(db, two_orgs):
    org_a, client_a, _org_b = two_orgs
    admin = db.query(User).filter(User.org_id == org_a.id).one()
    secret = pyotp.random_base32()
    admin.totp_secret = secret
    db.commit()
    password_hash = admin.password_hash

    zf = _download(client_a)
    users = _rows(zf, "tables/users.csv")
    assert users and set(users[0]) & {"password_hash", "totp_secret", "invite_token_hash"} == set()
    everything = _all_text(zf)
    assert secret not in everything
    assert password_hash not in everything
    for name in service.EXCLUDED_TABLES:
        assert f"tables/{name}.csv" not in zf.namelist()


def test_readme_explains_the_files(db, two_orgs):
    org_a, client_a, _org_b = two_orgs
    readme = _download(client_a).read("README.txt").decode()
    assert f"All records for {org_a.name}" in readme
    assert "tables/inventory_items.csv" in readme
    assert "location_id -> stock_locations.csv" in readme
    assert "Passwords, two-factor secrets" in readme


def test_each_download_is_audit_logged(db, two_orgs):
    org_a, client_a, _org_b = two_orgs
    _download(client_a)
    db.expire_all()
    actions = [
        a.action for a in db.query(AuditLog).filter(AuditLog.org_id == org_a.id, AuditLog.action.like("data_export%"))
    ]
    assert sorted(actions) == ["data_export_completed", "data_export_started"]


def test_staff_and_signed_out_cannot_download(db, flask_app, two_orgs):  # noqa: F811
    org_a, _client_a, _org_b = two_orgs
    email = f"staff_{uuid4()}@example.test"
    UserRepository(db).create_user(
        org_id=org_a.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.MEMBER,
    )
    db.commit()
    staff = _client_for(flask_app, email)
    assert staff.get(URL).status_code == 403
    assert "records-export-download" not in staff.get("/core/settings").get_data(as_text=True)

    anon = flask_app.test_client()
    anon.environ_base["wsgi.url_scheme"] = "https"
    anon.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert anon.get(URL).status_code in (302, 401)


def test_admin_sees_the_download_on_settings(two_orgs):
    _org_a, client_a, _org_b = two_orgs
    page = client_a.get("/core/settings").get_data(as_text=True)
    assert 'id="records-export-download"' in page
    assert 'href="/api/core/export/records.zip"' in page


# --- streaming and limits -------------------------------------------------------------------------


def test_the_zip_is_streamed_in_chunks(db, two_orgs, flask_app):  # noqa: F811
    org_a, _client_a, _org_b = two_orgs
    for i in range(30):
        _item(db, org_a.id, f"Bulk-{i}")
    chunks = [c for c in service.stream_export(db, org_a.id, org_a.name) if c]
    assert len(chunks) > len(service.tenant_tables(db.connection()))  # at least one chunk per table, not one blob
    zf = zipfile.ZipFile(io.BytesIO(b"".join(chunks)))
    assert zf.testzip() is None
    assert len(_rows(zf, "tables/inventory_items.csv")) == 30


def test_a_table_past_the_cap_is_cut_short_and_named(db, two_orgs, monkeypatch):
    org_a, _client_a, _org_b = two_orgs
    for i in range(3):
        _item(db, org_a.id, f"Cap-{i}")
    monkeypatch.setattr(service, "MAX_ROWS_PER_TABLE", 2)
    stats = service.ExportStats()
    zf = zipfile.ZipFile(io.BytesIO(b"".join(service.stream_export(db, org_a.id, org_a.name, stats))))
    assert len(_rows(zf, "tables/inventory_items.csv")) == 2
    assert "inventory_items" in stats.truncated
    assert "Cut short at 2 rows" in zf.read("README.txt").decode()


def test_binary_columns_become_files(db, two_orgs, monkeypatch):
    """Portal documents keep their bytes in the database: they come out as real files."""
    from sqlalchemy import Column, LargeBinary, MetaData, String, Table
    from sqlalchemy.dialects.postgresql import UUID

    org_a, _client_a, _org_b = two_orgs
    meta = MetaData()
    table = Table(
        "data_export_probe",
        meta,
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("org_id", UUID(as_uuid=True), nullable=False),
        Column("title", String(50)),
        Column("content", LargeBinary),
        prefixes=["TEMPORARY"],
    )
    conn = db.connection()
    table.create(conn)
    doc_id = uuid4()
    conn.execute(table.insert(), [{"id": doc_id, "org_id": org_a.id, "title": "COA", "content": b"%PDF-1"}])
    conn.execute(table.insert(), [{"id": uuid4(), "org_id": uuid4(), "title": "theirs", "content": b"NOPE"}])
    monkeypatch.setattr(service, "tenant_tables", lambda _conn: [table])

    zf = zipfile.ZipFile(io.BytesIO(b"".join(service.stream_export(db, org_a.id, org_a.name))))
    rows = _rows(zf, "tables/data_export_probe.csv")
    assert [(r["title"], r["content"]) for r in rows] == [("COA", f"files/data_export_probe/content/{doc_id}")]
    assert zf.read(f"files/data_export_probe/content/{doc_id}") == b"%PDF-1"
    assert not any(b"NOPE" in zf.read(n) for n in zf.namelist())
    db.rollback()


def test_spreadsheet_formulas_are_neutralised():
    assert service._cell('=HYPERLINK("https://attacker.invalid","open")').startswith("'=")
    for lead in ("+1", "-x", "@SUM(A1)", "\tx", "\rx"):
        assert service._cell(lead) == "'" + lead
    assert service._cell("Juniper") == "Juniper"
    # Numbers are data, not text: a negative quantity stays a number.
    from decimal import Decimal

    assert service._cell(Decimal("-3.5")) == "-3.5"
    assert service._cell(-2) == "-2"


def test_the_download_limit_holds_across_workers(db, two_orgs, monkeypatch):
    """The count comes from the audit log, so a second worker (fresh limiter memory) still refuses."""
    from datetime import timedelta

    from app.features.data_export import routes

    org_a, client_a, _org_b = two_orgs
    monkeypatch.setattr(routes, "DOWNLOAD_LIMITS", ((timedelta(hours=1), 2),))
    assert client_a.get(URL).status_code == 200
    assert client_a.get(URL).status_code == 200
    routes.limiter.reset()  # what a different worker's in-memory limiter looks like
    refused = client_a.get(URL)
    assert refused.status_code == 429
    assert refused.get_json()["code"] == "rate_limited"


def test_two_workers_racing_for_the_last_download_get_one_slot(db, two_orgs, monkeypatch):
    """Each thread is its own worker with its own session; the advisory lock lets one through."""
    import threading
    import time
    from datetime import timedelta

    from app.core.db import SessionLocal
    from app.features.data_export import routes

    org_a, _client_a, _org_b = two_orgs
    user_id = db.query(User).filter(User.org_id == org_a.id).one().id
    monkeypatch.setattr(routes, "DOWNLOAD_LIMITS", ((timedelta(hours=1), 1),))
    barrier = threading.Barrier(2)
    results = []

    def worker():
        session = SessionLocal()
        add = session.add

        def slow_add(obj):  # hold each worker between its count and its insert
            time.sleep(0.3)
            add(obj)

        session.add = slow_add
        try:
            barrier.wait()
            results.append(routes.reserve_download(session, org_a.id, user_id))
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [False, True]
    db.expire_all()
    started = db.query(AuditLog).filter(AuditLog.org_id == org_a.id, AuditLog.action == "data_export_started")
    assert started.count() == 1


def test_files_are_read_in_one_query_not_one_per_file(db, two_orgs, monkeypatch):
    from sqlalchemy import Column, LargeBinary, MetaData, String, Table, event
    from sqlalchemy.dialects.postgresql import UUID

    org_a, _client_a, _org_b = two_orgs
    table = Table(
        "data_export_probe2",
        MetaData(),
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("org_id", UUID(as_uuid=True), nullable=False),
        Column("title", String(50)),
        Column("content", LargeBinary),
        prefixes=["TEMPORARY"],
    )
    conn = db.connection()
    table.create(conn)
    conn.execute(
        table.insert(), [{"id": uuid4(), "org_id": org_a.id, "title": f"d{i}", "content": b"x"} for i in range(5)]
    )
    monkeypatch.setattr(service, "tenant_tables", lambda _conn: [table])
    blob_reads = []

    def count(_conn, _cursor, statement, *_rest):
        if "data_export_probe2.content" in statement and "IS NOT NULL" in statement and "SELECT" in statement:
            blob_reads.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        zf = zipfile.ZipFile(io.BytesIO(b"".join(service.stream_export(db, org_a.id, org_a.name))))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    assert len([n for n in zf.namelist() if n.startswith("files/data_export_probe2/content/")]) == 5
    # One CSV-pass query (content IS NOT NULL as a flag) and one file-pass query.
    assert len(blob_reads) == 2, blob_reads
    db.rollback()
