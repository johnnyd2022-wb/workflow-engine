from uuid import uuid4

import pytest

from tests.test_process_design import authed_client  # noqa: F401


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ([], "_body"),
        ({"name": 10}, "name"),
        ({"name": "x" * 256}, "name"),
        ({"name": "Blend", "is_draft": "false"}, "is_draft"),
        ({"name": "Blend", "settings": {"library_stock_name": 42}}, "settings"),
    ],
)
def test_process_create_validates_fields(authed_client, payload, field):  # noqa: F811
    response = authed_client.post("/api/core/processes", json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"step_number": True}, "step_number"),
        ({"step_number": 2.8}, "step_number"),
        ({"description": "x" * 1001}, "description"),
        ({"outputs": [{"name": "Output", "extra_data": ["invalid"]}]}, "outputs"),
        ({"inputs": "invalid"}, "inputs"),
    ],
)
def test_step_create_validates_fields(authed_client, values, field):  # noqa: F811
    pid = uuid4()
    response = authed_client.post(
        f"/api/core/processes/{pid}/steps",
        json={"step_number": 1, "name": "Blend", **values},
    )
    assert response.status_code == 400
    assert any(key == field or key.startswith(f"{field}.") for key in response.json["errors"])


@pytest.mark.parametrize(("payload", "field"), [([], "_body"), ({"process_id": []}, "process_id")])
def test_inline_document_validates_body_and_field_types(authed_client, payload, field):  # noqa: F811
    response = authed_client.post("/api/core/process-docs/inline", json=payload)
    assert response.status_code == 400
    assert field in response.json["errors"]


@pytest.mark.parametrize(
    ("filename", "contents", "expected"),
    [
        ("instructions.txt", b"Wash the vessel.\nRinse with water.\n", "text/plain"),
        ("instructions.md", b"# Cleaning procedure\n", "text/markdown"),
        ("instructions.txt", b"Incomplete data\x00", None),
        ("instructions.pdf", b"Not a PDF document", None),
        ("instructions.docx", b"Not a Word document", None),
        ("instructions.bin", b"Unsupported file extension", None),
    ],
)
def test_process_file_detection_checks_content_and_extension(tmp_path, filename, contents, expected):
    from app.features.process_design.process_docs.process_docs_validation import _validated_document_mime

    path = tmp_path / "upload.tmp"
    path.write_bytes(contents)
    assert _validated_document_mime(path, filename) == expected
