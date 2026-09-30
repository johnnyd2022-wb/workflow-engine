"""PDF and image attachments on compliance records, kept in org-scoped evidence storage.

Files live under ``<evidence root>/<org_id>/np3-<record_id>/<uuid>.<ext>``. The type is decided by
the file's own leading bytes, never the client's claimed content type or filename.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from flask import request

from app.core.backend.evidence.evidence_storage import (
    compute_checksum,
    delete_file,
    extension_from_mime,
    finalize_from_temp,
    read_file_path,
)
from app.core.backend.evidence.evidence_validation import detect_mime_from_path, get_max_file_size_bytes
from app.features.compliant.models import ComplianceRecord, ComplianceRecordFile

ALLOWED_MIME_TYPES = ("application/pdf", "image/png", "image/jpeg")
MAX_FILES_PER_RECORD = 10


def _segment(record_id: UUID) -> str:
    return f"np3-{record_id}"


def receive_upload() -> tuple[Path | None, str, str, int, str]:
    """Stream the request's ``file`` part to a temp file and validate it.

    Returns ``(temp_path, mime, file_name, size, error)``; ``temp_path`` is None on error.
    """
    upload = request.files.get("file")
    if upload is None or not (upload.filename or "").strip():
        return None, "", "", 0, "Choose a PDF or image to attach"
    fd, temp_name = tempfile.mkstemp(prefix="np3_file_", suffix=".tmp")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        upload.save(temp_path)
        size = temp_path.stat().st_size
        max_bytes = get_max_file_size_bytes()
        error = None
        mime = None
        if size == 0:
            error = "The file is empty"
        elif size > max_bytes:
            error = f"The file is too large (max {max_bytes // (1024 * 1024)}MB)"
        else:
            mime = detect_mime_from_path(temp_path)
            if mime not in ALLOWED_MIME_TYPES:
                error = "Only PDF, PNG and JPEG files can be attached"
        if error:
            temp_path.unlink(missing_ok=True)
            return None, "", "", 0, error
        return temp_path, mime, upload.filename.strip()[:512], size, ""
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def attach_file(
    session, org_id: UUID, record: ComplianceRecord, user_id: UUID | None, temp_path: Path, mime: str, name: str
) -> ComplianceRecordFile:
    """Store a validated temp file against ``record``. The row is committed before the file moves."""
    storage_name = f"{uuid4()}{extension_from_mime(mime)}"
    row = ComplianceRecordFile(
        org_id=org_id,
        record_id=record.id,
        file_name=name,
        storage_name=storage_name,
        mime_type=mime,
        file_size=temp_path.stat().st_size,
        checksum_sha256=compute_checksum(temp_path),
        uploaded_by_user_id=user_id,
    )
    session.add(row)
    session.flush()
    try:
        finalize_from_temp(temp_path, str(org_id), _segment(record.id), storage_name)
        session.commit()
    except Exception:
        session.rollback()
        delete_file(str(org_id), _segment(record.id), storage_name)
        temp_path.unlink(missing_ok=True)
        raise
    return row


def file_count(session, org_id: UUID, record_id: UUID) -> int:
    return (
        session.query(ComplianceRecordFile)
        .filter(ComplianceRecordFile.org_id == org_id, ComplianceRecordFile.record_id == record_id)
        .count()
    )


def get_file(session, org_id: UUID, record_id: UUID, file_id: UUID) -> ComplianceRecordFile | None:
    return (
        session.query(ComplianceRecordFile)
        .filter(
            ComplianceRecordFile.org_id == org_id,
            ComplianceRecordFile.record_id == record_id,
            ComplianceRecordFile.id == file_id,
        )
        .one_or_none()
    )


def read_content(row: ComplianceRecordFile) -> bytes | None:
    path = read_file_path(str(row.org_id), _segment(row.record_id), row.storage_name)
    if path is None:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def files_by_record(session, org_id: UUID, record_ids: list[UUID]) -> dict[UUID, list[dict]]:
    """Display metadata for each record's files, oldest first. Never includes the storage path."""
    if not record_ids:
        return {}
    rows = (
        session.query(ComplianceRecordFile)
        .filter(ComplianceRecordFile.org_id == org_id, ComplianceRecordFile.record_id.in_(record_ids))
        .order_by(ComplianceRecordFile.created_at.asc(), ComplianceRecordFile.id.asc())
        .all()
    )
    grouped: dict[UUID, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.record_id, []).append(
            {
                "id": str(row.id),
                "file_name": row.file_name,
                "mime_type": row.mime_type,
                "file_size": row.file_size,
                "checksum_sha256": row.checksum_sha256,
                "url": f"/api/compliant/np3-audit/records/{row.record_id}/files/{row.id}",
            }
        )
    return grouped
