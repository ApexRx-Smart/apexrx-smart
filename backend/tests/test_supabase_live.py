"""Optional round trip against the real Supabase bucket.

Skipped unless SUPABASE_LIVE_TESTS=1 and SUPABASE_URL / SUPABASE_SECRET_KEY are
set (environment or backend/.env). It uploads a dummy PDF under a random
``test-<hex>/`` prefix, downloads it, checks the bucket is private, and deletes
the object. Nothing else in the bucket is touched.
"""

import os
import secrets

import pytest
from storage3.exceptions import StorageApiError

from app.core.config import settings
from app.services import storage

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPABASE_LIVE_TESTS") != "1"
    or not (settings.supabase_url and settings.supabase_secret_key),
    reason="set SUPABASE_LIVE_TESTS=1 and the SUPABASE_* variables to run",
)

PDF = b"%PDF-1.4\n% ApexRx live storage test (dummy)\n%%EOF\n"


def test_live_round_trip():
    client = storage.create_supabase_client()
    backend = storage.SupabaseBackend(client, settings.supabase_bucket_name)
    assert client.get_bucket(settings.supabase_bucket_name).public is False

    key = f"test-{secrets.token_hex(8)}/{secrets.token_hex(16)}.pdf"
    try:
        backend.put(key, PDF, "application/pdf")
        assert backend.get(key) == PDF
        with pytest.raises(StorageApiError):  # never overwrites
            backend.put(key, PDF, "application/pdf")
    finally:
        backend.delete(key)
    with pytest.raises(storage.ObjectMissing):
        backend.get(key)
