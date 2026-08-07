"""Process docs / SOPs: upload, inline, list, download, delete (AC14-AC20).

.agents/specs/process-design.md flagged this as a confirmed zero-coverage gap: no test,
unit or e2e, touched upload/inline/download/delete before this file. Driven through the
real browser session so auth, CSRF, org filtering, and the multipart upload path are all
exercised together — the way a browser actually submits these forms.

Cross-tenant probes mirror test_tenant_isolation.py's pattern: org B must never read,
download, or delete org A's process docs. Download and delete 404 (object-level lookup
scoped by the document's own org_id); list is scoped the same way but has no per-id
lookup to 404 on, so a cross-org step_id just resolves to an empty list — the assertion
here is "no leak", not a specific status code (see process_docs_service.list_docs_for_step,
which filters directly on ProcessStepDocument.org_id, never through the step's process).
"""

import uuid

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import csrf_headers, login_through_ui

pytestmark = pytest.mark.e2e

# Mirrors app/config/local.ini [process_docs]: max 20MB, pdf/doc/docx/md/txt only.
_MAX_BYTES = 20 * 1024 * 1024


def _create_process_with_step(page, name: str) -> tuple[str, str]:
    proc = page.request.post(
        "/api/core/processes",
        headers=csrf_headers(page),
        data={"name": name, "category": "manufacturing"},
    )
    assert proc.status == 201, f"process setup failed: {proc.status} {proc.text()}"
    pid = proc.json()["id"]

    step = page.request.post(
        f"/api/core/processes/{pid}/steps",
        headers=csrf_headers(page),
        data={"step_number": 1, "name": "Mix"},
    )
    assert step.status == 201, f"step setup failed: {step.status} {step.text()}"
    sid = step.json()["id"]
    return pid, sid


def _upload(
    page, process_id: str, step_id: str, *, filename="sop.txt", mime="text/plain", content=b"Mix well.", title=""
):
    fields = {"process_id": process_id, "step_id": step_id}
    if title:
        fields["title"] = title
    return page.request.post(
        "/api/core/process-docs/upload",
        headers=csrf_headers(page),
        multipart={**fields, "file": {"name": filename, "mimeType": mime, "buffer": content}},
    )


def test_ac14_config_returns_limits_and_allowed_mime_types(logged_in_page: Page):
    page = logged_in_page
    resp = page.request.get("/api/core/process-docs/config")
    assert resp.status == 200, f"config failed: {resp.status} {resp.text()}"
    body = resp.json()
    assert body["max_file_size_bytes"] == _MAX_BYTES
    assert "application/pdf" in body["allowed_mime_types"]
    assert "text/plain" in body["allowed_mime_types"]


def test_ac15_upload_happy_path_is_listed_and_downloadable(logged_in_page: Page):
    """AC15 upload + AC17 list + AC18 download, chained end to end."""
    page = logged_in_page
    title = f"E2E SOP {uuid.uuid4().hex[:8]}"
    pid, sid = _create_process_with_step(page, f"E2E Docs {uuid.uuid4().hex[:8]}")

    uploaded = _upload(page, pid, sid, title=title, content=b"Step-by-step instructions.")
    assert uploaded.status == 201, f"upload failed: {uploaded.status} {uploaded.text()}"
    doc = uploaded.json()
    doc_id = doc["id"]
    assert doc["title"] == title
    assert doc["mime_type"] == "text/plain"

    listing = page.request.get(f"/api/core/process-docs/{sid}")
    assert listing.status == 200, f"list failed: {listing.status} {listing.text()}"
    docs = listing.json()["documents"]
    assert any(d["id"] == doc_id and d["title"] == title for d in docs), f"uploaded doc not listed: {docs}"

    downloaded = page.request.get(f"/api/core/process-docs/{doc_id}/download")
    assert downloaded.status == 200, f"download failed: {downloaded.status}"
    assert downloaded.body() == b"Step-by-step instructions."
    assert downloaded.headers.get("x-content-type-options") == "nosniff"
    disposition = downloaded.headers.get("content-disposition", "")
    assert "attachment" in disposition.lower(), f"expected attachment disposition by default, got: {disposition}"

    inline_view = page.request.get(f"/api/core/process-docs/{doc_id}/download?inline=1")
    assert inline_view.status == 200
    inline_disposition = inline_view.headers.get("content-disposition", "")
    assert "attachment" not in inline_disposition.lower(), (
        f"?inline=1 should not force attachment: {inline_disposition}"
    )


def test_ac15_upload_accepts_file_between_evidences_old_cap_and_process_docs_own_cap(logged_in_page: Page):
    """FIXED (was a review-found gap): app/api/app_factory.py:51 used to set Flask's
    *global* MAX_CONTENT_LENGTH from [evidence] max_file_size_mb (10MB in local.ini) —
    a setting that belongs to the evidence feature, not process_docs. process_docs has
    its own, separate config ([process_docs] max_file_size_mb = 20, exposed via
    GET .../config), but that limit was unreachable: any request over 10MB, including a
    process-docs upload well under its OWN advertised 20MB cap, was rejected by
    Werkzeug before the request body was even parsed. MAX_CONTENT_LENGTH is now the max
    across every feature's own cap (see app_factory.py), so a file in the previously
    dead 10-20MB zone now reaches process_docs' own check and succeeds, matching what
    GET /api/core/process-docs/config (AC14) has always advertised."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Docs Big {uuid.uuid4().hex[:8]}")

    from app.utils.config_loader import config as app_config

    evidence_cap_bytes = app_config.evidence_max_file_size_mb * 1024 * 1024
    assert evidence_cap_bytes < _MAX_BYTES, "evidence's cap is no longer smaller than process_docs' — re-check this test"

    # Just over evidence's old (now-irrelevant) 10MB cap, still under process_docs' own 20MB.
    in_range = b"A" * (evidence_cap_bytes + 1)
    resp = _upload(page, pid, sid, filename="big.txt", content=in_range)
    assert resp.status == 201, (
        f"expected a file within process_docs' own {_MAX_BYTES // (1024 * 1024)}MB cap to be "
        f"accepted, got {resp.status}: {resp.text()[:200]}"
    )

    listing = page.request.get(f"/api/core/process-docs/{sid}")
    assert len(listing.json()["documents"]) == 1


def test_ac15_upload_rejects_file_over_process_docs_own_cap(logged_in_page: Page):
    """A file over process_docs' own advertised 20MB cap is still rejected — now at the
    correct (unified) boundary rather than evidence's unrelated 10MB. Werkzeug's global
    MAX_CONTENT_LENGTH check runs before the request body is parsed, so a file this far
    over the cap is still a raw 413, not the app's own clean 400 JSON; narrowing that
    gap is a platform-wide Flask concern (a custom 413 handler), not specific to
    process-docs, so it's out of scope for this fix."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Docs TooBig {uuid.uuid4().hex[:8]}")

    oversized = b"A" * (_MAX_BYTES + 1)
    resp = _upload(page, pid, sid, filename="toobig.txt", content=oversized)
    assert resp.status == 413, f"expected 413 for a file over process_docs' own cap, got {resp.status}"

    listing = page.request.get(f"/api/core/process-docs/{sid}")
    assert listing.json()["documents"] == [], "oversized upload should not have created a record"


def test_ac15_upload_rejects_empty_file(logged_in_page: Page):
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Docs Empty {uuid.uuid4().hex[:8]}")

    resp = _upload(page, pid, sid, filename="empty.txt", content=b"")
    assert resp.status == 400, f"expected 400 for empty file, got {resp.status}: {resp.text()}"
    assert "empty" in resp.json()["error"].lower()


def test_ac15_upload_rejects_disallowed_mime_type(logged_in_page: Page):
    """image/png is not in [process_docs] allowed_mime_types (pdf/doc/docx/md/txt only)."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Docs Mime {uuid.uuid4().hex[:8]}")

    # PNG magic bytes so server-side magic-byte sniffing can't accidentally match an
    # allowed type regardless of the declared Content-Type.
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    resp = _upload(page, pid, sid, filename="sneaky.png", mime="image/png", content=png_bytes)
    assert resp.status == 400, f"expected 400 for disallowed mime type, got {resp.status}: {resp.text()}"
    assert "not allowed" in resp.json()["error"].lower()

    listing = page.request.get(f"/api/core/process-docs/{sid}")
    assert listing.json()["documents"] == [], "disallowed-mime upload should not have created a record"


def test_ac15_upload_requires_process_and_step_ownership(logged_in_page: Page):
    """validate_process_and_step: a step_id that doesn't belong to process_id is rejected."""
    page = logged_in_page
    pid_a, _sid_a = _create_process_with_step(page, f"E2E Docs Owner A {uuid.uuid4().hex[:8]}")
    pid_b, sid_b = _create_process_with_step(page, f"E2E Docs Owner B {uuid.uuid4().hex[:8]}")

    # step from process B, but claiming it belongs to process A.
    resp = _upload(page, pid_a, sid_b)
    assert resp.status == 400, f"expected 400 for mismatched process/step, got {resp.status}: {resp.text()}"
    assert "not found" in resp.json()["error"].lower() or "does not belong" in resp.json()["error"].lower()


def test_ac16_inline_create_then_update(logged_in_page: Page):
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Inline {uuid.uuid4().hex[:8]}")
    title = f"Inline SOP {uuid.uuid4().hex[:8]}"

    created = page.request.post(
        "/api/core/process-docs/inline",
        headers=csrf_headers(page),
        data={"process_id": pid, "step_id": sid, "title": title, "content_markdown": "# Step 1\nDo the thing."},
    )
    assert created.status == 201, f"inline create failed: {created.status} {created.text()}"
    doc = created.json()
    assert doc["content_markdown"] == "# Step 1\nDo the thing."

    updated = page.request.post(
        "/api/core/process-docs/inline",
        headers=csrf_headers(page),
        data={
            "process_id": pid,
            "step_id": sid,
            "document_id": doc["id"],
            "title": title,
            "content_markdown": "# Step 1\nDo the updated thing.",
        },
    )
    assert updated.status == 200, f"inline update failed: {updated.status} {updated.text()}"
    assert updated.json()["content_markdown"] == "# Step 1\nDo the updated thing."
    assert updated.json()["id"] == doc["id"], "update created a new doc instead of updating"

    listing = page.request.get(f"/api/core/process-docs/{sid}").json()["documents"]
    matching = [d for d in listing if d["id"] == doc["id"]]
    assert len(matching) == 1, f"expected exactly one doc after update, got: {listing}"


def test_ac16_inline_missing_title_is_rejected(logged_in_page: Page):
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Inline NoTitle {uuid.uuid4().hex[:8]}")
    resp = page.request.post(
        "/api/core/process-docs/inline",
        headers=csrf_headers(page),
        data={"process_id": pid, "step_id": sid, "title": "", "content_markdown": "content here"},
    )
    assert resp.status == 400, f"expected 400 for missing title, got {resp.status}: {resp.text()}"
    assert "title" in resp.json()["error"].lower()


def test_ac16_inline_missing_content_is_rejected(logged_in_page: Page):
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Inline NoContent {uuid.uuid4().hex[:8]}")
    resp = page.request.post(
        "/api/core/process-docs/inline",
        headers=csrf_headers(page),
        data={"process_id": pid, "step_id": sid, "title": "A title", "content_markdown": ""},
    )
    assert resp.status == 400, f"expected 400 for missing content_markdown, got {resp.status}: {resp.text()}"
    assert "content_markdown" in resp.json()["error"].lower()


def test_ac16_cannot_convert_file_doc_to_inline(logged_in_page: Page):
    """A file-based document (storage_path set) can't be repointed to inline via this endpoint."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Inline Convert {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page, pid, sid, title="file doc")
    assert uploaded.status == 201
    doc_id = uploaded.json()["id"]

    resp = page.request.post(
        "/api/core/process-docs/inline",
        headers=csrf_headers(page),
        data={
            "process_id": pid,
            "step_id": sid,
            "document_id": doc_id,
            "title": "file doc",
            "content_markdown": "trying to sneak in markdown",
        },
    )
    assert resp.status == 400, f"expected 400 converting file doc to inline, got {resp.status}: {resp.text()}"
    assert "file-based" in resp.json()["error"].lower() or "cannot replace" in resp.json()["error"].lower()


def test_ac19_delete_requires_admin_role(logged_in_page: Page):
    """logged_in_page's e2e_user is a plain member — delete must be refused."""
    page = logged_in_page
    pid, sid = _create_process_with_step(page, f"E2E Delete Member {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page, pid, sid, title="member cannot delete this")
    doc_id = uploaded.json()["id"]

    resp = page.request.delete(f"/api/core/process-docs/{doc_id}", headers=csrf_headers(page))
    assert resp.status in (401, 403), f"a member was allowed to delete a process doc: {resp.status}"

    still_listed = page.request.get(f"/api/core/process-docs/{sid}").json()["documents"]
    assert any(d["id"] == doc_id for d in still_listed), "doc disappeared despite the rejected delete"


@pytest.fixture()
def admin_page(browser, app_url, fresh_user):
    from app.core.db.models.user import UserRole

    admin = fresh_user(role=UserRole.ADMIN)
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    login_through_ui(page, admin["email"], admin["password"])
    yield page
    context.close()


def test_ac19_admin_can_soft_delete_and_it_disappears_and_is_idempotent(admin_page: Page):
    page = admin_page
    pid, sid = _create_process_with_step(page, f"E2E Delete Admin {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page, pid, sid, title="admin deletes this")
    assert uploaded.status == 201, f"setup upload failed: {uploaded.status} {uploaded.text()}"
    doc_id = uploaded.json()["id"]

    deleted = page.request.delete(f"/api/core/process-docs/{doc_id}", headers=csrf_headers(page))
    assert deleted.status == 200, f"admin delete failed: {deleted.status} {deleted.text()}"
    assert deleted.json()["deleted"] is True

    listing = page.request.get(f"/api/core/process-docs/{sid}").json()["documents"]
    assert not any(d["id"] == doc_id for d in listing), "soft-deleted doc still listed"

    download_after = page.request.get(f"/api/core/process-docs/{doc_id}/download")
    assert download_after.status == 404, "soft-deleted doc should no longer be downloadable"

    # Deleting again is idempotent success, not an error.
    again = page.request.delete(f"/api/core/process-docs/{doc_id}", headers=csrf_headers(page))
    assert again.status == 200, f"repeat delete of an already-deleted doc should succeed, got {again.status}"
    assert again.json()["deleted"] is True


def test_ac19_delete_nonexistent_doc_is_idempotent_success(admin_page: Page):
    page = admin_page
    resp = page.request.delete(f"/api/core/process-docs/{uuid.uuid4()}", headers=csrf_headers(page))
    assert resp.status == 200, f"deleting a nonexistent doc should be an idempotent success, got {resp.status}"


# --------------------------------------------------------------------------------------
# Cross-tenant probes (AC17/AC18/AC19's own org_id scoping) — mirrors test_tenant_isolation.py.
# --------------------------------------------------------------------------------------


@pytest.fixture()
def two_tenants(browser, app_url, fresh_user):
    from app.core.db.models.user import UserRole

    org_a = fresh_user(role=UserRole.ADMIN)
    org_b = fresh_user(role=UserRole.ADMIN)
    contexts = []

    def _sign_in(user):
        context = browser.new_context(base_url=app_url, ignore_https_errors=True)
        contexts.append(context)
        page = context.new_page()
        login_through_ui(page, user["email"], user["password"])
        return page

    pages = {"a": _sign_in(org_a), "b": _sign_in(org_b)}
    yield pages
    for context in contexts:
        context.close()


def test_org_b_process_docs_list_excludes_org_a_docs(two_tenants):
    """No dedicated GET-by-id: list is the read surface, and it must never cross tenants."""
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    marker = f"Secret SOP {uuid.uuid4().hex[:8]}"
    pid, sid = _create_process_with_step(page_a, f"E2E Cross Docs {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page_a, pid, sid, title=marker)
    assert uploaded.status == 201

    response = page_b.request.get(f"/api/core/process-docs/{sid}")
    # No object-level lookup exists to 404 on here (list_docs_for_step filters directly by
    # (step_id, org_id)); org B's own org_id simply never matches org A's rows, so the
    # right outcome is a normal 200 with an empty result, not a 404.
    assert response.status == 200, f"list failed for org B: {response.status}"
    assert response.json()["documents"] == [], "org A's process doc leaked into org B's step doc list"
    assert marker not in response.text(), "org A's doc title leaked into org B's response"


def test_org_b_cannot_download_org_a_doc(two_tenants):
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid, sid = _create_process_with_step(page_a, f"E2E Cross Download {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page_a, pid, sid, title="org A private SOP", content=b"org A only content")
    doc_id = uploaded.json()["id"]

    response = page_b.request.get(f"/api/core/process-docs/{doc_id}/download")
    assert response.status == 404, f"org B downloaded org A's doc: {response.status}"

    # Sanity: org A itself can still download it — proves the probe would catch a real leak.
    owner = page_a.request.get(f"/api/core/process-docs/{doc_id}/download")
    assert owner.status == 200, "owner cannot download its own doc — probe is inert"


def test_org_b_cannot_delete_org_a_doc(two_tenants):
    """Both signed in as ADMIN, so this isolates tenancy from role.

    Unlike download (404) and every process/step mutation (404), delete_document's
    lookup-miss and cross-org-miss paths are the *same* code path as "already deleted"
    (process_docs_service.delete_document: `repo.get_by_id` returns None either way, and
    that's treated as idempotent success — AC19). So org B's attempt on org A's doc_id
    returns 200 here, not 404 — and that is actually a *stronger* anti-enumeration
    property than 404 would be: a real delete by the owner also returns 200 (see
    test_ac19_admin_can_soft_delete...), so the response code alone never distinguishes
    "deleted", "not yours", and "never existed". The security-relevant assertion is
    therefore not the status code — it's that org A's doc must survive untouched.
    """
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid, sid = _create_process_with_step(page_a, f"E2E Cross Delete {uuid.uuid4().hex[:8]}")
    uploaded = _upload(page_a, pid, sid, title="org A doc org B tries to delete")
    doc_id = uploaded.json()["id"]

    response = page_b.request.delete(f"/api/core/process-docs/{doc_id}", headers=csrf_headers(page_b))
    assert response.status == 200, f"expected the idempotent-success shape (200), got {response.status}"
    assert response.json()["deleted"] is True

    still_there = page_a.request.get(f"/api/core/process-docs/{sid}").json()["documents"]
    assert any(d["id"] == doc_id for d in still_there), "org A's doc vanished after org B's cross-tenant delete attempt"

    downloadable = page_a.request.get(f"/api/core/process-docs/{doc_id}/download")
    assert downloadable.status == 200, "org A's doc should still be downloadable after org B's rejected delete"


def test_org_b_cannot_upload_against_org_a_process(two_tenants):
    page_a, page_b = two_tenants["a"], two_tenants["b"]
    pid, sid = _create_process_with_step(page_a, f"E2E Cross Upload {uuid.uuid4().hex[:8]}")

    response = _upload(page_b, pid, sid, title="org B trying to attach to org A process")
    assert response.status == 400, f"expected 400 (not found/access denied), got {response.status}: {response.text()}"

    listing = page_a.request.get(f"/api/core/process-docs/{sid}").json()["documents"]
    assert listing == [], "org B's cross-tenant upload attempt should not have created a record"
