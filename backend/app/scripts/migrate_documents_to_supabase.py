"""Copy document files from the local upload directory to Supabase Storage.

    python -m app.scripts.migrate_documents_to_supabase            # dry run
    python -m app.scripts.migrate_documents_to_supabase --apply    # upload

Each ``organization_document`` row keeps its ``storage_key``: the file is
uploaded to the bucket under the same key, so no database row is changed.
Rows whose file is not on this machine's disk are listed and left alone
(their download returns "missing from storage" until the organization
uploads the document again). Objects already in the bucket are skipped.

Needs DATABASE_URL, SUPABASE_URL and SUPABASE_SECRET_KEY, and UPLOAD_DIR
pointing at the folder that holds the files.
"""

import argparse
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import OrganizationDocument
from app.services import storage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Upload (default is a dry run)")
    args = parser.parse_args()

    if not (settings.supabase_url and settings.supabase_secret_key):
        print("SUPABASE_URL and SUPABASE_SECRET_KEY must be set.", file=sys.stderr)
        return 1
    local = storage.LocalBackend(settings.upload_dir)
    remote = storage.SupabaseBackend(storage.create_supabase_client(), settings.supabase_bucket_name)

    copied = present = missing = failed = 0
    with SessionLocal() as db:
        documents = db.scalars(select(OrganizationDocument).order_by(OrganizationDocument.document_id)).all()
        for d in documents:
            try:
                remote.get(d.storage_key)
                present += 1
                continue
            except storage.ObjectMissing:
                pass
            try:
                data = local.get(d.storage_key)
            except storage.ObjectMissing:
                missing += 1
                print(f"missing locally: document {d.document_id} ({d.storage_key})")
                continue
            if not args.apply:
                copied += 1
                print(f"would upload: document {d.document_id} ({d.storage_key}, {len(data)} bytes)")
                continue
            try:
                remote.put(d.storage_key, data, d.mime_type)
                copied += 1
                print(f"uploaded: document {d.document_id} ({d.storage_key})")
            except Exception as exc:
                failed += 1
                print(f"FAILED: document {d.document_id} ({type(exc).__name__})")

    verb = "uploaded" if args.apply else "to upload"
    print(f"\n{len(documents)} documents: {copied} {verb}, {present} already in Supabase, "
          f"{missing} missing locally, {failed} failed.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to upload.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
