"""Request validation for evidence uploads."""

import logging
from uuid import UUID

from flask import request

logger = logging.getLogger(__name__)


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


def validate_file():
    """
    Validate uploaded file: exists, size, MIME type.
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
    # Use the file part's Content-Type (multipart part), not request.content_type (which is multipart/form-data)
    content_type = (f.content_type or "").split(";")[0].strip().lower()
    if not content_type:
        content_type = (request.content_type or "").split(";")[0].strip().lower()
    # Normalize: some clients send image/jpg instead of image/jpeg
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    allowed_normalized = [("image/jpeg" if m == "image/jpg" else m) for m in allowed]
    if content_type not in allowed_normalized:
        logger.warning("Evidence validate_file: type not allowed content_type=%r allowed=%s", content_type, allowed)
        return False, f"File type not allowed (got {content_type!r}). Allowed: {', '.join(allowed)}", None, None, None
    logger.info("Evidence validate_file: ok filename=%s size=%s content_type=%s", f.filename, size, content_type)
    return True, "", data, content_type, (f.filename or "").strip()
