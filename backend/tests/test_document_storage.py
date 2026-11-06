"""Verification documents stored through the Supabase backend, using an
in-memory fake of the official storage3 client (see conftest.fake_bucket).
Only dummy file contents are used."""

import io
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from tests.helpers import admin, organization, user

PDF = b"%PDF-1.4\n% dummy test document, not a real license\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
KEY = re.compile(r"^org-(\d+)/[0-9a-f]{32}\.(pdf|png|jpg)$")


def _upload(client, headers, org_id, content=PDF, name="license.pdf", mime="application/pdf"):
    return client.post(
        f"/organizations/{org_id}/documents",
        data={"document_type": "pharmacy_license"},
        files={"file": (name, io.BytesIO(content), mime)},
        headers=headers,
    )


def _rows(org_id):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT document_id, storage_key, file_name, mime_type, file_size_bytes, verification_status "
                "FROM organization_document WHERE organization_id = :id ORDER BY document_id"
            ),
            {"id": org_id},
        ).all()


@pytest.fixture
def setup(client, fake_bucket):
    owner = user(client, "owner@x.example.com")
    org_id = organization(client, owner, "pharmacy", "Docs Pharmacy")
    return {"owner": owner, "org": org_id, "admin": admin(client), "bucket": fake_bucket}


def test_upload_goes_to_supabase_with_metadata_in_postgres(client, setup):
    r = _upload(client, setup["owner"], setup["org"], name="../../etc/passwd.pdf")
    assert r.status_code == 201, r.text
    assert "storage_key" not in r.json()

    [row] = _rows(setup["org"])
    # Server-generated key scoped to the organization; the client's file name
    # is metadata only, with path components stripped.
    m = KEY.match(row.storage_key)
    assert m and int(m.group(1)) == setup["org"] and m.group(2) == "pdf"
    assert row.file_name == "passwd.pdf"
    assert (row.mime_type, row.file_size_bytes, row.verification_status) == ("application/pdf", len(PDF), "pending")

    assert set(setup["bucket"].objects) == {row.storage_key}
    data, options = setup["bucket"].objects[row.storage_key]
    assert data == PDF
    assert options["content-type"] == "application/pdf" and options["upsert"] == "false"
    assert setup["bucket"].buckets[-1] == "organization-documents"

    # A second upload never reuses a key.
    assert _upload(client, setup["owner"], setup["org"], content=PNG, name="id.png", mime="image/png").status_code == 201
    keys = [r.storage_key for r in _rows(setup["org"])]
    assert len(set(keys)) == 2 and keys[1].endswith(".png")


def test_admin_download_streams_the_file(client, setup):
    doc = _upload(client, setup["owner"], setup["org"], name="Licence Pharmacie é.pdf").json()
    r = client.get(f"/admin/documents/{doc['document_id']}/download", headers=setup["admin"])
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''Licence%20Pharmacie%20%C3%A9.pdf" in r.headers["content-disposition"]
    assert "supabase" not in str(r.headers).lower()

    # The organization's own manager can download it too.
    own = client.get(f"/organizations/{setup['org']}/documents/{doc['document_id']}/download", headers=setup["owner"])
    assert own.status_code == 200 and own.content == PDF


def test_other_users_cannot_download(client, setup):
    doc_id = _upload(client, setup["owner"], setup["org"]).json()["document_id"]
    org_path = f"/organizations/{setup['org']}/documents"

    outsider = user(client, "other@x.example.com")
    other_org = organization(client, outsider, "pharmacy", "Other Pharmacy")
    # Another organization's member: the organization is hidden (404) ...
    assert client.get(f"{org_path}/{doc_id}/download", headers=outsider).status_code == 404
    assert client.get(org_path, headers=outsider).status_code == 404
    # ... and the admin route needs platform admin rights (403).
    assert client.get(f"/admin/documents/{doc_id}/download", headers=outsider).status_code == 403
    assert client.get(f"/admin/documents/{doc_id}/download", headers=setup["owner"]).status_code == 403
    # Unauthenticated.
    assert client.get(f"/admin/documents/{doc_id}/download").status_code == 401
    assert client.get(f"{org_path}/{doc_id}/download").status_code == 401

    # Another organization's document id cannot be fetched through this organization.
    other_doc = _upload(client, outsider, other_org).json()["document_id"]
    assert client.get(f"{org_path}/{other_doc}/download", headers=setup["owner"]).status_code == 404


@pytest.mark.parametrize(
    ("content", "name", "mime", "expected"),
    [
        (b"MZ\x90\x00 executable", "tool.exe", "application/octet-stream", 415),
        (b"<html>not a pdf</html>", "fake.pdf", "application/pdf", 415),
        (b"%PDF-1.4 but declared png", "fake.png", "image/png", 415),
        (b"", "empty.pdf", "application/pdf", 400),
    ],
)
def test_invalid_files_are_rejected_and_not_stored(client, setup, content, name, mime, expected):
    r = _upload(client, setup["owner"], setup["org"], content=content, name=name, mime=mime)
    assert r.status_code == expected, r.text
    assert _rows(setup["org"]) == []
    assert setup["bucket"].objects == {}


def test_oversized_upload_is_rejected(client, setup, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    r = _upload(client, setup["owner"], setup["org"], content=PDF + b"0" * 2048)
    assert r.status_code == 413
    assert _rows(setup["org"]) == [] and setup["bucket"].objects == {}
    # Exactly at the limit is accepted.
    exact = PDF + b"0" * (1024 - len(PDF))
    assert _upload(client, setup["owner"], setup["org"], content=exact).status_code == 201


def test_only_managers_can_upload(client, setup):
    stranger = user(client, "stranger@x.example.com")
    assert _upload(client, stranger, setup["org"]).status_code == 404
    assert _upload(client, {}, setup["org"]).status_code == 401
    assert setup["bucket"].objects == {}


def test_supabase_outage_is_handled(client, setup):
    doc = _upload(client, setup["owner"], setup["org"]).json()

    setup["bucket"].fail = True
    r = _upload(client, setup["owner"], setup["org"], name="second.pdf")
    assert r.status_code == 503
    assert "temporarily unavailable" in r.json()["detail"]
    assert len(_rows(setup["org"])) == 1  # no metadata row for the failed upload

    assert client.get(f"/admin/documents/{doc['document_id']}/download", headers=setup["admin"]).status_code == 503
    # Listing and reviewing do not depend on the storage service.
    assert client.get(f"/admin/organizations/{setup['org']}", headers=setup["admin"]).status_code == 200

    setup["bucket"].fail = False
    assert client.get(f"/admin/documents/{doc['document_id']}/download", headers=setup["admin"]).status_code == 200


def test_missing_object_returns_clear_404(client, setup):
    """Records whose file is not in the bucket (e.g. uploaded to the old local
    disk) stay intact and report the file as missing."""
    doc = _upload(client, setup["owner"], setup["org"]).json()
    setup["bucket"].objects.clear()
    r = client.get(f"/admin/documents/{doc['document_id']}/download", headers=setup["admin"])
    assert r.status_code == 404
    assert "missing from storage" in r.json()["detail"]
    assert len(_rows(setup["org"])) == 1
    # It can still be reviewed, e.g. rejected so the organization uploads it again.
    r = client.post(
        f"/admin/documents/{doc['document_id']}/review",
        json={"decision": "rejected", "rejection_reason": "File missing, please upload again"},
        headers=setup["admin"],
    )
    assert r.status_code == 200


def test_deleting_a_pending_document_removes_the_object(client, setup):
    doc = _upload(client, setup["owner"], setup["org"]).json()
    assert len(setup["bucket"].objects) == 1
    r = client.delete(f"/organizations/{setup['org']}/documents/{doc['document_id']}", headers=setup["owner"])
    assert r.status_code == 200
    assert setup["bucket"].objects == {} and _rows(setup["org"]) == []


def test_delete_succeeds_even_if_storage_cleanup_fails(client, setup):
    doc = _upload(client, setup["owner"], setup["org"]).json()
    setup["bucket"].fail = True
    r = client.delete(f"/organizations/{setup['org']}/documents/{doc['document_id']}", headers=setup["owner"])
    assert r.status_code == 200
    assert _rows(setup["org"]) == []
