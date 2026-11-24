"""Pharmacy and supplier applications: required licences, submission,
administrator approval, and what pending, rejected and suspended businesses
can reach.

  registration started -> documents uploaded -> submitted (awaiting review)
  -> approved / rejected / suspended

The documents go through the real upload endpoint, into the fake Supabase
bucket (no network); the dummy PDFs are labelled as test files."""

import io

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.helpers import admin, location, organization, user

PDF = b"%PDF-1.4\n% dummy test document, not a real licence\n%%EOF\n"
REQUIRED = {"pharmacy": ["pharmacy_license", "business_license", "owner_id"], "supplier": ["business_license", "owner_id"]}


def upload(client, headers, org_id, doc_type, content=PDF, name="licence.pdf", mime="application/pdf"):
    return client.post(f"/organizations/{org_id}/documents", data={"document_type": doc_type},
                       files={"file": (name, io.BytesIO(content), mime)}, headers=headers)


def application(client, headers, org_id):
    r = client.get(f"/organizations/{org_id}/application", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def submit(client, headers, org_id):
    return client.post(f"/organizations/{org_id}/submit", headers=headers)


def review(client, adm, org_id, decision, notes=None):
    return client.post(f"/admin/organizations/{org_id}/review", json={"decision": decision, "notes": notes},
                       headers=adm)


def review_document(client, adm, doc_id, decision, reason=None):
    r = client.post(f"/admin/documents/{doc_id}/review", json={"decision": decision, "rejection_reason": reason},
                    headers=adm)
    assert r.status_code == 200, r.text


@pytest.fixture
def biz(client, fake_bucket):
    """A new pharmacy and a new supplier, each with one branch, no documents yet."""
    out = {"admin": admin(client)}
    for kind in ("pharmacy", "supplier"):
        h = user(client, f"{kind}@apply.example.com", f"{kind.title()} Owner", account_type=kind)
        org = organization(client, h, kind, f"Apply {kind.title()}")
        location(client, h, org, "Main branch", -1.95, 30.06)
        out[kind] = (h, org)
    return out


def complete(client, biz, kind):
    h, org = biz[kind]
    for t in REQUIRED[kind]:
        assert upload(client, h, org, t).status_code == 201
    return h, org


@pytest.mark.parametrize("kind", ["pharmacy", "supplier"])
def test_a_new_registration_is_in_progress_with_its_required_documents_listed(client, biz, kind):
    h, org = biz[kind]
    app = application(client, h, org)
    assert app["stage"] == "in_progress" and app["status"] == "pending" and app["submitted_at"] is None
    assert [d["document_type"] for d in app["required_documents"]] == REQUIRED[kind]
    assert all(d["status"] == "missing" for d in app["required_documents"])
    assert app["documents_complete"] is False and app["can_submit"] is False and app["workspace_open"] is False


@pytest.mark.parametrize("kind", ["pharmacy", "supplier"])
def test_submission_is_refused_until_every_required_document_is_uploaded(client, biz, kind):
    h, org = biz[kind]
    r = submit(client, h, org)
    assert r.status_code == 409 and r.json()["code"] == "documents_missing"
    assert r.json()["missing"] == REQUIRED[kind]
    for t in REQUIRED[kind][:-1]:
        assert upload(client, h, org, t).status_code == 201
    r = submit(client, h, org)
    assert r.status_code == 409 and r.json()["missing"] == REQUIRED[kind][-1:]
    assert application(client, h, org)["stage"] == "in_progress"

    assert upload(client, h, org, REQUIRED[kind][-1]).status_code == 201
    r = submit(client, h, org)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "awaiting_review" and body["submitted_at"] and body["can_submit"] is False
    assert all(d["status"] == "pending" for d in body["required_documents"])
    # Once is enough.
    r = submit(client, h, org)
    assert r.status_code == 409 and r.json()["code"] == "already_submitted"


def test_only_the_registrations_own_document_types_are_accepted(client, biz):
    h, org = biz["supplier"]
    r = upload(client, h, org, "pharmacy_license")  # a supplier has no pharmacy licence
    assert r.status_code == 422 and r.json()["code"] == "invalid_document_type"
    assert upload(client, h, org, "made_up_type").status_code == 422
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM organization_document WHERE organization_id = :o"),
                         {"o": org}).scalar() == 0


@pytest.mark.parametrize("content,name,mime,expected", [
    (b"not a pdf at all", "licence.pdf", "application/pdf", 415),
    (b"", "empty.pdf", "application/pdf", 400),
    (PDF, "licence.exe", "application/x-msdownload", 415),
])
def test_invalid_files_do_not_count_as_uploaded(client, biz, content, name, mime, expected):
    h, org = biz["pharmacy"]
    assert upload(client, h, org, "owner_id", content, name, mime).status_code == expected
    assert next(d for d in application(client, h, org)["required_documents"]
                if d["document_type"] == "owner_id")["status"] == "missing"


def test_an_oversized_file_is_refused(client, biz, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    h, org = biz["pharmacy"]
    assert upload(client, h, org, "owner_id", PDF + b"0" * 2048).status_code == 413


def test_staff_cannot_submit(client, biz):
    h, org = complete(client, biz, "pharmacy")
    staff = user(client, "staff@apply.example.com", account_type="pharmacy")
    client.post(f"/organizations/{org}/members", json={"email": "staff@apply.example.com", "role": "staff"}, headers=h)
    assert submit(client, staff, org).status_code == 403
    assert application(client, staff, org)["stage"] == "in_progress"  # staff can see where it stands


def test_an_administrator_approves_only_a_submitted_application_with_approved_documents(client, biz):
    adm = biz["admin"]
    h, org = biz["pharmacy"]
    # Not submitted (no documents): cannot be approved.
    r = review(client, adm, org, "approved")
    assert r.status_code == 409 and r.json()["code"] == "not_submitted"
    complete(client, biz, "pharmacy")
    assert submit(client, h, org).status_code == 200
    # Documents still pending review.
    assert review(client, adm, org, "approved").status_code == 409
    docs = application(client, h, org)["required_documents"]
    for d in docs[:-1]:
        review_document(client, adm, d["document_id"], "approved")
    review_document(client, adm, docs[-1]["document_id"], "rejected", "The photo of the ID is unreadable.")
    r = review(client, adm, org, "approved")
    assert r.status_code == 409 and r.json()["code"] == "documents_not_approved" and "Owner ID" in r.json()["detail"]
    # The admin reviews a replacement.
    assert upload(client, h, org, "owner_id").status_code == 201
    replacement = next(d for d in application(client, h, org)["required_documents"] if d["document_type"] == "owner_id")
    assert replacement["status"] == "pending"
    review_document(client, adm, replacement["document_id"], "approved")
    assert review(client, adm, org, "approved").status_code == 200
    app = application(client, h, org)
    assert app["stage"] == "approved" and app["workspace_open"] is True


def _approved(client, biz, kind):
    adm = biz["admin"]
    h, org = complete(client, biz, kind)
    assert submit(client, h, org).status_code == 200
    for d in application(client, h, org)["required_documents"]:
        review_document(client, adm, d["document_id"], "approved")
    assert review(client, adm, org, "approved").status_code == 200
    return h, org


def operational(client, h, org, kind):
    """One read from each operational area, as the business's own member."""
    paths = [
        f"/organizations/{org}/inventory",
        f"/conversations?organization_id={org}",
        f"/conversations/contacts?organization_id={org}",
        f"/notifications?organization_id={org}",
        f"/purchase-orders?organization_id={org}",
        f"/procurement-requests?organization_id={org}",
        f"/organizations/{org}/insights",
    ]
    if kind == "pharmacy":
        paths.append(f"/organizations/{org}/reservations")
    return {p: client.get(p, headers=h) for p in paths}


@pytest.mark.parametrize("kind", ["pharmacy", "supplier"])
def test_pending_businesses_reach_only_their_application(client, biz, kind):
    h, org = complete(client, biz, kind)
    for stage in ("in_progress", "awaiting_review"):
        if stage == "awaiting_review":
            assert submit(client, h, org).status_code == 200
        results = operational(client, h, org, kind)
        refused = [p for p, r in results.items() if r.status_code == 403
                   and r.json().get("code") == "organization_not_approved"]
        # Every operational read is refused as "not approved" (none leaks data).
        assert refused == list(results), (stage, {p: r.status_code for p, r in results.items()})
        # What a pending business still uses: its application, profile, branches and documents.
        assert application(client, h, org)["stage"] == stage
        for path in (f"/organizations/{org}", f"/organizations/{org}/locations", f"/organizations/{org}/documents"):
            assert client.get(path, headers=h).status_code == 200, path


@pytest.mark.parametrize("kind", ["pharmacy", "supplier"])
def test_approved_businesses_reach_their_workspace(client, biz, kind):
    h, org = _approved(client, biz, kind)
    results = operational(client, h, org, kind)
    assert all(r.status_code in (200, 404) for r in results.values()), {p: r.status_code for p, r in results.items()}
    assert sum(r.status_code == 200 for r in results.values()) >= 5


def test_rejected_application_is_corrected_and_resubmitted(client, biz):
    adm = biz["admin"]
    h, org = complete(client, biz, "pharmacy")
    assert submit(client, h, org).status_code == 200
    docs = application(client, h, org)["required_documents"]
    review_document(client, adm, docs[0]["document_id"], "rejected", "This licence has expired.")
    assert review(client, adm, org, "rejected", "Your pharmacy licence has expired.").status_code == 200
    app = application(client, h, org)
    assert app["stage"] == "rejected" and app["review_notes"] == "Your pharmacy licence has expired."
    assert app["required_documents"][0]["status"] == "rejected"
    assert app["required_documents"][0]["rejection_reason"] == "This licence has expired."
    assert app["can_submit"] is False  # the rejected licence must be replaced first
    for r in operational(client, h, org, "pharmacy").values():
        assert r.status_code in (403, 404)
    r = submit(client, h, org)
    assert r.status_code == 409 and r.json()["missing"] == ["pharmacy_license"]
    assert upload(client, h, org, "pharmacy_license").status_code == 201
    r = submit(client, h, org)
    assert r.status_code == 200 and r.json()["stage"] == "awaiting_review" and r.json()["status"] == "pending"


def test_suspended_business_is_blocked_and_existing_records_are_kept(client, biz):
    adm = biz["admin"]
    h, org = _approved(client, biz, "supplier")
    before = client.get(f"/organizations/{org}/locations", headers=h).json()
    assert review(client, adm, org, "suspended", "Licence under investigation.").status_code == 200
    app = application(client, h, org)
    assert app["stage"] == "suspended" and app["review_notes"] == "Licence under investigation."
    assert app["can_submit"] is False and app["workspace_open"] is False
    assert submit(client, h, org).status_code == 409
    for path, r in operational(client, h, org, "supplier").items():
        assert r.status_code in (403, 404), path
    assert client.get(f"/organizations/{org}/locations", headers=h).json() == before
    # Reinstating reviews nothing new.
    assert review(client, adm, org, "approved").status_code == 200
    assert application(client, h, org)["workspace_open"] is True


def test_admin_overview_separates_submitted_from_in_progress(client, biz):
    adm = biz["admin"]
    h, org = complete(client, biz, "pharmacy")
    assert submit(client, h, org).status_code == 200
    counts = client.get("/admin/organizations/counts", headers=adm).json()
    assert counts["pending"] == 2 and counts["awaiting_review"] == 1 and counts["in_progress"] == 1
    waiting = client.get("/admin/organizations", params={"stage": "awaiting_review"}, headers=adm).json()
    assert [o["organization_id"] for o in waiting["items"]] == [org] and waiting["items"][0]["submitted_at"]
    started = client.get("/admin/organizations", params={"stage": "in_progress"}, headers=adm).json()
    assert [o["organization_id"] for o in started["items"]] == [biz["supplier"][1]]


def test_other_users_cannot_read_an_application(client, biz):
    _, org = biz["pharmacy"]
    stranger = user(client, "stranger@apply.example.com", account_type="pharmacy")
    assert client.get(f"/organizations/{org}/application", headers=stranger).status_code == 404
    assert client.post(f"/organizations/{org}/submit", headers=stranger).status_code == 404
    # Administrators can read it.
    assert client.get(f"/organizations/{org}/application", headers=biz["admin"]).status_code == 200


def test_support_contact_is_configurable_and_empty_by_default(client, monkeypatch):
    from app.core.config import settings
    assert client.get("/auth/capabilities").json()["support_contact"] == {"email": None, "phone": None}
    monkeypatch.setattr(settings, "support_contact_email", "help@example.com")
    assert client.get("/auth/capabilities").json()["support_contact"]["email"] == "help@example.com"
