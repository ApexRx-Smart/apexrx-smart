"""The registration profile the frontend collects, end to end through the API:
organization type, contact phone, structured Rwandan address, coordinates and
documents. Everything sent is stored and read back (nothing silently dropped)."""

import pytest

from tests.helpers import admin, organization, user

PDF = b"%PDF-1.4\n% test document\n%%EOF\n"
ADDRESS = {
    "name": "Kimironko branch",
    "address": "KG 11 Ave, near the market",
    "region": "Kigali",
    "city": "Gasabo",
    "sector": "Kimironko",
    "cell": "Bibare",
    "village": "Imena",
    "latitude": -1.949,
    "longitude": 30.126,
    "phone": "+250788123456",
    "whatsapp_phone": "+250788123456",
}


@pytest.mark.parametrize("type_", ["pharmacy", "supplier"])
def test_full_registration_profile_is_persisted(client, type_):
    h = user(client, f"profile-{type_}@x.example.com")
    org_id = organization(client, h, type_, f"Profile {type_.title()}")
    assert client.get(f"/organizations/{org_id}", headers=h).json()["type"] == type_

    r = client.post(f"/organizations/{org_id}/locations", json=ADDRESS, headers=h)
    assert r.status_code == 201, r.text
    loc = r.json()
    for key in ("address", "region", "city", "sector", "cell", "village", "phone", "whatsapp_phone"):
        assert loc[key] == ADDRESS[key]
    assert float(loc["latitude"]) == ADDRESS["latitude"] and float(loc["longitude"]) == ADDRESS["longitude"]

    # Editing one level keeps the others.
    r = client.patch(f"/organizations/{org_id}/locations/{loc['location_id']}",
                     json={"village": "Ubumwe"}, headers=h)
    assert r.status_code == 200 and r.json()["village"] == "Ubumwe" and r.json()["sector"] == "Kimironko"
    (listed,) = client.get(f"/organizations/{org_id}/locations", headers=h).json()
    assert listed["cell"] == "Bibare" and listed["village"] == "Ubumwe"


def test_address_parts_are_optional_and_length_checked(client):
    h = user(client, "addr@x.example.com")
    org_id = organization(client, h, "pharmacy", "Address Checks")
    r = client.post(f"/organizations/{org_id}/locations", json={"name": "Bare"}, headers=h)
    assert r.status_code == 201 and r.json()["sector"] is None
    r = client.post(f"/organizations/{org_id}/locations", json={"name": "Long", "sector": "x" * 101}, headers=h)
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("raw", "stored"),
    [("0788 123 456", "+250788123456"), ("+250 788 123 456", "+250788123456"), ("0252 123 456", "+250252123456")],
)
def test_contact_phone_is_normalized(client, raw, stored):
    h = user(client, "phone@x.example.com")
    org_id = organization(client, h, "supplier", "Phone Supplies")
    r = client.patch(f"/organizations/{org_id}", json={"phone": raw}, headers=h)
    assert r.status_code == 200 and r.json()["phone"] == stored


def test_invalid_contact_phone_is_rejected(client):
    h = user(client, "badphone@x.example.com")
    org_id = organization(client, h, "pharmacy", "Bad Phone Pharmacy")
    r = client.patch(f"/organizations/{org_id}", json={"phone": "0788 12"}, headers=h)
    assert r.status_code == 422 and "not a valid phone number" in r.json()["detail"]
    r = client.patch(f"/organizations/{org_id}", json={"phone": None}, headers=h)
    assert r.status_code == 200 and r.json()["phone"] is None


@pytest.mark.parametrize("type_", ["pharmacy", "supplier"])
def test_documents_upload_and_retrieval_after_registration(client, type_):
    h = user(client, f"docs-{type_}@x.example.com")
    org_id = organization(client, h, type_, f"Docs {type_.title()}")
    doc_types = ["pharmacy_license", "business_license", "owner_id"] if type_ == "pharmacy" else [
        "business_license", "owner_id"]
    for doc_type in doc_types:
        r = client.post(f"/organizations/{org_id}/documents", data={"document_type": doc_type},
                        files={"file": (f"{doc_type}.pdf", PDF, "application/pdf")}, headers=h)
        assert r.status_code == 201, r.text
    docs = client.get(f"/organizations/{org_id}/documents", headers=h).json()
    assert sorted(d["document_type"] for d in docs) == sorted(doc_types)
    assert all(d["verification_status"] == "pending" for d in docs)

    first = docs[0]["document_id"]
    r = client.get(f"/organizations/{org_id}/documents/{first}/download", headers=h)
    assert r.status_code == 200 and r.content == PDF
    a = admin(client)
    assert client.get(f"/admin/documents/{first}/download", headers=a).content == PDF
    # Another account cannot read them.
    other = user(client, f"other-{type_}@x.example.com")
    assert client.get(f"/organizations/{org_id}/documents", headers=other).status_code == 404
