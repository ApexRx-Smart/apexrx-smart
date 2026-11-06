"""Storage for organization verification documents.

The files live in a private **Supabase Storage** bucket in production, and in
``settings.upload_dir`` on the local disk during development and tests (see
``settings.document_storage``). Their metadata (type, name, size, review status
and the storage key) always stays in PostgreSQL.

Storage keys are generated here, never taken from the client:
``org-<organization_id>/<32 random hex characters><extension>``. The original
file name is only kept as metadata, so a crafted name cannot cause path
traversal or overwrite another file.

Files are never exposed by URL. The API checks the caller's rights and then
streams the bytes itself (see ``read_document``), so the bucket stays private
and the Supabase secret key never leaves the backend.
"""

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx
from fastapi import UploadFile, status

from app.core.config import settings
from app.core.errors import AppError, NotFound

logger = logging.getLogger("apexrx.storage")

READ_CHUNK = 1024 * 1024

# Magic numbers for the allowed document types; the client-supplied
# Content-Type is not trusted on its own.
_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}

UNAVAILABLE = "Document storage is temporarily unavailable. Please try again shortly."
MISSING = (
    "The document file is missing from storage. "
    "Ask the organization to upload it again."
)


class StorageUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class ObjectMissing(Exception):
    """Raised by a backend when the object does not exist."""


class StorageBackend(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class LocalBackend:
    """Files under ``settings.upload_dir`` (development and tests)."""

    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise AppError("Invalid storage key.")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as out:  # never overwrite
            out.write(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectMissing(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class SupabaseBackend:
    """Objects in a private Supabase Storage bucket.

    ``client`` is a ``storage3.SyncStorageClient`` (the official Supabase
    Storage client) or anything with the same ``from_(bucket)`` interface.
    """

    name = "supabase"

    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    def _files(self):
        return self.client.from_(self.bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._files().upload(
            key,
            data,
            {"content-type": content_type, "upsert": "false", "cache-control": "no-store"},
        )

    def get(self, key: str) -> bytes:
        try:
            return self._files().download(key)
        except Exception as exc:
            if _is_not_found(exc):
                raise ObjectMissing(key) from exc
            raise

    def delete(self, key: str) -> None:
        self._files().remove([key])


def _is_not_found(exc: Exception) -> bool:
    status_value = str(getattr(exc, "status", ""))
    code = str(getattr(exc, "code", "")).lower()
    return status_value == "404" or code in {"not_found", "nosuchkey", "notfound"}


def create_supabase_client():
    """Build the storage3 client from settings. The key is sent as both the
    ``apikey`` and the bearer token, which Supabase accepts for both the new
    ``sb_secret_...`` keys and the legacy ``service_role`` key."""
    from storage3 import SyncStorageClient

    if not settings.supabase_url or settings.supabase_secret_key is None:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must both be set.")
    key = settings.supabase_secret_key.get_secret_value()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    http_client = httpx.Client(
        headers=headers, timeout=settings.supabase_timeout_seconds, follow_redirects=True
    )
    return SyncStorageClient(
        f"{settings.supabase_url.rstrip('/')}/storage/v1/", headers, http_client=http_client
    )


def _supabase_configured() -> bool:
    return bool(settings.supabase_url) and settings.supabase_secret_key is not None


@lru_cache(maxsize=1)
def _configured_backend() -> StorageBackend:
    mode = settings.document_storage
    if mode == "supabase" or (mode == "auto" and _supabase_configured()):
        backend: StorageBackend = SupabaseBackend(create_supabase_client(), settings.supabase_bucket_name)
        logger.info("Document storage: Supabase bucket '%s'.", settings.supabase_bucket_name)
    else:
        backend = LocalBackend(settings.upload_dir)
        logger.info("Document storage: local directory (set SUPABASE_URL to use Supabase).")
    return backend


_override: StorageBackend | None = None


def get_backend() -> StorageBackend:
    return _override or _configured_backend()


def set_backend(backend: StorageBackend | None) -> None:
    """Replace the backend (tests). ``None`` restores the configured one."""
    global _override
    _override = backend


# ---------------------------------------------------------------------------
# Public API used by the routes
# ---------------------------------------------------------------------------
def _read_limited(upload: UploadFile) -> bytes:
    limit = settings.max_upload_size_bytes
    chunks, size = [], 0
    while chunk := upload.file.read(READ_CHUNK):
        size += len(chunk)
        if size > limit:
            raise AppError(
                f"File exceeds the {limit // (1024 * 1024)} MB limit.",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def save_document(organization_id: int, upload: UploadFile) -> tuple[str, str, int]:
    """Validate and store an upload. Returns ``(storage_key, mime_type, size)``."""
    mime_type = (upload.content_type or "").split(";")[0].strip().lower()
    if mime_type not in settings.allowed_document_mime_types:
        allowed = ", ".join(settings.allowed_document_mime_types)
        raise AppError(f"Unsupported file type '{mime_type}'. Allowed: {allowed}.", status_code=415)

    data = _read_limited(upload)
    if not data:
        raise AppError("The uploaded file is empty.")
    signatures = _SIGNATURES.get(mime_type)
    if signatures and not data.startswith(signatures):
        raise AppError("The file content does not match its declared type.", status_code=415)

    storage_key = f"org-{int(organization_id)}/{secrets.token_hex(16)}{_EXTENSIONS.get(mime_type, '')}"
    backend = get_backend()
    try:
        backend.put(storage_key, data, mime_type)
    except AppError:
        raise
    except Exception as exc:
        logger.error("Upload of %s to %s storage failed: %s", storage_key, backend.name, type(exc).__name__)
        raise StorageUnavailable(UNAVAILABLE) from exc
    return storage_key, mime_type, len(data)


def read_document(storage_key: str) -> bytes:
    backend = get_backend()
    try:
        return backend.get(storage_key)
    except ObjectMissing as exc:
        raise NotFound(MISSING) from exc
    except AppError:
        raise
    except Exception as exc:
        logger.error("Download of %s from %s storage failed: %s", storage_key, backend.name, type(exc).__name__)
        raise StorageUnavailable(UNAVAILABLE) from exc


def delete_document(storage_key: str) -> None:
    """Best effort: the database row is already gone, so a failure here only
    leaves an orphaned private object, which is logged for clean-up."""
    backend = get_backend()
    try:
        backend.delete(storage_key)
    except Exception as exc:
        logger.warning(
            "Could not delete %s from %s storage (%s); remove it manually.",
            storage_key,
            backend.name,
            type(exc).__name__,
        )
