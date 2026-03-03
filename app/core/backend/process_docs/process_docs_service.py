"""Business logic for process step documentation (SOP): upload, inline, list, delete, download."""

import logging
import os
from pathlib import Path
from uuid import UUID

from app.core.backend.process_docs.process_docs_storage import (
    delete_file as storage_delete_file,
)
from app.core.backend.process_docs.process_docs_storage import (
    finalize_from_temp,
    prepare_final_path,
    read_file_path,
)
from app.core.db import db_session
from app.core.db.repositories.process_step_document_repo import ProcessStepDocumentRepository

logger = logging.getLogger(__name__)


def upload_sop_file(
    org_id: UUID,
    process_id: UUID,
    step_id: UUID,
    temp_path: Path,
    title: str,
    content_type: str,
    file_size: int,
    original_filename: str,
    created_by: UUID | None = None,
) -> tuple[dict | None, str, int]:
    """
    Save uploaded SOP file: insert record, commit, then finalize file to storage.
    Returns (response_dict, error_message, status_code).
    """
    repo = ProcessStepDocumentRepository(db_session)
    rel_path, filename = prepare_final_path(str(org_id), str(process_id), str(step_id), content_type)
    # Title from original filename if not provided
    doc_title = (title or "").strip() or original_filename or "SOP document"
    record = repo.create(
        org_id=org_id,
        process_id=process_id,
        step_id=step_id,
        title=doc_title,
        storage_path=rel_path,
        content_markdown=None,
        mime_type=content_type,
        file_size=file_size,
        created_by=created_by,
    )
    try:
        db_session.commit()
    except Exception as e:
        logger.exception("Process docs upload_sop_file: create/commit failed: %s", e)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return None, "Failed to save document record", 500

    try:
        finalize_from_temp(temp_path, str(org_id), str(process_id), str(step_id), filename)
    except Exception as e:
        logger.exception("Process docs finalize_from_temp failed (record already committed): %s", e)
        try:
            repo.soft_delete(record.id, org_id)
            db_session.commit()
        except Exception:
            logger.exception("Cleanup soft_delete failed")
            db_session.rollback()
        try:
            if temp_path.exists():
                os.unlink(temp_path)
        except OSError:
            pass
        return None, "Failed to finalize file", 500

    logger.info("Process docs upload_sop_file: success doc_id=%s storage_path=%s", record.id, rel_path)
    return (
        {
            "id": str(record.id),
            "title": record.title,
            "storage_path": rel_path,
            "mime_type": record.mime_type,
            "file_size": record.file_size,
            "process_id": str(process_id),
            "step_id": str(step_id),
            "created_at": record.created_at.isoformat() if record.created_at else None,
        },
        "",
        201,
    )


def create_or_update_inline(
    org_id: UUID,
    process_id: UUID,
    step_id: UUID,
    title: str,
    content_markdown: str,
    created_by: UUID | None = None,
    document_id: UUID | None = None,
) -> tuple[dict | None, str, int]:
    """
    Create or update inline SOP. If document_id given, update; else create.
    Returns (response_dict, error_message, status_code).
    """
    repo = ProcessStepDocumentRepository(db_session)
    if document_id:
        doc = repo.get_by_id(document_id, org_id)
        if not doc:
            return None, "Document not found or access denied", 404
        if doc.storage_path:
            return None, "Cannot replace file-based SOP with inline content via this endpoint", 400
        doc = repo.update_inline(document_id, org_id, title=title, content_markdown=content_markdown)
        db_session.commit()
        return (
            {
                "id": str(doc.id),
                "title": doc.title,
                "content_markdown": doc.content_markdown,
                "process_id": str(doc.process_id),
                "step_id": str(doc.step_id),
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            },
            "",
            200,
        )
    record = repo.create(
        org_id=org_id,
        process_id=process_id,
        step_id=step_id,
        title=title.strip(),
        content_markdown=content_markdown.strip(),
        storage_path=None,
        mime_type=None,
        file_size=None,
        created_by=created_by,
    )
    try:
        db_session.commit()
    except Exception as e:
        logger.exception("Process docs create_or_update_inline: commit failed: %s", e)
        db_session.rollback()
        return None, "Failed to save document", 500
    return (
        {
            "id": str(record.id),
            "title": record.title,
            "content_markdown": record.content_markdown,
            "process_id": str(process_id),
            "step_id": str(step_id),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        },
        "",
        201,
    )


def list_docs_for_step(step_id: UUID, org_id: UUID) -> list[dict]:
    """Return list of SOP documents for a step (file-based and inline), for execution modal."""
    repo = ProcessStepDocumentRepository(db_session)
    docs = repo.list_by_step(step_id, org_id)
    out = []
    for d in docs:
        item = {
            "id": str(d.id),
            "title": d.title,
            "process_id": str(d.process_id),
            "step_id": str(d.step_id),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        if d.storage_path:
            item["storage_path"] = d.storage_path
            item["mime_type"] = d.mime_type
            item["file_size"] = d.file_size
        else:
            item["content_markdown"] = d.content_markdown
        out.append(item)
    return out


def delete_document(doc_id: UUID, org_id: UUID) -> tuple[bool, str, int]:
    """
    Soft-delete a document; then remove file from storage if file-based (best effort).
    Order: soft-delete record, commit, then delete file — so a failed commit does not orphan the file.
    Returns (success, error_message, status_code).
    """
    repo = ProcessStepDocumentRepository(db_session)
    doc = repo.get_by_id(doc_id, org_id)
    if not doc:
        return True, "", 200  # idempotent
    # Capture path info before soft-delete (record may be updated)
    storage_path = doc.storage_path
    org_id_s, process_id_s, step_id_s = str(doc.org_id), str(doc.process_id), str(doc.step_id)
    repo.soft_delete(doc_id, org_id)
    try:
        db_session.commit()
    except Exception as e:
        logger.exception("Process docs delete_document failed: %s", e)
        db_session.rollback()
        return False, "Failed to delete document record", 500
    # Best-effort file deletion after commit (avoids storage leak; file delete failure is logged only)
    if storage_path:
        parts = storage_path.replace("\\", "/").split("/")
        if len(parts) >= 4:
            filename = parts[-1]
            storage_delete_file(org_id_s, process_id_s, step_id_s, filename)
    logger.info("Process docs delete_document: removed doc_id=%s", doc_id)
    return True, "", 200


def get_file_for_download(doc_id: UUID, org_id: UUID) -> tuple[bytes | None, str | None, str | None, str | None]:
    """Return (file_bytes, mime_type, file_name, error) for streaming. Error set if not found or not file-based."""
    repo = ProcessStepDocumentRepository(db_session)
    doc = repo.get_by_id(doc_id, org_id)
    if not doc:
        return None, None, None, "Document not found or access denied"
    if not doc.storage_path:
        return None, None, None, "Document is inline; no file to download"
    parts = doc.storage_path.replace("\\", "/").split("/")
    if len(parts) < 4:
        return None, None, None, "Invalid storage path"
    filename = parts[-1]
    full_path = read_file_path(str(doc.org_id), str(doc.process_id), str(doc.step_id), filename)
    if not full_path or not full_path.exists():
        return None, None, None, "File not found on disk"
    try:
        file_bytes = full_path.read_bytes()
    except OSError as e:
        logger.exception("Process doc read failed: %s", e)
        return None, None, None, "Failed to read file"
    # Download name: title with extension
    ext = full_path.suffix or ""
    download_name = (doc.title or "document").strip()
    if not download_name.endswith(ext):
        download_name += ext
    return file_bytes, doc.mime_type or "application/octet-stream", download_name, None
