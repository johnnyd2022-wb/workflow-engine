import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import csrf_headers, login_through_ui
from tests.e2e.test_execution_flow import _add_step, _create_process, _open_batch_start, _start_execution

pytestmark = pytest.mark.e2e


def test_evidence_camera_filters_types_and_server_confirms_content(page, app_url, fresh_user):
    user = fresh_user()
    login_through_ui(page, user["email"], user["password"])
    process = _create_process(page, "Evidence validation", is_draft=False)
    _add_step(
        page,
        process,
        1,
        "Review evidence",
        execution_prompts=[{"label": "Evidence", "type": "evidence", "required": True}],
    )
    execution = _start_execution(page, process)
    _open_batch_start(page, process, execution)
    camera = page.get_by_label("Take a photo")
    expect(camera).to_have_attribute("accept", "image/jpeg,image/png")

    response = page.request.post(
        "/api/core/evidence/upload",
        headers=csrf_headers(page),
        multipart={
            "execution_id": execution,
            "file": {"name": "note.png", "mimeType": "image/png", "buffer": b"Written observations"},
        },
    )
    assert response.status == 400
    assert "file" in response.json()["errors"]
