"""Request validation for evidence uploads."""

import logging
from pathlib import Path
from uuid import UUID

from flask import request

logger = logging.getLogger(__name__)

# Magic bytes for server-side MIME detection (first few bytes)
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"%PDF": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
}


def detect_mime_from_path(file_path: Path) -> str | None:
    """
    Detect MIME from file magic bytes. Returns canonical MIME or None if unknown.
    """
    try:
        with open(file_path, "rb") as f:
            head = f.read(12)
    except OSError:
        return None
    for magic, mime in _MAGIC.items():
        if head.startswith(magic):
            return mime
    return None


def get_allowed_mime_types():
    """Return list of allowed MIME types from config."""
    from app.utils.config_loader import config

    return config.evidence_allowed_mime_types


def get_max_file_size_bytes():
    """Return max file size in bytes (default 10MB)."""
    from app.utils.config_loader import config

    return config.evidence_max_file_size_mb * 1024 * 1024


def validate_upload_request(org_id: UUID, execution_id: str, step_id: str | None) -> tuple[bool, str]:
    """
    Validate upload request: execution_id format and presence.
    Caller must validate execution belongs to org_id via repository.
    """
    if not execution_id or not str(execution_id).strip():
        return False, "execution_id is required"
    try:
        UUID(execution_id)
    except (ValueError, TypeError):
        return False, "Invalid execution_id"
    if step_id is not None and str(step_id).strip():
        try:
            UUID(step_id)
        except (ValueError, TypeError):
            return False, "Invalid step_id"
    return True, ""


def _normalize_content_type(content_type: str) -> str:
    """Normalize image/jpg -> image/jpeg."""
    if (content_type or "").strip().lower() == "image/jpg":
        return "image/jpeg"
    return (content_type or "").split(";")[0].strip().lower()


def validate_file():
    """
    Validate uploaded file: exists, size, MIME type. Loads entire file into memory (legacy).
    Returns (ok, error_message, data_bytes, content_type, original_filename).
    """
    if "file" not in request.files:
        logger.warning("Evidence validate_file: no 'file' in request.files (keys=%s)", list(request.files.keys()))
        return False, "No file in request", None, None, None
    f = request.files["file"]
    if not f or not f.filename or f.filename.strip() == "":
        logger.warning("Evidence validate_file: no file or empty filename")
        return False, "No file selected", None, None, None
    data = f.read()
    size = len(data)
    max_bytes = get_max_file_size_bytes()
    if size > max_bytes:
        logger.warning("Evidence validate_file: file too large size=%s max=%s", size, max_bytes)
        return False, f"File too large (max {max_bytes // (1024*1024)}MB)", None, None, None
    if size == 0:
        logger.warning("Evidence validate_file: file is empty")
        return False, "File is empty", None, None, None
    allowed = get_allowed_mime_types()
    content_type = _normalize_content_type(f.content_type or request.content_type or "")
    allowed_normalized = [_normalize_content_type(m) for m in allowed]
    if content_type not in allowed_normalized:
        logger.warning("Evidence validate_file: type not allowed content_type=%r allowed=%s", content_type, allowed)
        return False, f"File type not allowed (got {content_type!r}). Allowed: {', '.join(allowed)}", None, None, None
    logger.info("Evidence validate_file: ok filename=%s size=%s content_type=%s", f.filename, size, content_type)
    return True, "", data, content_type, (f.filename or "").strip()


def validate_file_streaming():
    """
    Validate uploaded file by streaming to a temp file. Checks size and server-side MIME (magic bytes).
    Returns (ok, error_message, temp_path, content_type, original_filename, file_size).
    On failure temp_path is None and caller has nothing to clean up. On success caller must pass
    temp_path to upload; it will be moved (or cleaned up on error).
    """
    import tempfile
    import os as os_mod

    if "file" not in request.files:
        logger.warning("Evidence validate_file_streaming: no 'file' in request.files")
        return False, "No file in request", None, None, None, 0
    f = request.files["file"]
    if not f or not f.filename or f.filename.strip() == "":
        return False, "No file selected", None, None, None, 0

    max_bytes = get_max_file_size_bytes()
    fd, temp_path = tempfile.mkstemp(prefix="evidence_", suffix=".tmp")
    try:
        os_mod.close(fd)
        f.save(temp_path)
        size = os_mod.path.getsize(temp_path)
        if size > max_bytes:
            logger.warning("Evidence validate_file_streaming: file too large size=%s max=%s", size, max_bytes)
            try:
                os_mod.unlink(temp_path)
            except OSError:
                pass
            return False, f"File too large (max {max_bytes // (1024*1024)}MB)", None, None, None, 0
        if size == 0:
            try:
                os_mod.unlink(temp_path)
            except OSError:
                pass
            return False, "File is empty", None, None, None, 0

        content_type = detect_mime_from_path(Path(temp_path))
        if not content_type:
            content_type = _normalize_content_type(f.content_type or request.content_type or "")
        content_type = _normalize_content_type(content_type or "")
        allowed = get_allowed_mime_types()
        allowed_normalized = [_normalize_content_type(m) for m in allowed]
        if content_type not in allowed_normalized:
            logger.warning("Evidence validate_file_streaming: type not allowed content_type=%r", content_type)
            try:
                os_mod.unlink(temp_path)
            except OSError:
                pass
            return False, f"File type not allowed (got {content_type!r}). Allowed: {', '.join(allowed)}", None, None, None, 0

        logger.info("Evidence validate_file_streaming: ok filename=%s size=%s content_type=%s", f.filename, size, content_type)
        return True, "", Path(temp_path), content_type, (f.filename or "").strip(), size
    except Exception as e:
        logger.exception("Evidence validate_file_streaming failed: %s", e)
        try:
            os_mod.unlink(temp_path)
        except OSError:
            pass
        return False, "Upload failed", None, None, None, 0
