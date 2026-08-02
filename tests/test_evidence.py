"""Tests for the execution evidence upload/download/delete API.

Scope: app/core/backend/evidence/*.py, ExecutionEvidence model. No test file existed
for this surface before this audit (see .agents/feature-index.md "execution" slice,
"Known coverage gaps" — flagged for a broader test-author sweep); this covers the
uploaded_by regression found and fixed during review.
"""

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

import app.core.backend.evidence.evidence_service as evidence_service_module
import app.core.backend.evidence.evidence_validation as evidence_validation_module
from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.execution_evidence import ExecutionEvidence
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.step import Step
from app.core.db.repositories.evidence_repo import EvidenceRepository
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.utils.config_loader import config
from tests.factories import DEFAULT_TEST_PASSWORD, ExecutionFactory, ProcessFactory

# Smallest possible valid-looking PNG: magic bytes only, matches _MAGIC detection
# in evidence_validation.detect_mime_from_path — content after the header is never
# parsed as a real image by this code path.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _storage_files(org_id, execution_id) -> list[Path]:
    """List files persisted for an org/execution, for orphan-cleanup assertions."""
    storage_root = Path(config.evidence_storage_root or "app/core/evidence_storage")
    d = storage_root / str(org_id) / str(execution_id)
    return list(d.glob("*")) if d.exists() else []


@contextmanager
def _authenticated_client(email: str, password: str = DEFAULT_TEST_PASSWORD):
    """A fresh, logged-in Flask test client for a given user — for tests that need two
    independently-authenticated clients (one per org) in the same test body."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": email, "password": password},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed for {email}: {resp.data}"
            yield client


@pytest.fixture
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture
def org_process_execution(db):
    """Org + one-step process + an execution, ready to accept evidence for its single step."""
    org_repo = OrganisationRepository(db)
    process_repo = ProcessRepository(db)
    exec_repo = ExecutionRepository(db)

    org = org_repo.create_org(f"Evidence Test Org {uuid4()}")
    password_hash = AuthService.hash_password("TestPass123!")
    user_repo = UserRepository(db)
    user = user_repo.create_user(org_id=org.id, email=f"evidence_{uuid4()}@test.com", password_hash=password_hash)
    process = process_repo.create_process(org_id=org.id, name="Evidence Process", description="", is_draft=False)
    process_repo.add_step(
        process_id=process.id,
        org_id=org.id,
        step_number=1,
        position=1000,
        name="Step 1",
        inputs=[],
        outputs=[{"name": "Out1", "quantity": 1, "unit": "kg"}],
    )
    execution = exec_repo.create_execution(org_id=org.id, process_id=process.id)
    db.commit()
    data = {"org": org, "user": user, "process": process, "execution": execution}
    try:
        yield data
    finally:
        import shutil

        from app.utils.config_loader import config

        storage_root = config.evidence_storage_root or "app/core/evidence_storage"
        shutil.rmtree(Path(storage_root) / str(org.id), ignore_errors=True)
        db.query(ExecutionEvidence).filter(ExecutionEvidence.org_id == org.id).delete(synchronize_session=False)
        db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution.id).delete(synchronize_session=False)
        db.query(Execution).filter(Execution.id == execution.id).delete(synchronize_session=False)
        db.query(Step).filter(Step.process_id == process.id).delete(synchronize_session=False)
        db.query(Process).filter(Process.id == process.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def app_client(db, org_process_execution):
    """Authenticated Flask test client scoped to the fixture's org."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": org_process_execution["user"].email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


@pytest.fixture
def two_org_evidence(db, two_org_two_user):
    """Two orgs, each with a process + execution, for evidence tenant-isolation tests."""
    org_a = two_org_two_user["org_a"]
    org_b = two_org_two_user["org_b"]
    user_a = two_org_two_user["user_a"]
    user_b = two_org_two_user["user_b"]

    process_a = ProcessFactory(org_id=org_a.id)
    process_b = ProcessFactory(org_id=org_b.id)
    execution_a = ExecutionFactory(org_id=org_a.id, process_id=process_a.id)
    execution_b = ExecutionFactory(org_id=org_b.id, process_id=process_b.id)
    db.commit()

    data = {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "execution_a": execution_a,
        "execution_b": execution_b,
    }
    try:
        yield data
    finally:
        import shutil

        from app.core.db.models.audit_log import AuditLog

        storage_root = config.evidence_storage_root or "app/core/evidence_storage"
        for org in (org_a, org_b):
            shutil.rmtree(Path(storage_root) / str(org.id), ignore_errors=True)
        db.rollback()
        # Evidence upload/delete routes call log_action, which writes audit_logs rows
        # FK'd to users.id -- two_org_two_user's teardown deletes those users next, so
        # they must go first or the user DELETE fails with a FK violation.
        db.query(AuditLog).filter(AuditLog.org_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.query(ExecutionEvidence).filter(ExecutionEvidence.org_id.in_([org_a.id, org_b.id])).delete(
            synchronize_session=False
        )
        db.query(Execution).filter(Execution.id.in_([execution_a.id, execution_b.id])).delete(
            synchronize_session=False
        )
        db.query(Process).filter(Process.id.in_([process_a.id, process_b.id])).delete(synchronize_session=False)
        db.commit()


class TestEvidenceUploadRecordsUploader:
    """Regression: uploaded_by must be persisted from the authenticated session's email.

    Previously `getattr(g, "user_email", None) or getattr(g, "user", {}).get("email")
    if hasattr(g, "user") else None` silently evaluated to None on every upload — the
    ternary binds looser than `or`, so it reduced to `(... or ...) if hasattr(g, "user")
    else None`, and `g.user` is never set anywhere in this codebase (only g.user_email /
    g.user_id / g.current_user are), so the condition was always False.
    """

    def test_uploaded_by_is_persisted_from_session_email(self, db, org_process_execution):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        user = org_process_execution["user"]
        execution = org_process_execution["execution"]

        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            with flask_app.app_context():
                login_resp = client.post(
                    "/auth/login",
                    json={"email": user.email, "password": "TestPass123!"},
                    content_type="application/json",
                )
                assert login_resp.status_code in (200, 201), f"Login failed: {login_resp.data}"

                resp = client.post(
                    "/api/core/evidence/upload",
                    data={
                        "execution_id": str(execution.id),
                        "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png"),
                    },
                    content_type="multipart/form-data",
                )

        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        evidence_id = body["id"]

        record = db.query(ExecutionEvidence).filter(ExecutionEvidence.id == evidence_id).first()
        assert record is not None
        assert record.uploaded_by == user.email, (
            f"expected uploaded_by={user.email!r}, got {record.uploaded_by!r} "
            "(uploaded_by should never be None when the session has a user_email)"
        )


class TestEvidenceUploadValidatesStepId:
    """Regression: step_id must belong to the execution's own process.

    ExecutionEvidence.step_id is a FK to the global steps table with no org scoping of
    its own; evidence_service previously stored whatever UUID-shaped step_id the client
    sent without checking it was one of this execution's actual steps. Not a demonstrated
    cross-tenant read today (nothing joins evidence.step_id back to Step to render foreign
    data), but a data-integrity gap in the same FK shape InventoryRepository already
    guards for provenance references — flagged by security-audit, fixed by validating
    step_id against execution.execution_steps before persisting.
    """

    def test_step_id_not_belonging_to_execution_is_rejected(self, app_client, db, org_process_execution):
        foreign_step_id = str(uuid4())
        execution = org_process_execution["execution"]

        resp = app_client.post(
            "/api/core/evidence/upload",
            data={
                "execution_id": str(execution.id),
                "step_id": foreign_step_id,
                "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert db.query(ExecutionEvidence).filter(ExecutionEvidence.execution_id == execution.id).count() == 0

    def test_step_id_belonging_to_execution_is_accepted(self, app_client, db, org_process_execution):
        execution = org_process_execution["execution"]
        real_step = db.query(Step).filter(Step.process_id == org_process_execution["process"].id).one()

        resp = app_client.post(
            "/api/core/evidence/upload",
            data={
                "execution_id": str(execution.id),
                "step_id": str(real_step.id),
                "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)


class TestEvidenceConfig:
    def test_config_returns_size_limit_and_allowed_types(self, app_client):
        resp = app_client.get("/api/core/evidence/config")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["max_file_size_bytes"] == config.evidence_max_file_size_mb * 1024 * 1024
        assert body["allowed_mime_types"] == config.evidence_allowed_mime_types


class TestEvidenceList:
    def test_list_returns_uploaded_evidence(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        upload_resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)
        evidence_id = upload_resp.get_json()["id"]

        resp = app_client.get(f"/api/core/evidence/list?execution_id={execution.id}")
        assert resp.status_code == 200
        items = resp.get_json()["evidence"]
        assert [item["id"] for item in items] == [evidence_id]

    def test_list_is_empty_for_execution_with_no_evidence(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        resp = app_client.get(f"/api/core/evidence/list?execution_id={execution.id}")
        assert resp.status_code == 200
        assert resp.get_json()["evidence"] == []

    def test_list_missing_execution_id_is_rejected(self, app_client):
        resp = app_client.get("/api/core/evidence/list")
        assert resp.status_code == 400

    def test_list_invalid_execution_id_format_is_rejected(self, app_client):
        resp = app_client.get("/api/core/evidence/list?execution_id=not-a-uuid")
        assert resp.status_code == 400

    def test_list_is_org_scoped(self, two_org_evidence):
        """Org B listing org A's execution_id must not see org A's evidence — list_evidence_for_execution
        filters by org_id, so a request for another org's execution_id returns empty rather than
        that org's records (no execution-ownership check is even needed for this to hold)."""
        execution_a = two_org_evidence["execution_a"]
        user_a = two_org_evidence["user_a"]
        user_b = two_org_evidence["user_b"]

        with _authenticated_client(user_a.email) as client_a:
            upload_resp = client_a.post(
                "/api/core/evidence/upload",
                data={"execution_id": str(execution_a.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
                content_type="multipart/form-data",
            )
            assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)

        with _authenticated_client(user_b.email) as client_b:
            resp = client_b.get(f"/api/core/evidence/list?execution_id={execution_a.id}")
            assert resp.status_code == 200
            assert resp.get_json()["evidence"] == [], "org B must not see org A's evidence"


class TestEvidenceDownload:
    def test_download_returns_uploaded_bytes(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        upload_resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)
        evidence_id = upload_resp.get_json()["id"]

        resp = app_client.get(f"/api/core/evidence/{evidence_id}/download")
        assert resp.status_code == 200
        assert resp.data == _PNG_BYTES
        assert resp.mimetype == "image/png"

    def test_download_nonexistent_id_is_404(self, app_client):
        resp = app_client.get(f"/api/core/evidence/{uuid4()}/download")
        assert resp.status_code == 404

    def test_download_cross_org_is_404(self, two_org_evidence):
        execution_a = two_org_evidence["execution_a"]
        user_a = two_org_evidence["user_a"]
        user_b = two_org_evidence["user_b"]

        with _authenticated_client(user_a.email) as client_a:
            upload_resp = client_a.post(
                "/api/core/evidence/upload",
                data={"execution_id": str(execution_a.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
                content_type="multipart/form-data",
            )
            assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)
            evidence_id = upload_resp.get_json()["id"]

        with _authenticated_client(user_b.email) as client_b:
            resp = client_b.get(f"/api/core/evidence/{evidence_id}/download")
            assert resp.status_code == 404


class TestEvidenceDelete:
    def test_delete_success_removes_record_and_file(self, app_client, db, org_process_execution):
        execution = org_process_execution["execution"]
        upload_resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)
        evidence_id = upload_resp.get_json()["id"]
        assert _storage_files(execution.org_id, execution.id) != []

        resp = app_client.delete(f"/api/core/evidence/{evidence_id}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True
        assert db.query(ExecutionEvidence).filter(ExecutionEvidence.id == evidence_id).first() is None
        assert _storage_files(execution.org_id, execution.id) == []

    def test_delete_is_idempotent_on_missing(self, app_client):
        missing_id = str(uuid4())
        resp = app_client.delete(f"/api/core/evidence/{missing_id}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True

        # A second delete of the SAME (never-existing) id must behave identically —
        # this is the actual idempotency claim; two different random ids would each
        # independently hit "missing" without ever proving a repeat delete is safe.
        resp2 = app_client.delete(f"/api/core/evidence/{missing_id}")
        assert resp2.status_code == 200
        assert resp2.get_json()["deleted"] is True

    def test_delete_cross_org_does_not_remove_the_record(self, db, two_org_evidence):
        """DELETE has no separate cross-org branch: evidence_service.delete_evidence treats
        'not found in this org' as the same idempotent-success path as 'genuinely missing'
        (get_by_id is org-filtered, so org B's lookup simply misses). That means org B's
        attempt returns 200, not the 404 AC17 states for this route — flagged as a spec/code
        mismatch in the test-author report. What actually matters for tenant isolation is
        exercised here: org A's record must survive untouched."""
        execution_a = two_org_evidence["execution_a"]
        user_a = two_org_evidence["user_a"]
        user_b = two_org_evidence["user_b"]

        with _authenticated_client(user_a.email) as client_a:
            upload_resp = client_a.post(
                "/api/core/evidence/upload",
                data={"execution_id": str(execution_a.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
                content_type="multipart/form-data",
            )
            assert upload_resp.status_code == 201, upload_resp.get_data(as_text=True)
            evidence_id = upload_resp.get_json()["id"]

        with _authenticated_client(user_b.email) as client_b:
            resp = client_b.delete(f"/api/core/evidence/{evidence_id}")
            assert resp.status_code == 200

        record = db.query(ExecutionEvidence).filter(ExecutionEvidence.id == evidence_id).first()
        assert record is not None, "org B's delete attempt must not remove org A's evidence record"


class TestEvidenceUploadValidation:
    def test_oversized_file_is_rejected(self, app_client, org_process_execution, monkeypatch):
        monkeypatch.setattr(evidence_validation_module, "get_max_file_size_bytes", lambda: 10)
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "too large" in resp.get_json()["error"].lower()

    def test_empty_file_is_rejected(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(b""), "empty.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "empty" in resp.get_json()["error"].lower()

    def test_disallowed_mime_type_is_rejected(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={
                "execution_id": str(execution.id),
                "file": (BytesIO(b"plain text, no magic bytes here"), "notes.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.get_json()["error"].lower()

    def test_mime_sniffing_overrides_a_lying_client_content_type(self, app_client, org_process_execution):
        """AC14: 'the client-declared Content-Type is only a fallback, never trusted alone'.
        Real PNG magic bytes with a disallowed declared Content-Type must still be sniffed
        as image/png and accepted — proving the server classifies from bytes, not the header,
        whenever sniffing succeeds."""
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={
                "execution_id": str(execution.id),
                "file": (BytesIO(_PNG_BYTES), "proof.dat", "application/octet-stream"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert resp.get_json()["mime_type"] == "image/png"

    def test_missing_file_in_request_is_rejected(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id)},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "no file" in resp.get_json()["error"].lower()

    def test_invalid_execution_id_format_is_rejected(self, app_client):
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": "not-a-uuid", "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "execution_id" in resp.get_json()["error"].lower()

    def test_invalid_step_id_format_is_rejected(self, app_client, org_process_execution):
        execution = org_process_execution["execution"]
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={
                "execution_id": str(execution.id),
                "step_id": "not-a-uuid",
                "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "step_id" in resp.get_json()["error"].lower()

    def test_execution_not_found_is_rejected(self, app_client):
        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(uuid4()), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()


class TestEvidenceUploadFailureCleanup:
    """Every failure branch inside upload_evidence_from_temp after the DB commit must leave
    no orphan: no ExecutionEvidence row and no file on disk. Each test forces a specific
    stage to fail via monkeypatch and asserts both are gone."""

    def test_checksum_verification_failure_leaves_no_orphan(self, app_client, db, org_process_execution, monkeypatch):
        monkeypatch.setattr(evidence_service_module, "verify_checksum_at_path", lambda *a, **kw: False)
        execution = org_process_execution["execution"]

        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 500
        assert "verification failed" in resp.get_json()["error"].lower()
        assert db.query(ExecutionEvidence).filter(ExecutionEvidence.execution_id == execution.id).count() == 0
        assert _storage_files(execution.org_id, execution.id) == []

    def test_finalize_from_temp_failure_leaves_no_orphan_record(
        self, app_client, db, org_process_execution, monkeypatch
    ):
        captured_temp_path = {}

        def _boom(temp_path, *a, **kw):
            # finalize_from_temp's own job is moving the temp file into final storage;
            # capture what it was called with so we can assert the *temp* file (not
            # just the never-populated final storage dir) is actually cleaned up.
            captured_temp_path["path"] = temp_path
            raise OSError("simulated move failure")

        monkeypatch.setattr(evidence_service_module, "finalize_from_temp", _boom)
        execution = org_process_execution["execution"]

        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 500
        assert "finalize" in resp.get_json()["error"].lower()
        assert db.query(ExecutionEvidence).filter(ExecutionEvidence.execution_id == execution.id).count() == 0
        assert _storage_files(execution.org_id, execution.id) == []
        assert captured_temp_path.get("path") is not None
        assert not captured_temp_path["path"].exists(), (
            f"temp upload file {captured_temp_path['path']} should have been deleted on finalize failure"
        )

    def test_activate_failure_deletes_record_and_finalized_file(
        self, app_client, db, org_process_execution, monkeypatch
    ):
        def _boom(self, *a, **kw):
            raise Exception("simulated activate failure")

        monkeypatch.setattr(EvidenceRepository, "update_status", _boom)
        execution = org_process_execution["execution"]

        resp = app_client.post(
            "/api/core/evidence/upload",
            data={"execution_id": str(execution.id), "file": (BytesIO(_PNG_BYTES), "proof.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 500
        assert "activate" in resp.get_json()["error"].lower()
        assert db.query(ExecutionEvidence).filter(ExecutionEvidence.execution_id == execution.id).count() == 0
        assert _storage_files(execution.org_id, execution.id) == []


class TestEvidenceStorageHelpers:
    def test_is_safe_filename_accepts_uuid_and_allowed_extensions(self):
        from app.core.backend.evidence.evidence_storage import is_safe_filename

        assert is_safe_filename(f"{uuid4()}.png") is True
        assert is_safe_filename(f"{uuid4()}.pdf") is True
        assert is_safe_filename(f"{uuid4()}.jpeg") is True

    def test_is_safe_filename_rejects_path_traversal(self):
        from app.core.backend.evidence.evidence_storage import is_safe_filename

        assert is_safe_filename("../../etc/passwd") is False
        assert is_safe_filename(f"../{uuid4()}.png") is False
        assert is_safe_filename(f"{uuid4()}\\evil.png") is False

    def test_is_safe_filename_rejects_non_uuid_or_disallowed_extension(self):
        from app.core.backend.evidence.evidence_storage import is_safe_filename

        assert is_safe_filename("evidence.png") is False
        assert is_safe_filename(f"{uuid4()}.exe") is False
        assert is_safe_filename("") is False

    def test_extension_from_mime_maps_known_types(self):
        from app.core.backend.evidence.evidence_storage import extension_from_mime

        assert extension_from_mime("image/png") == ".png"
        assert extension_from_mime("image/jpeg") == ".jpg"
        assert extension_from_mime("image/jpg") == ".jpg"
        assert extension_from_mime("application/pdf") == ".pdf"
        assert extension_from_mime("application/zip") == ".bin"

    def test_compute_checksum_and_verify_roundtrip(self, tmp_path):
        from app.core.backend.evidence.evidence_storage import compute_checksum, verify_checksum_at_path

        p = tmp_path / "f.bin"
        p.write_bytes(_PNG_BYTES)
        checksum = compute_checksum(p)
        assert verify_checksum_at_path(p, checksum) is True

        p.write_bytes(_PNG_BYTES + b"tampered")
        assert verify_checksum_at_path(p, checksum) is False

    def test_finalize_from_temp_rejects_unsafe_filename(self, tmp_path):
        from app.core.backend.evidence.evidence_storage import finalize_from_temp

        temp = tmp_path / "temp.bin"
        temp.write_bytes(_PNG_BYTES)
        with pytest.raises(ValueError):
            finalize_from_temp(temp, "org1", "exec1", "../evil.png")

    def test_finalize_from_temp_raises_if_temp_file_missing(self, tmp_path, monkeypatch):
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        missing = tmp_path / "missing.bin"
        with pytest.raises(FileNotFoundError):
            storage.finalize_from_temp(missing, "org1", "exec1", f"{uuid4()}.png")

    def test_finalize_from_temp_moves_file_to_final_path(self, tmp_path, monkeypatch):
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        temp = tmp_path / "temp_src.bin"
        temp.write_bytes(_PNG_BYTES)
        filename = f"{uuid4()}.png"

        final_path = storage.finalize_from_temp(temp, "org1", "exec1", filename)

        assert not temp.exists()
        assert final_path.exists()
        assert final_path.read_bytes() == _PNG_BYTES

    def test_read_file_path_rejects_traversal_outside_storage_root(self, tmp_path, monkeypatch):
        """org_id/execution_id are UUID strings in production, but the path-join itself
        offers no protection — the root-containment check (`relative_to`) is what actually
        stops a traversal, so prove it holds even if a caller ever passed a hostile segment.

        A file must genuinely exist at the traversal target: read_file_path's first check
        is `candidate.is_file()`, which returns False (and short-circuits before the
        containment check ever runs) for a target that's merely absent — that would make
        this test pass for the wrong reason regardless of whether relative_to() works.
        """
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        filename = f"{uuid4()}.png"
        # tmp_path/org1/../../outside resolves to tmp_path.parent/outside — a real file
        # planted there so is_file() is True and the relative_to() guard is what's tested.
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / filename
        try:
            outside_file.write_bytes(_PNG_BYTES)
            assert storage.read_file_path("org1", "../../outside", filename) is None
        finally:
            outside_file.unlink(missing_ok=True)
            try:
                outside_dir.rmdir()
            except OSError:
                pass

    def test_read_file_path_returns_none_for_missing_file(self, tmp_path, monkeypatch):
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        assert storage.read_file_path("org1", "exec1", f"{uuid4()}.png") is None

    def test_delete_file_is_idempotent_when_missing(self, tmp_path, monkeypatch):
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        assert storage.delete_file("org1", "exec1", f"{uuid4()}.png") is True

    def test_delete_file_removes_existing_file(self, tmp_path, monkeypatch):
        import app.core.backend.evidence.evidence_storage as storage

        monkeypatch.setattr(storage, "get_storage_root", lambda: tmp_path)
        filename = f"{uuid4()}.png"
        dest_dir = tmp_path / "org1" / "exec1"
        dest_dir.mkdir(parents=True)
        (dest_dir / filename).write_bytes(_PNG_BYTES)

        assert storage.delete_file("org1", "exec1", filename) is True
        assert not (dest_dir / filename).exists()


class TestEvidenceValidationHelpers:
    def test_detect_mime_from_path_identifies_known_magic_bytes(self, tmp_path):
        from app.core.backend.evidence.evidence_validation import detect_mime_from_path

        png = tmp_path / "a.png"
        png.write_bytes(_PNG_BYTES)
        assert detect_mime_from_path(png) == "image/png"

        jpeg = tmp_path / "a.jpg"
        jpeg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
        assert detect_mime_from_path(jpeg) == "image/jpeg"

        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4" + b"\x00" * 16)
        assert detect_mime_from_path(pdf) == "application/pdf"

    def test_detect_mime_from_path_returns_none_for_unknown_bytes(self, tmp_path):
        from app.core.backend.evidence.evidence_validation import detect_mime_from_path

        unknown = tmp_path / "a.txt"
        unknown.write_bytes(b"not a recognised file signature")
        assert detect_mime_from_path(unknown) is None

    def test_validate_upload_request_requires_execution_id(self):
        from app.core.backend.evidence.evidence_validation import validate_upload_request

        ok, err = validate_upload_request(uuid4(), "", None)
        assert ok is False
        assert "execution_id" in err.lower()

    def test_validate_upload_request_rejects_malformed_execution_id(self):
        from app.core.backend.evidence.evidence_validation import validate_upload_request

        ok, err = validate_upload_request(uuid4(), "not-a-uuid", None)
        assert ok is False
        assert "execution_id" in err.lower()

    def test_validate_upload_request_rejects_malformed_step_id(self):
        from app.core.backend.evidence.evidence_validation import validate_upload_request

        ok, err = validate_upload_request(uuid4(), str(uuid4()), "not-a-uuid")
        assert ok is False
        assert "step_id" in err.lower()

    def test_validate_upload_request_accepts_valid_ids(self):
        from app.core.backend.evidence.evidence_validation import validate_upload_request

        ok, err = validate_upload_request(uuid4(), str(uuid4()), str(uuid4()))
        assert ok is True
        assert err == ""

    def test_validate_upload_request_accepts_missing_step_id(self):
        from app.core.backend.evidence.evidence_validation import validate_upload_request

        ok, _err = validate_upload_request(uuid4(), str(uuid4()), None)
        assert ok is True
