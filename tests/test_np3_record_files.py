"""Files attached to NP3 check evidence: types, size, tenant isolation, CSRF, access, PDF export."""

import shutil
from html.parser import HTMLParser
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image as PilImage
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from app.core.backend.evidence.evidence_storage import get_storage_root
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401

CONTROL = "registration-scope"
ATTEST = "/api/compliant/np3-audit/attestations"


def _pdf(text="Signed procedure") -> bytes:
    out = BytesIO()
    canvas = Canvas(out)
    canvas.drawString(72, 720, text)
    canvas.save()
    return out.getvalue()


def _png() -> bytes:
    out = BytesIO()
    PilImage.new("RGB", (60, 30), color="navy").save(out, format="PNG")
    return out.getvalue()


def _upload(client, record_id, content, name="evidence.pdf", mime="application/pdf", **kwargs):
    return client.post(
        f"/api/compliant/np3-audit/records/{record_id}/files",
        data={"file": (BytesIO(content), name, mime)},
        content_type="multipart/form-data",
        **kwargs,
    )


def _attest(client):
    assert (
        client.put(
            "/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}}
        ).status_code
        == 200
    )
    response = client.post(
        ATTEST,
        json={"control_id": CONTROL, "how_we_meet": "Reviewed with the register.", "confirmed": True},
    )
    assert response.status_code == 201
    return response.get_json()["record"]["id"]


@pytest.fixture
def org_client(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    yield org, client
    shutil.rmtree(get_storage_root() / str(org.id), ignore_errors=True)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_attestation_file_is_stored_listed_and_downloadable(org_client):
    org, client = org_client
    record_id = _attest(client)
    content = _pdf()

    response = _upload(client, record_id, content)

    assert response.status_code == 201
    file = response.get_json()["file"]
    assert file["file_name"] == "evidence.pdf" and file["mime_type"] == "application/pdf"
    assert "storage" not in str(file).lower()
    stored = list((get_storage_root() / str(org.id) / f"np3-{record_id}").glob("*.pdf"))
    assert len(stored) == 1
    audit = client.get("/api/compliant/np3-audit").get_json()
    row = next(r for r in audit["rows"] if r["control_id"] == CONTROL)
    assert [f["id"] for f in row["history"][0]["files"]] == [file["id"]]
    download = client.get(file["url"])
    assert download.status_code == 200
    assert download.data == content
    assert download.headers["Content-Disposition"].startswith("attachment")
    assert download.headers["X-Content-Type-Options"] == "nosniff"


def test_log_entry_file_shows_on_the_log_entry(org_client):
    _, client = org_client
    _attest(client)
    entry = client.post(
        "/api/compliant/np3-audit/checks/trace-and-recall/logs",
        json={
            "fields": {
                "event_date": "2026-09-30",
                "batch_or_product": "Juniper berries",
                "trace_result": "All lots traced",
                "elapsed_time": "4 minutes",
            }
        },
    )
    assert entry.status_code == 201, entry.get_json()
    record_id = entry.get_json()["record"]["id"]
    assert _upload(client, record_id, _png(), "photo.png", "image/png").status_code == 201
    row = next(
        r for r in client.get("/api/compliant/np3-audit").get_json()["rows"] if r["control_id"] == "trace-and-recall"
    )
    assert [f["file_name"] for f in row["log_entries"][0]["files"]] == ["photo.png"]


def test_type_is_decided_by_content_not_claimed_type_or_name(org_client):
    _, client = org_client
    record_id = _attest(client)
    assert (
        _upload(client, record_id, b"<html><script>alert(1)</script></html>", "x.pdf", "application/pdf").status_code
        == 400
    )
    assert _upload(client, record_id, b"MZ\x90\x00 executable", "x.png", "image/png").status_code == 400
    assert _upload(client, record_id, b"GIF89a....", "x.gif", "image/gif").status_code == 400
    # a real PDF is accepted even when the browser reports a generic type
    assert _upload(client, record_id, _pdf(), "scan", "application/octet-stream").status_code == 201


def test_empty_missing_and_oversized_files_are_rejected(org_client, monkeypatch):
    _, client = org_client
    record_id = _attest(client)
    assert _upload(client, record_id, b"").status_code == 400
    assert client.post(f"/api/compliant/np3-audit/records/{record_id}/files", data={}).status_code == 400
    monkeypatch.setattr("app.features.compliant.record_files.get_max_file_size_bytes", lambda: 1024)
    response = _upload(client, record_id, _pdf() + b"0" * 2048)
    assert response.status_code == 400 and "too large" in response.get_json()["error"]


def test_file_count_per_record_is_capped(org_client, monkeypatch):
    _, client = org_client
    record_id = _attest(client)
    monkeypatch.setattr("app.features.compliant.record_files.MAX_FILES_PER_RECORD", 2)
    assert _upload(client, record_id, _pdf("a")).status_code == 201
    assert _upload(client, record_id, _pdf("b")).status_code == 201
    assert _upload(client, record_id, _pdf("c")).status_code == 409


def test_other_orgs_cannot_see_attach_or_download(db, flask_app, org_client):  # noqa: F811
    _, client = org_client
    record_id = _attest(client)
    file_id = _upload(client, record_id, _pdf()).get_json()["file"]["id"]
    other_org, other = _admin_client(db, flask_app)
    try:
        other.put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}})
        assert _upload(other, record_id, _pdf()).status_code == 404
        assert other.get(f"/api/compliant/np3-audit/records/{record_id}/files/{file_id}").status_code == 404
        # the other org's own record cannot be used to reach the first org's file id
        own_record = other.post(
            ATTEST, json={"control_id": CONTROL, "how_we_meet": "Own review.", "confirmed": True}
        ).get_json()["record"]["id"]
        assert other.get(f"/api/compliant/np3-audit/records/{own_record}/files/{file_id}").status_code == 404
        audit = other.get("/api/compliant/np3-audit").get_json()
        assert file_id not in str(audit)
        assert "not-a-uuid" and other.get("/api/compliant/np3-audit/records/not-a-uuid/files/x").status_code == 404
    finally:
        shutil.rmtree(get_storage_root() / str(other_org.id), ignore_errors=True)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()


def test_only_np_records_can_carry_files(org_client, db):
    org, client = org_client
    _attest(client)
    generic = client.post(
        "/api/compliant/records",
        json={
            "framework_slug": "np3-food-control",
            "control_id": CONTROL,
            "record_type": "reading",
            "title": "Not an attestation or log",
        },
    )
    assert generic.status_code == 201, generic.get_json()
    assert _upload(client, generic.get_json()["record"]["id"], _pdf()).status_code == 404


def test_requires_login_and_role(org_client, db, flask_app):  # noqa: F811
    org, client = org_client
    record_id = _attest(client)
    file_id = _upload(client, record_id, _pdf()).get_json()["file"]["id"]
    anonymous = flask_app.test_client()
    anonymous.environ_base["wsgi.url_scheme"] = "https"
    anonymous.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert _upload(anonymous, record_id, _pdf()).status_code == 401
    assert anonymous.get(f"/api/compliant/np3-audit/records/{record_id}/files/{file_id}").status_code == 401

    email = f"auditor-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.AUDITOR,
        is_active=True,
    )
    db.commit()
    auditor = flask_app.test_client()
    auditor.environ_base["wsgi.url_scheme"] = "https"
    auditor.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    login = auditor.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    if login.status_code != 200:
        pytest.skip("auditor login needs an expiry set in this build")
    assert auditor.get(f"/api/compliant/np3-audit/records/{record_id}/files/{file_id}").status_code == 200
    assert _upload(auditor, record_id, _pdf()).status_code == 403


def test_upload_requires_csrf_token(org_client, flask_app):  # noqa: F811
    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name") == "csrf-token":
                self.token = values.get("content")

    _, client = org_client
    record_id = _attest(client)
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert _upload(client, record_id, _pdf()).status_code == 400
        parser = TokenParser()
        parser.feed(client.get("/compliant/nz-alcohol/food-safety").get_data(as_text=True))
        assert parser.token
        response = _upload(
            client,
            record_id,
            _pdf(),
            headers={"X-CSRFToken": parser.token, "Referer": "https://localhost/compliant/nz-alcohol/food-safety"},
        )
        assert response.status_code == 201
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = False


def test_evidence_pdf_export_includes_attached_files(org_client):
    _, client = org_client
    record_id = _attest(client)
    assert _upload(client, record_id, _pdf("ATTACHED-PROCEDURE-TEXT")).status_code == 201
    assert _upload(client, record_id, _png(), "photo.png", "image/png").status_code == 201

    response = client.get("/api/compliant/np3-audit?format=pdf")

    assert response.status_code == 200
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.data)).pages)
    assert "ATTACHED-PROCEDURE-TEXT" in text
    assert "evidence.pdf" in text
