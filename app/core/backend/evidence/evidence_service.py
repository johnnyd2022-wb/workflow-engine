"""Business logic for evidence upload and retrieval."""

import logging
import os
from pathlib import Path
from uuid import UUID

from app.core.backend.evidence.evidence_storage import (
    compute_checksum,
    finalize_from_temp,
    prepare_final_path,
    read_file_path,
    verify_checksum_at_path,
)
from app.core.db import db_session
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, EVIDENCE_STATUS_PENDING
from app.core.db.repositories.evidence_repo import EvidenceRepository
from app.core.db.repositories.execution_repo import ExecutionRepository

logger = logging.getLogger(__name__)


def upload_evidence_from_temp(
    org_id: UUID,
    execution_id: UUID,
    temp_path: Path,
    file_name: str,
    content_type: str,
    file_size: int,
    step_id: UUID | None = None,
    uploaded_by: str | None = None,
) -> tuple[dict | None, str, int]:
    """
    Two-phase upload: validate execution, compute checksum from temp file, insert DB, commit, then
    atomically move temp to final path. No file at final path until after commit (no orphan files).
    Returns (response_dict, error_message, status_code).
    """
    repo = ExecutionRepository(db_session)
    execution = repo.get_execution_with_steps(execution_id, org_id)
    if not execution:
        logger.warning(
            "Evidence upload_evidence_from_temp: execution not found execution_id=%s org_id=%s",
            execution_id,
            org_id,
        )
        return None, "Execution not found or access denied", 404

    try:
        checksum = compute_checksum(temp_path)
    except Exception as e:
        logger.exception("Evidence compute_checksum failed: %s", e)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return None, "Failed to process file", 500

    rel_path, filename = prepare_final_path(str(org_id), str(execution_id), content_type)
    evidence_repo = EvidenceRepository(db_session)
    # Transaction 1: metadata commit first, then storage (session already has active transaction)
    record = evidence_repo.create(
        org_id=org_id,
        execution_id=execution_id,
        step_id=step_id,
        file_name=file_name,
        storage_path=rel_path,
        mime_type=content_type,
        file_size=file_size,
        checksum_sha256=checksum,
        uploaded_by=uploaded_by,
        evidence_status=EVIDENCE_STATUS_PENDING,
    )
    try:
        db_session.commit()
    except Exception as e:
        logger.exception("Evidence upload_evidence_from_temp: create/commit failed: %s", e)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return None, "Failed to save evidence record", 500

    full_path = None
    try:
        full_path = finalize_from_temp(temp_path, str(org_id), str(execution_id), filename)
    except Exception as e:
        logger.exception("Evidence finalize_from_temp failed (record already committed): %s", e)
        try:
            evidence_repo.delete_by_id(record.id, org_id)
            db_session.commit()
        except Exception:
            logger.exception("Cleanup record deletion failed")
            db_session.rollback()
        try:
            if temp_path.exists():
                os.unlink(temp_path)
        except OSError:
            pass
        return None, "Failed to finalize file", 500

    if not verify_checksum_at_path(full_path, checksum):
        logger.error("Evidence verify_checksum_at_path failed after move: %s", full_path)
        try:
            evidence_repo.delete_by_id(record.id, org_id)
            db_session.commit()
        except Exception:
            logger.exception("Cleanup record deletion failed")
            db_session.rollback()
        try:
            if full_path.exists():
                os.unlink(full_path)
        except OSError:
            pass
        return None, "File verification failed after save", 500

    # Transaction 2: mark ACTIVE only after storage is finalized and verified
    try:
        evidence_repo.update_status(record.id, org_id, EVIDENCE_STATUS_ACTIVE)
        db_session.commit()
    except Exception as e:
        logger.exception("Evidence update_status to ACTIVE failed: %s", e)
        try:
            evidence_repo.delete_by_id(record.id, org_id)
            db_session.commit()
        except Exception:
            logger.exception("Cleanup record deletion failed")
            db_session.rollback()
        try:
            if full_path.exists():
                os.unlink(full_path)
        except OSError:
            pass
        return None, "Failed to activate evidence record", 500

    # Canonical shape so frontend never infers mapping (step_definition_id, execution_step_id, execution_id)
    step_definition_id = str(record.step_id) if record.step_id else None
    execution_step_id = None
    if execution.execution_steps and step_definition_id:
        for es in execution.execution_steps:
            if es.step_id and str(es.step_id) == step_definition_id:
                execution_step_id = str(es.id)
                break

    logger.info("Evidence upload_evidence_from_temp: success evidence_id=%s storage_path=%s", record.id, rel_path)
    return (
        {
            "id": str(record.id),
            "file_name": record.file_name,
            "mime_type": record.mime_type,
            "file_size": record.file_size,
            "step_definition_id": step_definition_id,
            "execution_step_id": execution_step_id,
            "execution_id": str(execution_id),
            "created_at": record.created_at.isoformat() if record.created_at else None,
        },
        "",
        201,
    )


def list_evidence_for_execution(execution_id: UUID, org_id: UUID) -> list[dict]:
    """
    Return list of evidence metadata for an execution (org-scoped).
    Each item includes step_definition_id (steps.id) and execution_step_id (execution_steps.id)
    so the frontend can filter without duplicating step-id resolution logic.
    """
    evidence_repo = EvidenceRepository(db_session)
    records = evidence_repo.list_by_execution(execution_id, org_id)
    exec_repo = ExecutionRepository(db_session)
    execution = exec_repo.get_execution_with_steps(execution_id, org_id)
    step_id_to_exec_step_id = {}
    if execution and execution.execution_steps:
        for es in execution.execution_steps:
            if es.step_id:
                step_id_to_exec_step_id[str(es.step_id)] = str(es.id)

    # Canonical shape: id, file_name, mime_type, file_size, step_definition_id, execution_step_id, execution_id
    # step_id kept as alias for step_definition_id for backward compatibility
    out = []
    exec_id_str = str(execution_id)
    for r in records:
        step_definition_id = str(r.step_id) if r.step_id else None
        execution_step_id = step_id_to_exec_step_id.get(step_definition_id) if step_definition_id else None
        out.append(
            {
                "id": str(r.id),
                "file_name": r.file_name,
                "mime_type": r.mime_type,
                "file_size": r.file_size,
                "step_definition_id": step_definition_id,
                "execution_step_id": execution_step_id,
                "execution_id": exec_id_str,
                "step_id": step_definition_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


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
