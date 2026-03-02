"""Filesystem operations for process step documentation. UUID filenames, no reuse of evidence_storage."""

import logging
import os
import re
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# Safe filename: UUID plus extension only
_SAFE_FILENAME_RE = re.compile(r"^[a-f0-9\-]{36}\.(pdf|doc|docx|md|txt|bin)$", re.IGNORECASE)


def is_safe_filename(name: str) -> bool:
    """Return True if name is safe for filesystem use: UUID + allowed extension only."""
    if not name or ".." in name or "/" in name or "\\" in name:
        return False
    return bool(_SAFE_FILENAME_RE.fullmatch(name.strip()))


def get_storage_root() -> Path:
    """Return process docs storage root from config; default app/core/process_docs_storage."""
    from app.utils.config_loader import config

    root = getattr(config, "process_docs_storage_root", None) or ""
    if root and str(root).strip():
        path = Path(str(root).strip())
        logger.info("Process docs storage root from config: %s", path)
        return path
    core_dir = Path(__file__).resolve().parent.parent.parent
    path = core_dir / "process_docs_storage"
    logger.info("Process docs storage root (default): %s", path)
    return path


def _dir_for(org_id: str, process_id: str, step_id: str) -> Path:
    """Path for org/process/step (no trailing slash)."""
    root = get_storage_root()
    return root / str(org_id) / str(process_id) / str(step_id)


def ensure_dir(path: Path) -> None:
    """Create directory and parents if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def extension_from_mime(mime: str) -> str:
    """Map MIME to safe extension."""
    m = (mime or "").strip().lower()
    if m == "application/pdf":
        return ".pdf"
    if m == "application/msword":
        return ".doc"
    if m == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return ".docx"
    if m == "text/markdown":
        return ".md"
    if m == "text/plain":
        return ".txt"
    return ".bin"


def prepare_final_path(org_id: str, process_id: str, step_id: str, content_type: str) -> tuple[str, str]:
    """Generate relative storage path and filename (UUID.ext). Returns (rel_path, filename)."""
    ext = extension_from_mime(content_type)
    name = f"{uuid4()}{ext}"
    rel_path = os.path.join(str(org_id), str(process_id), str(step_id), name)
    return rel_path, name


def finalize_from_temp(
    temp_path: Path, org_id: str, process_id: str, step_id: str, filename: str
) -> Path:
    """Atomically move temp file to final location. Call after DB commit. Raises if filename unsafe or move fails."""
    if not is_safe_filename(filename):
        raise ValueError(f"Unsafe filename: {filename!r}")
    root = get_storage_root()
    dest_dir = root / str(org_id) / str(process_id) / str(step_id)
    ensure_dir(dest_dir)
    full_path = dest_dir / filename
    temp_path = Path(temp_path)
    if not temp_path.is_file():
        raise FileNotFoundError(f"Temp file missing: {temp_path}")
    os.replace(temp_path, full_path)
    logger.info("Process doc finalize_from_temp: %s -> %s", temp_path, full_path)
    return full_path


def read_file_path(org_id: str, process_id: str, step_id: str, filename: str) -> Path | None:
    """Return full Path for a stored file if it exists and is under org/process/step."""
    if not is_safe_filename(filename):
        logger.warning("Process docs read_file_path: rejected unsafe filename=%r", filename)
        return None
    root = get_storage_root()
    candidate = root / str(org_id) / str(process_id) / str(step_id) / filename
    try:
        if not candidate.is_file():
            return None
        candidate.resolve().relative_to(root.resolve())
        return candidate
    except (ValueError, OSError):
        return None


def delete_file(org_id: str, process_id: str, step_id: str, filename: str) -> bool:
    """Delete a stored file if it exists and is safe. Returns True if deleted or missing."""
    full_path = read_file_path(org_id, process_id, step_id, filename)
    if not full_path:
        return True
    try:
        if full_path.exists():
            full_path.unlink()
            logger.info("Process doc delete_file: removed %s", full_path)
        return True
    except OSError as e:
        logger.warning("Process doc delete_file failed: %s", e)
        return False
