"""Filesystem operations for evidence files. Atomic write, UUID filenames."""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


def get_storage_root():
    """Return evidence storage root directory from config."""
    from app.utils.config_loader import config

    root = getattr(config, "evidence_storage_root", None) or ""
    if root and str(root).strip():
        path = Path(str(root).strip())
        logger.info("Evidence storage root from config: %s", path)
        return path
    # Default: app/core/evidence_storage (per execution-evidence spec)
    core_dir = Path(__file__).resolve().parent.parent.parent  # app/core
    path = core_dir / "evidence_storage"
    logger.info("Evidence storage root (default): %s", path)
    return path


def _dir_for(org_id: str, execution_id: str) -> Path:
    """Path for org/execution (no trailing slash)."""
    root = get_storage_root()
    return root / str(org_id) / str(execution_id)


def ensure_dir(path: Path) -> None:
    """Create directory and parents if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def extension_from_mime(mime: str) -> str:
    """Map MIME to safe extension (no trust of client filename)."""
    m = (mime or "").strip().lower()
    if m == "image/jpeg" or m == "image/jpg":
        return ".jpg"
    if m == "image/png":
        return ".png"
    if m == "application/pdf":
        return ".pdf"
    return ".bin"


def save_file(org_id: str, execution_id: str, data: bytes, content_type: str) -> tuple[str, str]:
    """
    Save file to org_id/execution_id/uuid.ext using atomic write.
    Returns (storage_path_relative_to_root, checksum_sha256).
    """
    dest_dir = _dir_for(org_id, execution_id)
    logger.info("Evidence save_file: dest_dir=%s, size=%s, content_type=%s", dest_dir, len(data), content_type)
    ensure_dir(dest_dir)
    ext = extension_from_mime(content_type)
    name = f"{uuid4()}{ext}"
    full_path = dest_dir / name
    rel_path = os.path.join(str(org_id), str(execution_id), name)

    hasher = hashlib.sha256()
    hasher.update(data)
    checksum = hasher.hexdigest()

    try:
        fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=".tmp_", suffix=ext)
        try:
            os.write(fd, data)  # type: ignore[arg-type]
            os.close(fd)
            fd = None
            os.replace(tmp_path, full_path)
            logger.info("Evidence file written: %s", full_path)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
    except Exception as e:
        logger.exception("Evidence save failed: dest_dir=%s, error=%s", dest_dir, e)
        raise

    return rel_path, checksum


def read_file_path(org_id: str, execution_id: str, filename: str) -> Path | None:
    """
    Return full Path for a stored file if it exists and is under org_id/execution_id.
    filename must be a single path component (UUID.ext).
    """
    root = get_storage_root()
    candidate = root / str(org_id) / str(execution_id) / filename
    try:
        if not candidate.is_file():
            return None
        candidate.resolve().relative_to(root.resolve())
        return candidate
    except (ValueError, OSError):
        return None
