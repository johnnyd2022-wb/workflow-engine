"""Business logic for evidence upload and retrieval."""

import logging
from uuid import UUID

from app.core.backend.evidence.evidence_storage import read_file_path, save_file
from app.core.db import db_session
from app.core.db.repositories.evidence_repo import EvidenceRepository
from app.core.db.repositories.execution_repo import ExecutionRepository

logger = logging.getLogger(__name__)


def upload_evidence(
    org_id: UUID,
    execution_id: UUID,
    file_name: str,
    data: bytes,
    content_type: str,
    step_id: UUID | None = None,
    uploaded_by: str | None = None,
) -> tuple[dict | None, str, int]:
    """
    Validate execution belongs to org, save file, insert metadata.
    Returns (response_dict, error_message, status_code).
    """
    repo = ExecutionRepository(db_session)
    execution = repo.get_execution_by_id(execution_id, org_id)
    if not execution:
        logger.warning("Evidence upload_evidence: execution not found execution_id=%s org_id=%s", execution_id, org_id)
        return None, "Execution not found or access denied", 404

    logger.info(
        "Evidence upload_evidence: saving file execution_id=%s step_id=%s file_name=%s size=%s",
        execution_id,
        step_id,
        file_name,
        len(data),
    )
    try:
        storage_path, checksum = save_file(str(org_id), str(execution_id), data, content_type)
    except Exception as e:
        logger.exception("Evidence save_file failed: %s", e)
        return None, "Failed to save file", 500

    evidence_repo = EvidenceRepository(db_session)
    record = evidence_repo.create(
        org_id=org_id,
        execution_id=execution_id,
        step_id=step_id,
        file_name=file_name,
        storage_path=storage_path,
        mime_type=content_type,
        file_size=len(data),
        checksum_sha256=checksum,
        uploaded_by=uploaded_by,
    )
    try:
        db_session.commit()
    except Exception as e:
        logger.exception("Evidence upload_evidence: commit failed after file write: %s", e)
        return None, "Failed to save evidence record", 500
    logger.info("Evidence upload_evidence: success evidence_id=%s storage_path=%s", record.id, storage_path)
    return (
        {
            "id": str(record.id),
            "file_name": record.file_name,
            "storage_path": record.storage_path,
            "mime_type": record.mime_type,
            "file_size": record.file_size,
            "checksum_sha256": record.checksum_sha256,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        },
        "",
        201,
    )


def list_evidence_for_execution(execution_id: UUID, org_id: UUID) -> list[dict]:
    """Return list of evidence metadata for an execution (org-scoped)."""
    repo = EvidenceRepository(db_session)
    records = repo.list_by_execution(execution_id, org_id)
    return [
        {
            "id": str(r.id),
            "file_name": r.file_name,
            "mime_type": r.mime_type,
            "file_size": r.file_size,
            "step_id": str(r.step_id) if r.step_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


def get_evidence_for_download(
    evidence_id: UUID, org_id: UUID
) -> tuple[bytes | None, str | None, str | None, str | None]:
    """
    Return (file_bytes, mime_type, file_name, error) for streaming.
    If error is set, file_bytes/mime_type/file_name may be None.
    """
    evidence_repo = EvidenceRepository(db_session)
    record = evidence_repo.get_by_id(evidence_id, org_id)
    if not record:
        return None, None, None, "Evidence not found or access denied"

    # storage_path is relative: org_id/execution_id/filename
    parts = record.storage_path.replace("\\", "/").split("/")
    if len(parts) < 3:
        return None, None, None, "Invalid storage path"
    filename = parts[-1]
    full_path = read_file_path(str(record.org_id), str(record.execution_id), filename)
    if not full_path or not full_path.exists():
        return None, None, None, "File not found on disk"
    try:
        file_bytes = full_path.read_bytes()
    except OSError as e:
        logger.exception("Evidence read failed: %s", e)
        return None, None, None, "Failed to read file"
    return file_bytes, record.mime_type, record.file_name, None
