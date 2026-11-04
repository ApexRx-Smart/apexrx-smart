"""Local filesystem storage for organization verification documents.

Files are stored under ``settings.upload_dir`` with a random storage key; the
original file name is only kept as metadata. Swap this module for an object
store (S3, GCS, ...) in production deployments with multiple servers.
"""

import secrets
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import AppError

CHUNK_SIZE = 1024 * 1024

# Magic numbers for the allowed document types; the client-supplied
# Content-Type is not trusted on its own.
_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def _root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve(storage_key: str) -> Path:
    root = _root()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise AppError("Invalid storage key.")
    return path


def save_document(organization_id: int, upload: UploadFile) -> tuple[str, str, int]:
    """Validate and store an upload. Returns ``(storage_key, mime_type, size)``."""
    mime_type = (upload.content_type or "").split(";")[0].strip().lower()
    if mime_type not in settings.allowed_document_mime_types:
        allowed = ", ".join(settings.allowed_document_mime_types)
        raise AppError(f"Unsupported file type '{mime_type}'. Allowed: {allowed}.", status_code=415)

    storage_key = f"org-{organization_id}/{secrets.token_hex(16)}{_EXTENSIONS.get(mime_type, '')}"
    path = resolve(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    head = b""
    try:
        with path.open("xb") as out:
            while chunk := upload.file.read(CHUNK_SIZE):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise AppError(
                        f"File exceeds the {settings.max_upload_size_bytes // (1024 * 1024)} MB limit.",
                        status_code=413,
                    )
                out.write(chunk)
        if size == 0:
            raise AppError("The uploaded file is empty.")
        signatures = _SIGNATURES.get(mime_type)
        if signatures and not head.startswith(signatures):
            raise AppError("The file content does not match its declared type.", status_code=415)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return storage_key, mime_type, size


def delete_document(storage_key: str) -> None:
    resolve(storage_key).unlink(missing_ok=True)
