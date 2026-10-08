"""Where admin documents live on disk, and what may be stored there.

Files are kept on the admin site's own volume, outside the customer app's storage, under
`<root>/<org id>/<uuid>.<ext>`. Nothing from the upload decides a path: the stored name is
generated here, and the original filename is kept only as text to show and to offer as the
download name.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

from app.utils.config_loader import config

MAX_BYTES = 20 * 1024 * 1024
# Extension -> the bytes such a file must start with (None: no fixed signature to check).
_ZIP, _OLE = (b"PK\x03\x04",), (b"\xd0\xcf\x11\xe0",)
ALLOWED = {
    ".pdf": (b"%PDF",),
    ".docx": _ZIP,
    ".xlsx": _ZIP,
    ".pptx": _ZIP,
    ".doc": _OLE,
    ".xls": _OLE,
    ".msg": _OLE,
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".txt": None,
    ".csv": None,
    ".eml": None,
}
_STORED_NAME = re.compile(r"^[a-f0-9-]{36}\.[a-z]{3,4}$")


class DocumentError(ValueError):
    """The upload cannot be kept; the message is safe to show the admin."""


def storage_root() -> Path:
    root = (os.getenv("ADMIN_DOCUMENTS_ROOT") or config.get("admin_site", "documents_root", "") or "").strip()
    if root:
        return Path(root)
    if config.environment not in {"local", "test"}:
        # Inside a container an unset root would mean files that vanish on the next deploy.
        raise DocumentError("Document storage is not set up for this site (ADMIN_DOCUMENTS_ROOT).")
    return Path(__file__).resolve().parent / "document_storage"


def clean_filename(name: str | None) -> str:
    """The upload's own name, reduced to something safe to show and to send back."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '"<>|:*?').strip(" .")
    return name[:255]


def store(org_id: UUID, stream, filename: str) -> tuple[str, int, str]:
    """Write an upload under the organisation's folder. Returns (stored name, size, sha256)."""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED))
        raise DocumentError(f"That file type can't be stored. Allowed: {allowed}.")
    folder = storage_root() / str(org_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4()}{extension}"
    partial = folder / f"{stored_name}.part"
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with open(partial, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DocumentError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise DocumentError("That file is empty.")
        signatures = ALLOWED[extension]
        if signatures is not None and not head.startswith(signatures):
            raise DocumentError(f"That file is not a real {extension.lstrip('.')} file.")
        if signatures is None and b"\x00" in head:
            raise DocumentError(f"That file is not a real {extension.lstrip('.')} file.")
        os.replace(partial, folder / stored_name)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return stored_name, size, digest.hexdigest()


def path_for(org_id: UUID, stored_name: str) -> Path | None:
    """The stored file, or None if it is missing or the name is not one this module made."""
    if not _STORED_NAME.fullmatch(stored_name or ""):
        return None
    root = storage_root()
    candidate = root / str(org_id) / stored_name
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def remove(org_id: UUID, stored_name: str) -> None:
    path = path_for(org_id, stored_name)
    if path is not None:
        path.unlink(missing_ok=True)
