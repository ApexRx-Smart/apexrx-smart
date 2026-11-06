"""Check the document storage configuration end to end.

    python -m app.scripts.check_storage

Uses the same settings as the API (environment, otherwise backend/.env). For
Supabase it confirms that the bucket exists and is private, then uploads,
downloads and deletes a small dummy PDF under ``healthcheck/`` (a PDF because
the bucket may restrict uploads to the document types). No secret
is printed.
"""

import secrets
import sys

from app.core.config import settings
from app.services import storage


def main() -> int:
    backend = storage.get_backend()
    print(f"Storage backend: {backend.name}")
    if isinstance(backend, storage.SupabaseBackend):
        print(f"Bucket: {backend.bucket}")
        try:
            bucket = backend.client.get_bucket(backend.bucket)
        except Exception as exc:
            print(f"FAILED: cannot read the bucket ({type(exc).__name__}: {getattr(exc, 'message', exc)})")
            return 1
        if bucket.public:
            print("FAILED: the bucket is PUBLIC. Make it private in the Supabase dashboard.")
            return 1
        print("Bucket is private: OK")
    elif settings.document_storage != "local":
        print("Note: Supabase is not configured (SUPABASE_URL / SUPABASE_SECRET_KEY), so local disk is used.")

    key = f"healthcheck/{secrets.token_hex(16)}.pdf"
    payload = b"%PDF-1.4\n% ApexRx storage check (dummy)\n%%EOF\n"
    try:
        backend.put(key, payload, "application/pdf")
        ok = backend.get(key) == payload
    except Exception as exc:
        print(f"FAILED: round trip error ({type(exc).__name__}: {getattr(exc, 'message', exc)})")
        return 1
    finally:
        try:
            backend.delete(key)
            try:
                backend.get(key)
                print(f"Warning: {key} is still in storage; remove it manually.")
            except storage.ObjectMissing:
                print(f"Dummy file {key} deleted: OK")
        except Exception:
            print(f"Warning: could not delete {key}; remove it manually.")
    print("Upload, download and delete: OK" if ok else "FAILED: downloaded content differs")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
