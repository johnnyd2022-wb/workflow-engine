"""Validation for process doc upload and inline SOP."""

import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from flask import request

from app.core.backend.process_docs.process_docs_storage import get_temp_dir
from app.core.db import db_session
from app.core.db.repositories.process_repo import ProcessRepository

logger = logging.getLogger(__name__)

# Magic bytes for server-side MIME detection
_MAGIC = {
    b"%PDF": "application/pdf",
    b"\xd0\xcf\x11\xe0": "application/msword",  # DOC
    b"PK\x03\x04": None,  # ZIP-based (docx, etc.) – check extension from original filename
}


def _detect_mime_from_path(file_path: Path, original_filename: str = "") -> str | None:
    """Detect MIME from file magic bytes. For ZIP-based files, use original_filename extension (temp file has .tmp)."""
    try:
        with open(file_path, "rb") as f:
            head = f.read(12)
    except OSError:
        return None
    for magic, mime in _MAGIC.items():
        if head.startswith(magic):
            if mime:
                return mime
            # ZIP: infer from original filename; temp file is .tmp so file_path.suffix is wrong
            ext = Path(original_filename).suffix.lower() if original_filename else file_path.suffix.lower()
            if ext in (".docx", ".md", ".txt"):
                if ext == ".docx":
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if ext == ".md":
                    return "text/markdown"
                if ext == ".txt":
                    return "text/plain"
            return "application/octet-stream"
    return None


def get_allowed_mime_types() -> list[str]:
    """Return list of allowed MIME types from config."""
    from app.utils.config_loader import config

    return config.process_docs_allowed_mime_types


def get_max_file_size_bytes() -> int:
    """Return max file size in bytes (default 20MB).
    If limits are increased, consider setting app.config['MAX_CONTENT_LENGTH'] so Flask
    rejects oversized requests before streaming to disk.
    """
    from app.utils.config_loader import config

    return config.process_docs_max_file_size_mb * 1024 * 1024


def _normalize_content_type(content_type: str) -> str:
    """Normalize content-type header."""
    return (content_type or "").split(";")[0].strip().lower()


def validate_process_and_step(org_id: UUID, process_id: UUID, step_id: UUID) -> tuple[bool, str]:
    """Validate that process and step exist and belong to org. Returns (ok, error_message)."""
    repo = ProcessRepository(db_session)
    process = repo.get_process_with_steps(process_id, org_id)
    if not process:
        return False, "Process not found or access denied"
    step_ids = [s.id for s in (process.steps or []) if s.id]
    if step_id not in step_ids:
        return False, "Step not found or does not belong to process"
    return True, ""


def validate_upload_request(org_id: UUID, process_id: str, step_id: str) -> tuple[bool, str]:
    """Validate upload request: process_id and step_id format and ownership."""
    if not process_id or not str(process_id).strip():
        return False, "process_id is required"
    if not step_id or not str(step_id).strip():
        return False, "step_id is required"
    try:
        p_uuid = UUID(process_id)
        s_uuid = UUID(step_id)
    except (ValueError, TypeError):
        return False, "Invalid process_id or step_id"
    ok, err = validate_process_and_step(org_id, p_uuid, s_uuid)
    return ok, err


def validate_file_streaming() -> tuple[bool, str, Path | None, str, str, int]:
    """
    Validate uploaded file by streaming to temp file. Checks size and MIME.
    Returns (ok, error_message, temp_path, content_type, original_filename, file_size).
    """
    if "file" not in request.files:
        logger.warning("Process docs validate_file_streaming: no 'file' in request.files")
        return False, "No file in request", None, "", "", 0
    f = request.files["file"]
    if not f or not f.filename or f.filename.strip() == "":
        return False, "No file selected", None, "", "", 0

    max_bytes = get_max_file_size_bytes()
    # Temp under storage root so os.replace(temp, final) is same-filesystem and atomic (avoids cross-device link errors)
    temp_dir = get_temp_dir()
    fd, temp_path = tempfile.mkstemp(prefix="process_doc_", suffix=".tmp", dir=temp_dir)
    try:
        os.close(fd)
        f.save(temp_path)
        size = os.path.getsize(temp_path)
        if size > max_bytes:
            logger.warning("Process docs validate_file_streaming: file too large size=%s max=%s", size, max_bytes)
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return False, f"File too large (max {get_max_file_size_bytes() // (1024 * 1024)}MB)", None, "", "", 0
        if size == 0:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return False, "File is empty", None, "", "", 0

        content_type = _detect_mime_from_path(Path(temp_path), (f.filename or "").strip())
        if not content_type:
            content_type = _normalize_content_type(f.content_type or request.content_type or "")
        content_type = _normalize_content_type(content_type or "")
        allowed = get_allowed_mime_types()
        allowed_normalized = [_normalize_content_type(m) for m in allowed]
        if content_type not in allowed_normalized:
            logger.warning("Process docs validate_file_streaming: type not allowed content_type=%r", content_type)
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return (
                False,
                f"File type not allowed (got {content_type!r}). Allowed: {', '.join(allowed)}",
                None,
                "",
                "",
                0,
            )

        logger.info(
            "Process docs validate_file_streaming: ok filename=%s size=%s content_type=%s",
            f.filename,
            size,
            content_type,
        )
        return True, "", Path(temp_path), content_type, (f.filename or "").strip(), size
    except Exception as e:
        logger.exception("Process docs validate_file_streaming failed: %s", e)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return False, "Upload failed", None, "", "", 0


def validate_inline_request(
    org_id: UUID, process_id: UUID, step_id: UUID, title: str, content_markdown: str
) -> tuple[bool, str]:
    """Validate inline SOP: title and content_markdown required; process/step ownership."""
    ok, err = validate_process_and_step(org_id, process_id, step_id)
    if not ok:
        return False, err
    if not title or not str(title).strip():
        return False, "title is required"
    if content_markdown is None or (isinstance(content_markdown, str) and not content_markdown.strip()):
        return False, "content_markdown is required for inline SOP"
    return True, ""
