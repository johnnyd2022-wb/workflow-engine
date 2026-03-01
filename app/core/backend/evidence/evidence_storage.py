"""Filesystem operations for evidence files. Atomic write, UUID filenames."""

import hashlib
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# Strict filename: UUID plus extension only (no path traversal, no arbitrary names)
_SAFE_FILENAME_RE = re.compile(r"^[a-f0-9\-]{36}\.(jpg|jpeg|png|pdf|bin)$", re.IGNORECASE)


def is_safe_filename(name: str) -> bool:
    """
    Return True if name is safe for filesystem use: UUID + allowed extension only.
    Rejects '..', '/', '\\', and any non-UUID.ext pattern.
    """
    if not name or ".." in name or "/" in name or "\\" in name:
        return False
    return bool(_SAFE_FILENAME_RE.fullmatch(name.strip()))


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


def compute_checksum(file_path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA256 of file using chunked read to avoid loading entire file into RAM."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def prepare_final_path(org_id: str, execution_id: str, content_type: str) -> tuple[str, str]:
    """
    Generate final storage path (relative) and filename for a new evidence file.
    Returns (rel_path, filename) where filename is UUID.ext and passes is_safe_filename.
    """
    ext = extension_from_mime(content_type)
    name = f"{uuid4()}{ext}"
    rel_path = os.path.join(str(org_id), str(execution_id), name)
    return rel_path, name


def finalize_from_temp(temp_path: Path, org_id: str, execution_id: str, filename: str) -> None:
    """
    Atomically move temp file to final location under storage root.
    Call only after DB commit. Raises if filename is not safe or move fails.
    """
    if not is_safe_filename(filename):
        raise ValueError(f"Unsafe filename: {filename!r}")
    root = get_storage_root()
    dest_dir = root / str(org_id) / str(execution_id)
    ensure_dir(dest_dir)
    full_path = dest_dir / filename
    temp_path = Path(temp_path)
    if not temp_path.is_file():
        raise FileNotFoundError(f"Temp file missing: {temp_path}")
    os.replace(temp_path, full_path)
    logger.info("Evidence finalize_from_temp: %s -> %s", temp_path, full_path)


def read_file_path(org_id: str, execution_id: str, filename: str) -> Path | None:
    """
    Return full Path for a stored file if it exists and is under org_id/execution_id.
    filename must pass is_safe_filename (UUID.ext only; no path traversal).
    """
    if not is_safe_filename(filename):
        logger.warning("Evidence read_file_path: rejected unsafe filename=%r", filename)
        return None
    root = get_storage_root()
    candidate = root / str(org_id) / str(execution_id) / filename
    try:
        if not candidate.is_file():
            return None
        candidate.resolve().relative_to(root.resolve())
        return candidate
    except (ValueError, OSError):
        return None
