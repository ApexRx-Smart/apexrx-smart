"""Reservation API and security (Phase 2): patient, pharmacy, catalogue
settings and branch acknowledgement endpoints, over the Phase 1 engine.

Local *_test database only (see conftest). Concurrency tests use real
separate HTTP requests from threads, each with its own database session.
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.core.rate_limit import reservation_limiter
from tests.helpers import approve, location, organization, user
from tests.reservation_support import PHONE, ResWorld, backdate, rows, scalar

REFERENCE = re.compile(r"^RX-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{10}$")
# Keys that must never appear in a patient-facing or public response.
INTERNAL_KEYS = {
    "reservation_id", "patient_user_id", "status_changed_by", "responded_by", "collected_by",
    "correction_adjustment_id", "deduction_adjustment_id", "collected_xid", "client_request_id",
    "status_source", "pharmacy_organization_id",
}


@pytest.fixture
def w(client):
    return ResWorld(client)


def keys(value) -> set[str]:
    """Every key in a JSON document, at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def unit_version(product) -> int:
    return scalar("SELECT unit_version FROM product WHERE product_id = :p", p=product)


def body(w, product=None, quantity=2, branch=None, request_id=None, **extra):
    product = product or w.product
    data = {
        "location_id": branch or w.branch,
        "product_id": product,
        "quantity": quantity,
        "unit_version": unit_version(product),
        "client_request_id": str(request_id or uuid.uuid4()),
        "contact_phone": PHONE,
    }
    data.update(extra)
    return {k: v for k, v in data.items() if v is not ...}


def submit(w, patient=None, **kwargs):
    return w.client.post("/reservations", json=body(w, **kwargs), headers=w.headers[patient or w.patient])


def reserve(w, patient=None, **kwargs) -> str:
    r = submit(w, patient, **kwargs)
    assert r.status_code == 201, r.text
    return r.json()["reference"]


def pharmacy(w, reference="", action=None, by=None, org=None, **kwargs):
    path = f"/organizations/{org or w.org}/reservations"
    if reference:
        path += f"/{reference}"
    if action:
        path += f"/{action}"
        if action == "collect" and "raw" not in kwargs:
            # Staff type the reference the patient shows; tests of that rule pass raw=True.
            kwargs["json"] = {"reference": reference, **(kwargs.get("json") or {})}
        kwargs.pop("raw", None)
        return w.client.post(path, headers=w.headers[by or w.staff], **kwargs)
    return w.client.get(path, headers=w.headers[by or w.staff], **kwargs)


def confirm(w, reference, by=None):
    r = pharmacy(w, reference, "confirm", by)
    assert r.status_code == 200, r.text
    return r.json()


def db_count(sql, **params) -> int:
    return scalar(sql, **params)


# ---------------------------------------------------------------------------
# Authentication and route inventory
# ---------------------------------------------------------------------------
def test_every_reservation_endpoint_requires_authentication(w):
    ref = reserve(w)
    org, loc, prod = w.org, w.branch, w.product
    endpoints = [
        ("post", "/reservations"),
        ("get", "/reservations"),
        ("get", f"/reservations/{ref}"),
        ("post", f"/reservations/{ref}/cancel"),
        ("get", f"/organizations/{org}/reservations"),
        ("get", f"/organizations/{org}/reservations/{ref}"),
        ("post", f"/organizations/{org}/reservations/{ref}/confirm"),
        ("post", f"/organizations/{org}/reservations/{ref}/decline"),
        ("post", f"/organizations/{org}/reservations/{ref}/cancel"),
        ("post", f"/organizations/{org}/reservations/{ref}/collect"),
        ("get", f"/organizations/{org}/locations/{loc}/reservation-units"),
        ("get", f"/organizations/{org}/locations/{loc}/products/{prod}/unit-acknowledgement"),
        ("post", f"/organizations/{org}/locations/{loc}/products/{prod}/unit-acknowledgement"),
        ("get", f"/catalogue/products/{prod}/reservation-settings"),
        ("patch", f"/catalogue/products/{prod}/reservation-settings"),
        ("get", f"/catalogue/products/{prod}/reservation-settings/history"),
    ]
    for method, path in endpoints:
        r = getattr(w.client, method)(path, headers={"Authorization": "Bearer not-a-token"})
        assert r.status_code == 401, (method, path, r.status_code)
        r = w.client.request(method.upper(), path)
        assert r.status_code == 401, (method, path, r.status_code)
    assert w.status(scalar("SELECT reservation_id FROM reservation")) == "requested"
    # Options work signed out (public search), but a bad token is still refused.
    path = f"/reservations/options?location_id={loc}&product_id={prod}"
    anonymous = w.client.get(path)
    assert anonymous.status_code == 200 and anonymous.json()["reservable"] is True
    assert w.client.get(path, headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_only_the_expected_reservation_routes_exist(client):
    """No system-only operation (expiry, suspension cancellation) and no
    trigger bypass is reachable over HTTP."""
    paths = {p: set(ops) for p, ops in client.app.openapi()["paths"].items()
             if "reservation" in p or "unit-acknowledgement" in p}
    assert paths == {
        "/reservations": {"get", "post"},
        "/reservations/options": {"get"},
        "/reservations/{reference}": {"get"},
        "/reservations/{reference}/cancel": {"post"},
        "/organizations/{organization_id}/reservations": {"get"},
        "/organizations/{organization_id}/reservations/{reference}": {"get"},
        "/organizations/{organization_id}/reservations/{reference}/confirm": {"post"},
        "/organizations/{organization_id}/reservations/{reference}/decline": {"post"},
        "/organizations/{organization_id}/reservations/{reference}/cancel": {"post"},
        "/organizations/{organization_id}/reservations/{reference}/collect": {"post"},
        "/organizations/{organization_id}/locations/{location_id}/reservation-units": {"get"},
        "/organizations/{organization_id}/locations/{location_id}/products/{product_id}/unit-acknowledgement": {
            "get", "post"
        },
        "/catalogue/products/{product_id}/reservation-settings": {"get", "patch"},
        "/catalogue/products/{product_id}/reservation-settings/history": {"get"},
    }
    assert not any(word in p for p in paths for word in ("expire", "suspend", "system", "xid", "trigger"))


def test_system_operations_cannot_be_invoked(w):
    ref = reserve(w)
    patient = w.headers[w.patient]
    for path in ("/reservations/expire", "/reservations/expire-due", f"/reservations/{ref}/expire",
                 f"/organizations/{w.org}/reservations/expire", f"/organizations/{w.org}/reservations/{ref}/expire"):
        assert w.client.post(path, headers=patient).status_code in (404, 405), path
        assert w.client.post(path, headers=w.headers[w.owner]).status_code in (404, 405), path
    # A patient cannot record a pharmacy or system transition on their own reservation.
    for action, payload in (("confirm", None), ("decline", {"reason": "x"}), ("collect", {"reference": ref})):
        r = w.client.post(f"/organizations/{w.org}/reservations/{ref}/{action}", headers=patient, json=payload)
        assert r.status_code == 404, (action, r.text)
    assert w.status(scalar("SELECT reservation_id FROM reservation")) == "requested"


# ---------------------------------------------------------------------------
# Patient: submission
# ---------------------------------------------------------------------------
def test_submit_returns_the_reservation_and_retries_are_idempotent(w):
    request_id = uuid.uuid4()
    r = submit(w, request_id=request_id, note="  Collecting after work  ")
    assert r.status_code == 201, r.text
    data = r.json()
    assert REFERENCE.match(data["reference"])
    assert data["status"] == "requested" and data["can_cancel"] is True
    assert data["quantity"] == 2 and data["unit"] == {
        "unit_version": unit_version(w.product), "stock_unit": "pack", "unit_label": "box", "pack_size": "20 tablets"
    }
    assert data["unit_price"] == "500.00" and data["currency"] == "RWF"
    assert data["contact_phone"] == "+250788123456" and data["note"] == "Collecting after work"
    assert data["respond_by"] > data["submitted_at"] and data["collect_by"] is None
    assert data["branch"]["pharmacy_name"] == "Kigali Pharmacy" and data["branch"]["name"] == "Downtown"
    assert [h["to_status"] for h in data["history"]] == ["requested"]
    assert not keys(data) & INTERNAL_KEYS

    retry = submit(w, request_id=request_id)
    assert retry.status_code == 200 and retry.json()["reference"] == data["reference"]
    assert db_count("SELECT count(*) FROM reservation") == 1
    assert db_count("SELECT count(*) FROM notification WHERE kind = 'reservation_requested'") == 1

    reused = submit(w, request_id=request_id, quantity=3)
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key_reused"


def test_concurrent_retries_create_one_reservation(w):
    payload = body(w)
    headers = w.headers[w.patient]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: w.client.post("/reservations", json=payload, headers=headers), range(4)))
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    assert len({r.json()["reference"] for r in results}) == 1
    assert db_count("SELECT count(*) FROM reservation") == 1


@pytest.mark.parametrize(
    "forged",
    [
        {"status": "confirmed"},
        {"status_source": "system"},
        {"patient_user_id": 1},
        {"status_changed_by": 1},
        {"unit_price": "1.00"},
        {"currency": "USD"},
        {"pharmacy_organization_id": 1},
        {"expires_at": "2099-01-01T00:00:00Z"},
        {"respond_by": "2099-01-01T00:00:00Z"},
        {"collected_xid": "1"},
        {"stock_quantity": 999},
        {"reference": "RX-AAAAAAAAAA"},
    ],
)
def test_submit_rejects_server_controlled_fields(w, forged):
    r = w.client.post("/reservations", json=body(w, **forged), headers=w.headers[w.patient])
    assert r.status_code == 422, r.text
    assert db_count("SELECT count(*) FROM reservation") == 0


def test_submit_validation_and_structured_errors(w):
    def code(r, status):
        assert r.status_code == status, r.text
        return r.json().get("code")

    assert code(submit(w, quantity=0), 422) is None
    assert code(submit(w, quantity=1001), 422) is None
    assert code(submit(w, unit_version=...), 422) is None
    assert code(submit(w, client_request_id="not-a-uuid"), 422) is None
    assert submit(w, product=999999, unit_version=1).status_code == 404
    assert submit(w, branch=999999).status_code == 404
    current = unit_version(w.product)
    assert code(submit(w, unit_version=current + 5), 409) == "unit_changed"
    stale = submit(w, unit_version=current - 1).json()
    assert (stale["code"], stale["unit_version"], stale["stock_unit"], stale["unit_label"]) == (
        "unit_changed", current, "pack", "box")
    r = submit(w, quantity=6)
    assert code(r, 409) == "quantity_above_limit" and r.json()["max_quantity"] == 5
    assert code(submit(w, contact_phone="call me"), 422) == "invalid_phone"
    assert db_count("SELECT count(*) FROM reservation") == 0


def test_phone_is_required_and_defaults_to_the_account_phone(w):
    r = submit(w, contact_phone=...)
    assert r.status_code == 422 and r.json()["code"] == "phone_required"
    r = w.client.patch("/auth/me", json={"phone": "0788 765 432"}, headers=w.headers[w.patient])
    assert r.status_code == 200, r.text
    r = submit(w, contact_phone=...)
    assert r.status_code == 201, r.text
    assert r.json()["contact_phone"] == "+250788765432"


def test_ineligible_medicines_are_refused_with_a_reason(w):
    unacknowledged = w.medicine("Ibuprofen", "Brufen 200mg", ack=False)
    disabled = w.medicine("Cetirizine", "Zyrtec 10mg")
    w.configure(disabled, reservation_enabled=False)
    prescription = w.medicine("Amoxicillin", "Amoxil 250mg", enable=False, ack=False)
    w.configure(prescription, dispensing_class="prescription_only", reservation_enabled=False)
    for product, reason in ((unacknowledged, "unit_not_acknowledged"), (disabled, "disabled"),
                            (prescription, "prescription_only")):
        r = submit(w, product=product)
        assert r.status_code == 409, r.text
        assert (r.json()["code"], r.json()["reason"]) == ("not_reservable", reason)
    # The branch of another product without a stock record.
    r = submit(w, branch=w.branch2)
    assert r.status_code == 409 and r.json()["reason"] in ("offer_unlisted", "unit_not_acknowledged")
    # Pharmacy staff cannot reserve at their own pharmacy.
    r = submit(w, patient=w.staff)
    assert r.status_code == 409 and r.json()["code"] == "own_pharmacy"
    assert db_count("SELECT count(*) FROM reservation") == 0


def test_options_show_eligibility_and_unit_without_quantities(w):
    def options(product, who=None):
        r = w.client.get(
            "/reservations/options", params={"location_id": w.branch, "product_id": product},
            headers=w.headers[who or w.patient],
        )
        assert r.status_code == 200, r.text
        return r.json()

    data = options(w.product)
    assert data["reservable"] is True and data["max_quantity"] == 5
    assert data["unit"]["unit_version"] == unit_version(w.product) and data["availability_status"] == "in_stock"
    assert not keys(data) & {"quantity", "recorded_quantity", "allocated_quantity", "available_to_reserve"}
    other = w.medicine("Ibuprofen", "Brufen 200mg", ack=False)
    data = options(other)
    assert (data["reservable"], data["reason"], data["max_quantity"]) == (False, "unit_not_acknowledged", None)
    assert options(w.product, w.staff)["reason"] == "own_pharmacy"
    anonymous = w.client.get("/reservations/options", params={"location_id": w.branch, "product_id": w.product}).json()
    assert anonymous["reservable"] is True and not keys(anonymous) & {"quantity", "allocated_quantity"}
    r = submit(w)
    assert r.status_code == 201
    again = submit(w)
    assert again.status_code == 409 and again.json()["code"] == "open_reservation_exists"
    assert again.json()["reference"] == r.json()["reference"] and "reservation_id" not in again.json()
    r = w.client.get("/reservations/options", params={"location_id": 999999, "product_id": w.product},
                     headers=w.headers[w.patient])
    assert r.status_code == 404


def test_submissions_are_rate_limited_but_retries_are_not(w):
    request_id = uuid.uuid4()
    reserve(w, request_id=request_id)
    for _ in range(reservation_limiter.limit):
        reservation_limiter.hit(str(w.patient))
    r = submit(w, product=w.medicine("Ibuprofen", "Brufen 200mg"))
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and "Retry-After" in r.headers
    assert submit(w, request_id=request_id).status_code == 200


def test_open_reservation_cap_comes_from_settings(w, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "reservation_max_open_per_patient", 1)
    reserve(w)
    r = submit(w, product=w.medicine("Ibuprofen", "Brufen 200mg"))
    assert r.status_code == 409 and r.json()["code"] == "too_many_open_reservations"


# ---------------------------------------------------------------------------
# Patient: listing, detail, isolation, cancellation, expiry
# ---------------------------------------------------------------------------
def test_patients_see_only_their_own_reservations(w):
    products = [w.product, w.medicine("Ibuprofen", "Brufen 200mg"), w.medicine("Cetirizine", "Zyrtec 10mg")]
    refs = [reserve(w, product=p) for p in products]
    other = reserve(w, patient=w.patient2)
    mine = w.headers[w.patient]

    page = w.client.get("/reservations", params={"limit": 2}, headers=mine).json()
    assert page["total"] == 3 and [i["reference"] for i in page["items"]] == refs[::-1][:2]
    page2 = w.client.get("/reservations", params={"limit": 2, "offset": 2}, headers=mine).json()
    assert [i["reference"] for i in page2["items"]] == [refs[0]]
    assert w.client.get("/reservations", params={"limit": 101}, headers=mine).status_code == 422

    w.client.post(f"/reservations/{refs[0]}/cancel", headers=mine)
    cancelled = w.client.get("/reservations", params={"status": "cancelled"}, headers=mine).json()
    assert [i["reference"] for i in cancelled["items"]] == [refs[0]]
    both = w.client.get("/reservations", params=[("status", "cancelled"), ("status", "requested")], headers=mine)
    assert both.json()["total"] == 3

    theirs = w.headers[w.patient2]
    assert [i["reference"] for i in w.client.get("/reservations", headers=theirs).json()["items"]] == [other]
    for ref in refs:
        assert w.client.get(f"/reservations/{ref}", headers=theirs).status_code == 404
        assert w.client.post(f"/reservations/{ref}/cancel", headers=theirs).status_code == 404
        # the same reference in lower case is still the same (normalised) and still hidden
        assert w.client.get(f"/reservations/{ref.lower()}", headers=theirs).status_code == 404
    assert w.client.get(f"/reservations/{refs[1]}", headers=mine).json()["status"] == "requested"
    assert w.client.get("/reservations/RX-0000000000", headers=mine).status_code == 404
    assert w.client.get("/reservations/123", headers=mine).status_code == 422


def test_patient_cancellation_follows_the_engine_rules(w):
    ref = reserve(w)
    mine = w.headers[w.patient]
    r = w.client.post(f"/reservations/{ref}/cancel", json={"reason": "Found it elsewhere"}, headers=mine)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "cancelled" and data["can_cancel"] is False and data["closed_at"]
    assert data["cancel_reason"] == "Found it elsewhere"
    assert [(h["to_status"], h["by"]) for h in data["history"]] == [("requested", "patient"), ("cancelled", "patient")]
    assert w.client.post(f"/reservations/{ref}/cancel", headers=mine).status_code == 200  # repeat: no change
    assert db_count("SELECT count(*) FROM reservation_status_history") == 2
    assert w.client.post(f"/reservations/{ref}/cancel", json={"status": "collected"}, headers=mine).status_code == 422

    collected = reserve(w)
    confirm(w, collected)
    assert pharmacy(w, collected, "collect").status_code == 200
    r = w.client.post(f"/reservations/{collected}/cancel", headers=mine)
    assert r.status_code == 409 and r.json()["code"] == "reservation_state_conflict"


def test_expired_reservations_show_as_expired_and_cannot_be_cancelled(w):
    ref = reserve(w)
    backdate(scalar("SELECT reservation_id FROM reservation"))
    mine = w.headers[w.patient]
    data = w.client.get(f"/reservations/{ref}", headers=mine).json()
    assert data["status"] == "expired" and data["can_cancel"] is False and data["closed_at"]
    assert w.client.get("/reservations", params={"status": "expired"}, headers=mine).json()["total"] == 1
    assert w.client.get("/reservations", params={"status": "requested"}, headers=mine).json()["total"] == 0
    r = w.client.post(f"/reservations/{ref}/cancel", headers=mine)
    assert r.status_code == 409 and r.json()["code"] == "expired"
    assert w.status(scalar("SELECT reservation_id FROM reservation")) == "expired"  # recorded


def test_disabled_medicine_keeps_confirmed_reservations_collectable(w):
    ref = reserve(w)
    confirm(w, ref)
    assert w.client.patch(
        f"/catalogue/products/{w.product}/reservation-settings", json={"reservation_enabled": False},
        headers=w.admin_headers,
    ).status_code == 200
    assert submit(w, patient=w.patient2).json()["reason"] == "disabled"
    assert pharmacy(w, ref, "collect").json()["status"] == "collected"


def test_patient_view_hides_stock_and_override_details(w):
    ref = reserve(w, quantity=4)
    confirm(w, ref)
    w.set_stock(w.product, 1)
    override = {"verified_on_hand": 6, "recorded_quantity_seen": 1, "reason": "Counted the shelf twice",
                "physically_verified": True}
    r = pharmacy(w, ref, "collect", by=w.manager, json={"override": override})
    assert r.status_code == 200, r.text
    data = w.client.get(f"/reservations/{ref}", headers=w.headers[w.patient]).json()
    assert data["status"] == "collected"
    assert not keys(data) & ({"collection", "stock", "override", "override_reason", "verified_on_hand",
                              "recorded_quantity_seen", "recorded_quantity", "allocated_quantity"} | INTERNAL_KEYS)
    assert all(h["by_name"] is None for h in data["history"])


# ---------------------------------------------------------------------------
# Pharmacy: access control
# ---------------------------------------------------------------------------
def test_pharmacy_access_is_limited_to_active_members_of_the_handling_pharmacy(w, client):
    ref = reserve(w)
    # Non-members, including platform admins and patients: not found.
    for who in (w.outsider, w.patient, w.admin):
        assert pharmacy(w, by=who).status_code == 404
        assert pharmacy(w, ref, by=who).status_code == 404
        assert pharmacy(w, ref, "confirm", by=who).status_code == 404
    # Another approved pharmacy: its own list is empty and the reservation is hidden from it.
    other_owner = user(client, "owner@other.example.com", "Other Owner")
    other_org = organization(client, other_owner, "pharmacy", "Other Pharmacy")
    approve(client, w.admin_headers, other_org)
    w.headers["other"] = other_owner
    assert pharmacy(w, by="other", org=other_org).json()["total"] == 0
    for action in (None, "confirm", "decline", "cancel", "collect"):
        payload = {"json": {"reason": "nope"}} if action in ("decline", "cancel") else {}
        r = pharmacy(w, ref, action, by="other", org=other_org, **payload)
        assert r.status_code == 404, (action, r.text)
    # A supplier organization cannot use pharmacy reservation endpoints.
    supplier_owner = user(client, "owner@supplier.example.com", "Supplier")
    supplier = organization(client, supplier_owner, "supplier", "Supplier Ltd")
    approve(client, w.admin_headers, supplier)
    w.headers["supplier"] = supplier_owner
    assert pharmacy(w, by="supplier", org=supplier).status_code == 403
    # Inactive membership: no access at all.
    with engine.begin() as conn:
        conn.execute(text("UPDATE membership SET is_active = false WHERE user_id = :u"), {"u": w.staff})
    assert pharmacy(w, by=w.staff).status_code == 404
    assert pharmacy(w, ref, "confirm", by=w.staff).status_code == 404
    assert w.status(scalar("SELECT reservation_id FROM reservation")) == "requested"


def test_branch_filter_rejects_other_organizations_branches(w, client):
    other_owner = user(client, "owner@other.example.com", "Other Owner")
    other_org = organization(client, other_owner, "pharmacy", "Other Pharmacy")
    approve(client, w.admin_headers, other_org)
    other_branch = location(client, other_owner, other_org, "Elsewhere")
    reserve(w)
    assert pharmacy(w, params={"location_id": other_branch}).status_code == 404
    assert pharmacy(w, params={"location_id": w.branch2}).json()["total"] == 0
    assert pharmacy(w, params={"location_id": w.branch}).json()["total"] == 1
    for path in (f"/organizations/{w.org}/locations/{other_branch}/reservation-units",
                 f"/organizations/{w.org}/locations/{other_branch}/products/{w.product}/unit-acknowledgement"):
        assert client.get(path, headers=w.owner_headers).status_code == 404
    r = client.post(
        f"/organizations/{w.org}/locations/{other_branch}/products/{w.product}/unit-acknowledgement",
        json={"unit_version": 1, "stock_unit": "pack", "unit_label": "box", "pack_size": "20 tablets"},
        headers=w.owner_headers,
    )
    assert r.status_code == 404


def test_role_permissions_for_pharmacy_actions(w):
    first, second, third = (reserve(w, product=p) for p in
                            (w.product, w.medicine("Ibuprofen", "Brufen 200mg"), w.medicine("Cetirizine", "Zyrtec 10mg")))
    confirm(w, first, by=w.staff)
    r = pharmacy(w, first, "cancel", by=w.staff, json={"reason": "Out of stock"})
    assert r.status_code == 403
    r = pharmacy(w, first, "cancel", by=w.manager, json={"reason": ""})
    assert r.status_code == 422
    r = pharmacy(w, first, "cancel", by=w.manager, json={"reason": "Damaged packs"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    assert pharmacy(w, second, "decline", by=w.staff, json={}).status_code == 422
    r = pharmacy(w, second, "decline", by=w.staff, json={"reason": "Not in stock today"})
    assert r.status_code == 200 and r.json()["decline_reason"] == "Not in stock today"
    r = pharmacy(w, second, "cancel", by=w.owner, json={"reason": "Too late"})
    assert r.status_code == 409 and r.json()["code"] == "reservation_state_conflict"

    detail = pharmacy(w, third, by=w.staff).json()
    assert detail["actions"] == ["confirm", "decline"]
    confirm(w, third, by=w.owner)
    assert pharmacy(w, third, by=w.staff).json()["actions"] == ["collect"]
    assert pharmacy(w, third, by=w.manager).json()["actions"] == ["collect", "cancel", "override"]
    override = {"verified_on_hand": 5, "recorded_quantity_seen": 10, "reason": "Counted the shelf twice",
                "physically_verified": True}
    assert pharmacy(w, third, "collect", by=w.staff, json={"override": override}).status_code == 403


def test_forged_fields_are_rejected_on_pharmacy_actions(w):
    ref = reserve(w)
    for extra in ({"status": "collected"}, {"actor_id": w.owner}, {"status_changed_by": w.owner},
                  {"collected_xid": "1"}, {"deduction_adjustment_id": 1}):
        assert pharmacy(w, ref, "decline", json={"reason": "No", **extra}).status_code == 422
        assert pharmacy(w, ref, "collect", json=extra).status_code == 422
    r = pharmacy(w, ref, "collect", by=w.manager, json={"override": {
        "verified_on_hand": 5, "recorded_quantity_seen": 10, "reason": "Counted it carefully",
        "physically_verified": True, "override_by": w.staff}})
    assert r.status_code == 422
    assert w.status(scalar("SELECT reservation_id FROM reservation")) == "requested"
    # The actor recorded is always the signed-in user.
    confirm(w, ref, by=w.staff)
    assert scalar("SELECT responded_by FROM reservation") == w.staff


# ---------------------------------------------------------------------------
# Pharmacy: listing, detail, phone privacy
# ---------------------------------------------------------------------------
def test_pharmacy_list_filters_ordering_and_phone_visibility(w):
    a = reserve(w)
    b = reserve(w, patient=w.patient2)
    page = pharmacy(w).json()
    assert page["total"] == 2 and [i["reference"] for i in page["items"]] == [b, a]
    item = page["items"][1]
    assert item["patient"] == {"name": "Patient One", "phone": "+250788123456"}
    assert item["respond_by"] and item["collect_by"] is None and item["location_name"] == "Downtown"
    assert not keys(page) & INTERNAL_KEYS

    assert pharmacy(w, params={"limit": 1, "offset": 1}).json()["items"][0]["reference"] == a
    assert pharmacy(w, params={"reference": a.lower()}).json()["total"] == 1
    assert pharmacy(w, params={"submitted_from": "2999-01-01T00:00:00Z"}).json()["total"] == 0
    assert pharmacy(w, params={"submitted_to": "2999-01-01T00:00:00Z"}).json()["total"] == 2
    assert pharmacy(w, params={"status": "bogus"}).status_code == 422

    confirm(w, a)
    assert [i["reference"] for i in pharmacy(w, params={"sort": "deadline"}).json()["items"]] == [b, a]
    pharmacy(w, b, "decline", json={"reason": "Not available"})
    closed = pharmacy(w, b).json()
    assert closed["status"] == "declined" and closed["patient"] == {"name": "Patient Two", "phone": None}
    assert pharmacy(w, params={"status": "confirmed"}).json()["items"][0]["patient"]["phone"] == "+250788123456"
    assert [i["reference"] for i in pharmacy(w, params={"sort": "deadline"}).json()["items"]] == [a, b]


def test_pharmacy_detail_shows_deadlines_history_and_allocation(w):
    ref = reserve(w, quantity=3)
    before = pharmacy(w, ref).json()
    assert before["stock"] == {
        "recorded_quantity": 10, "allocated_quantity": 0, "available_to_reserve": 10, "shortfall": 0,
        "last_updated": before["stock"]["last_updated"], "this_reservation_at_risk": False,
    }
    stock_updated = before["stock"]["last_updated"]
    data = confirm(w, ref, by=w.staff)
    assert data["respond_by"] != data["collect_by"] and data["collect_by"] > data["confirmed_at"]
    assert data["stock"]["allocated_quantity"] == 3 and data["stock"]["available_to_reserve"] == 7
    assert data["stock"]["last_updated"] == stock_updated  # confirming never touches the stock record
    assert [(h["to_status"], h["by"], h["by_name"]) for h in data["history"]] == [
        ("requested", "patient", None), ("confirmed", "pharmacy", "Staff")
    ]
    assert data["collection"] is None
    w.set_stock(w.product, 2)
    data = pharmacy(w, ref).json()
    assert data["stock"]["shortfall"] == 1 and data["stock"]["this_reservation_at_risk"] is True
    assert data["status"] == "confirmed"  # a shortfall never cancels a reservation by itself


def test_confirm_conflicts_are_structured_and_roll_back(w):
    big = reserve(w, quantity=5)
    other = reserve(w, quantity=5, patient=w.patient2)
    w.set_stock(w.product, 8)
    confirm(w, big)
    r = pharmacy(w, other, "confirm")
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    assert r.json()["available_to_reserve"] == 3
    assert db_count("SELECT count(*) FROM notification WHERE kind = 'reservation_confirmed'") == 1
    assert pharmacy(w, other).json()["status"] == "requested"

    w.configure(w.product, reservation_enabled=False)
    r = pharmacy(w, other, "confirm")
    assert r.status_code == 409 and (r.json()["code"], r.json()["reason"]) == ("not_reservable", "disabled")
    w.configure(w.product, reservation_enabled=True)

    backdate(scalar("SELECT reservation_id FROM reservation WHERE reference = :r", r=other))
    r = pharmacy(w, other, "confirm")
    assert r.status_code == 409 and r.json()["code"] == "expired"
    assert pharmacy(w, other).json()["status"] == "expired"


def test_confirmation_requires_a_current_acknowledgement(w):
    ref = reserve(w)
    # Remove the branch acknowledgement row the request relied on (direct SQL,
    # simulating data drift); confirmation must re-check it.
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("DELETE FROM offer_unit_acknowledgement"))
    r = pharmacy(w, ref, "confirm")
    assert r.status_code == 409 and r.json()["reason"] == "unit_not_acknowledged"


def test_concurrent_confirmations_over_http_never_overallocate(w):
    first = reserve(w, quantity=5)
    second = reserve(w, quantity=5, patient=w.patient2)
    w.set_stock(w.product, 8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: pharmacy(w, pair[0], "confirm", by=pair[1]), [(first, w.staff), (second, w.manager)]
        ))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert [r.json()["code"] for r in results if r.status_code == 409] == ["insufficient_stock"]
    assert db_count("SELECT coalesce(sum(quantity), 0) FROM reservation WHERE status = 'confirmed'") == 5


def test_collection_normal_insufficient_and_override(w):
    ref = reserve(w, quantity=4)
    confirm(w, ref)
    r = pharmacy(w, ref, "collect")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "collected" and w.stock_quantity() == 6
    assert data["collection"]["quantity"] == 4 and data["collection"]["override"] is False
    assert data["collection"]["collected_by_name"] == "Staff" and data["actions"] == []
    assert not keys(data) & INTERNAL_KEYS
    assert pharmacy(w, ref, "collect").status_code == 200  # repeat: unchanged
    assert w.stock_quantity() == 6

    short = reserve(w, quantity=4, patient=w.patient2)
    confirm(w, short)
    w.set_stock(w.product, 2)
    r = pharmacy(w, short, "collect")
    assert r.status_code == 409 and r.json()["code"] == "stock_record_insufficient"
    assert (r.json()["recorded_quantity"], r.json()["can_override"]) == (2, False)
    assert pharmacy(w, short, "collect", by=w.manager).json()["can_override"] is True
    override = {"verified_on_hand": 5, "recorded_quantity_seen": 2, "reason": "Counted the shelf twice",
                "physically_verified": True}
    for bad, code in (({"recorded_quantity_seen": 3}, 409), ({"verified_on_hand": 3}, 422),
                      ({"physically_verified": False}, 422), ({"reason": "short"}, 422)):
        r = pharmacy(w, short, "collect", by=w.manager, json={"override": {**override, **bad}})
        assert r.status_code == code, (bad, r.text)
    assert pharmacy(w, short, "collect", by=w.manager, json={"override": {**override, "recorded_quantity_seen": 3}}
                    ).json()["code"] == "stock_changed"
    assert w.stock_quantity() == 2 and pharmacy(w, short).json()["status"] == "confirmed"
    r = pharmacy(w, short, "collect", by=w.manager, json={"override": override})
    assert r.status_code == 200, r.text
    collection = r.json()["collection"]
    assert collection["override"] is True and collection["override_by_name"] == "Manager"
    assert (collection["verified_on_hand"], collection["recorded_quantity_before"], collection["quantity_after"]) == (5, 2, 1)
    assert w.stock_quantity() == 1


def test_collection_requires_the_reference_the_patient_shows(w):
    ref = reserve(w, quantity=2)
    confirm(w, ref)
    other = reserve(w, patient=w.patient2, product=w.medicine("Ibuprofen", "Brufen 200mg"))
    r = pharmacy(w, ref, "collect", raw=True)
    assert r.status_code == 422  # no body: the typed reference is required
    r = pharmacy(w, ref, "collect", raw=True, json={})
    assert r.status_code == 422
    for wrong in (other, "RX-AAAAAAAAAA"):
        r = pharmacy(w, ref, "collect", raw=True, json={"reference": wrong})
        assert r.status_code == 422 and r.json()["code"] == "reference_mismatch", wrong
    r = pharmacy(w, ref, "collect", raw=True, json={"reference": "not-a-reference"})
    assert r.status_code == 422
    assert w.stock_quantity() == 10 and pharmacy(w, ref).json()["status"] == "confirmed"
    assert db_count("SELECT count(*) FROM reservation_collection") == 0
    r = pharmacy(w, ref, "collect", raw=True, json={"reference": ref.lower()})
    assert r.status_code == 200 and r.json()["status"] == "collected" and w.stock_quantity() == 8


def test_handled_requests_no_longer_count_as_unread(w):
    first, second = reserve(w), reserve(w, patient=w.patient2)
    notes = lambda: w.client.get("/notifications", params={"organization_id": w.org}, headers=w.headers[w.manager]).json()  # noqa: E731
    assert notes()["unread_count"] == 2
    confirm(w, first)
    data = notes()
    by_ref = {n["reservation_reference"]: n["read"] for n in data["items"]}
    assert by_ref == {first: True, second: False} and data["unread_count"] == 1
    pharmacy(w, second, "decline", json={"reason": "Not stocked today"})
    assert notes()["unread_count"] == 0
    # The patient's own updates are unaffected.
    assert w.client.get("/notifications", headers=w.headers[w.patient]).json()["unread_count"] == 1


def test_expired_reservation_cannot_be_collected(w):
    ref = reserve(w)
    confirm(w, ref)
    backdate(scalar("SELECT reservation_id FROM reservation"))
    r = pharmacy(w, ref, "collect")
    assert r.status_code == 409 and r.json()["code"] == "expired"
    assert w.stock_quantity() == 10


def test_suspended_pharmacy_can_read_but_not_act(w):
    ref = reserve(w)
    r = w.client.post(f"/admin/organizations/{w.org}/review",
                      json={"decision": "suspended", "notes": "Licence check"}, headers=w.admin_headers)
    assert r.status_code == 200, r.text
    data = pharmacy(w, ref).json()
    assert data["status"] == "cancelled" and data["actions"] == [] and data["system_reason"]
    assert pharmacy(w, ref, "confirm").status_code == 403


# ---------------------------------------------------------------------------
# Notifications and phone privacy
# ---------------------------------------------------------------------------
def test_notifications_reach_the_right_recipient_without_personal_details(w):
    ref = reserve(w)
    confirm(w, ref)
    org_notes = w.client.get("/notifications", params={"organization_id": w.org}, headers=w.owner_headers).json()
    assert [(n["kind"], n["reservation_reference"]) for n in org_notes["items"]] == [("reservation_requested", ref)]
    mine = w.client.get("/notifications", headers=w.headers[w.patient]).json()
    assert [(n["kind"], n["reservation_reference"]) for n in mine["items"]] == [("reservation_confirmed", ref)]
    assert mine["unread_count"] == 1
    assert w.client.post("/notifications/read", json={"all": True}, headers=w.headers[w.patient]).status_code == 204
    assert w.client.get("/notifications", headers=w.headers[w.patient]).json()["unread_count"] == 0
    assert w.client.get("/notifications", headers=w.headers[w.patient2]).json()["items"] == []
    # Staff have no personal reservation notifications, and none carry a phone number.
    assert w.client.get("/notifications", headers=w.owner_headers).json()["items"] == []
    for payload in (org_notes, mine):
        assert "phone" not in str(payload) and "+250788123456" not in str(payload)


def test_patient_phone_never_reaches_public_supplier_or_other_views(w, client):
    ref = reserve(w)
    confirm(w, ref)
    phone = "+250788123456"
    public = [
        client.get("/search/pharmacies", params={"q": "Panadol"}),
        client.get(f"/search/pharmacies/{w.branch}"),
        client.get("/search/medicines", params={"q": "Panadol"}),
        client.get("/medicines/availability"),
    ]
    for r in public:
        assert r.status_code == 200, r.text
        assert phone not in r.text
        assert not keys(r.json()) & {"quantity", "allocated_quantity", "available_to_reserve",
                                     "recorded_quantity", "shortfall", "reservation_shortfall"}
    # Inventory (members) shows allocation figures but no patient details.
    inventory = client.get(f"/organizations/{w.org}/inventory", headers=w.owner_headers)
    assert phone not in inventory.text and "Patient One" not in inventory.text
    # The admin organization view does not include reservations or phones.
    admin_view = client.get(f"/admin/organizations/{w.org}", headers=w.admin_headers)
    assert admin_view.status_code == 200 and phone not in admin_view.text
    # Another patient cannot read it through any reservation endpoint.
    assert client.get(f"/reservations/{ref}", headers=w.headers[w.patient2]).status_code == 404


# ---------------------------------------------------------------------------
# Stock and allocation
# ---------------------------------------------------------------------------
def test_inventory_shows_allocation_and_filters_on_unreserved_stock(w):
    ref = reserve(w, quantity=5)
    confirm(w, ref)
    w.set_stock(w.product, 9)  # 9 recorded, 5 allocated, 4 unreserved <= threshold 5

    def listing(availability=None):
        params = {"location_id": w.branch}
        if availability:
            params["availability"] = availability
        r = w.client.get(f"/organizations/{w.org}/inventory", params=params, headers=w.headers[w.staff])
        assert r.status_code == 200, r.text
        return [i for i in r.json()["items"] if i["product_id"] == w.product]

    [item] = listing()
    assert (item["quantity"], item["allocated_quantity"], item["available_to_reserve"],
            item["reservation_shortfall"], item["availability_status"]) == (9, 5, 4, 0, "low_stock")
    assert len(listing("low_stock")) == 1
    assert listing("in_stock") == [] and listing("unavailable") == []

    w.set_stock(w.product, 3)
    [item] = listing()
    assert (item["available_to_reserve"], item["reservation_shortfall"], item["availability_status"]) == (0, 2, "unavailable")
    assert len(listing("unavailable")) == 1 and listing("low_stock") == []
    single = w.client.get(f"/organizations/{w.org}/locations/{w.branch}/stock/{w.product}", headers=w.owner_headers)
    assert single.json()["allocated_quantity"] == 5
    # Public search agrees (nothing unreserved) and still shows no figures.
    public = w.client.get(f"/search/pharmacies/{w.branch}").json()
    assert all(m["availability_status"] == "unavailable" for m in public["medicines"] if m["product_id"] == w.product)
    assert not keys(public) & {"quantity", "allocated_quantity", "available_to_reserve"}


# ---------------------------------------------------------------------------
# Catalogue reservation settings (platform admins) and acknowledgement
# ---------------------------------------------------------------------------
def test_reservation_settings_are_admin_only_and_explain_problems(w):
    product = w.medicine("Ibuprofen", "Brufen 200mg", enable=False, ack=False)
    url = f"/catalogue/products/{product}/reservation-settings"
    for who in (w.owner, w.manager, w.staff, w.patient):
        assert w.client.patch(url, json={"reservation_enabled": True}, headers=w.headers[who]).status_code == 403
        assert w.client.get(f"{url}/history", headers=w.headers[who]).status_code == 403
    data = w.client.get(url, headers=w.owner_headers).json()
    assert data["can_enable"] is False and data["reservation_enabled"] is False
    assert [p["code"] for p in data["problems"]] == ["not_non_prescription", "unit_unknown", "no_quantity_limit"]

    r = w.client.patch(url, json={"reservation_enabled": True}, headers=w.admin_headers)
    assert r.status_code == 422 and r.json()["code"] == "invalid_reservation_settings"
    assert {p["code"] for p in r.json()["problems"]} == {"not_non_prescription", "unit_unknown", "no_quantity_limit"}
    for bad in ({"unit_label": "n/a", "stock_unit": "unit"}, {"unit_label": "123", "stock_unit": "unit"},
                {"dispensing_class": "otc"}, {"stock_unit": "bottle"}, {"max_reservation_quantity": 0},
                {"unit_version": 9}, {"reservation_enabled": None}):
        assert w.client.patch(url, json=bad, headers=w.admin_headers).status_code == 422, bad

    r = w.client.patch(url, json={"dispensing_class": "non_prescription", "stock_unit": "pack", "unit_label": "box",
                                  "max_reservation_quantity": 4, "reservation_enabled": True}, headers=w.admin_headers)
    assert r.status_code == 200, r.text
    assert (r.json()["can_enable"], r.json()["reservation_enabled"], r.json()["unit_version"]) == (True, True, 2)
    history = w.client.get(f"{url}/history", headers=w.admin_headers).json()
    assert history[0]["changed_by_name"] == "Admin" and history[0]["reservation_enabled"] is True


def test_branch_acknowledgement_api(w):
    product = w.medicine("Ibuprofen", "Brufen 200mg", ack=False)
    url = f"/organizations/{w.org}/locations/{w.branch}/products/{product}/unit-acknowledgement"
    shown = {"unit_version": unit_version(product), "stock_unit": "pack", "unit_label": "box", "pack_size": "20 tablets"}

    status = w.client.get(url, headers=w.headers[w.staff]).json()
    assert (status["acknowledged"], status["reason"], status["current_unit"]["unit_label"]) == (
        False, "unit_not_acknowledged", "box")
    assert w.client.post(url, json=shown, headers=w.headers[w.staff]).status_code == 403
    assert w.client.post(url, json=shown, headers=w.headers[w.outsider]).status_code == 404
    for wrong in ({"unit_label": "strip"}, {"unit_version": shown["unit_version"] + 1}, {"pack_size": "10 tablets"},
                  {"stock_unit": "unit"}):
        r = w.client.post(url, json={**shown, **wrong}, headers=w.owner_headers)
        assert r.status_code == 409 and r.json()["code"] == "unit_changed", wrong
    assert w.client.post(url, json={**shown, "acknowledged_by": w.staff}, headers=w.owner_headers).status_code == 422
    assert w.client.post(url, json={**shown, "stock_unit": "unknown"}, headers=w.owner_headers).status_code == 422

    r = w.client.post(url, json=shown, headers=w.headers[w.manager])
    assert r.status_code == 200, r.text
    assert (r.json()["acknowledged"], r.json()["reservable"], r.json()["acknowledged_by_name"]) == (True, True, "Manager")
    assert w.client.post(url, json=shown, headers=w.owner_headers).json()["acknowledged_by_name"] == "Manager"
    assert db_count("SELECT count(*) FROM offer_unit_acknowledgement WHERE product_id = :p", p=product) == 1
    # Branch-specific: the other branch has not acknowledged (and does not stock it).
    other = w.client.get(url.replace(f"/locations/{w.branch}/", f"/locations/{w.branch2}/"), headers=w.owner_headers)
    assert other.json()["acknowledged"] is False

    # A unit change starts a new version: the acknowledgement no longer counts.
    r = w.client.patch(f"/catalogue/products/{product}/reservation-settings", json={"unit_label": "carton"},
                       headers=w.admin_headers)
    assert r.status_code == 200 and r.json()["unit_version"] == shown["unit_version"] + 1
    status = w.client.get(url, headers=w.owner_headers).json()
    assert (status["acknowledged"], status["last_acknowledged_version"], status["reason"]) == (
        False, shown["unit_version"], "unit_not_acknowledged")
    assert submit(w, product=product).json()["reason"] == "unit_not_acknowledged"
    assert w.client.post(url, json=shown, headers=w.owner_headers).json()["code"] == "unit_changed"
    new = {**shown, "unit_version": shown["unit_version"] + 1, "unit_label": "carton"}
    assert w.client.post(url, json=new, headers=w.owner_headers).json()["acknowledged"] is True
    assert submit(w, product=product).status_code == 201
    # Old acknowledgements are kept, never edited.
    assert rows("SELECT unit_version, unit_label FROM offer_unit_acknowledgement WHERE product_id = :p "
                "ORDER BY unit_version", p=product) == [(shown["unit_version"], "box"), (shown["unit_version"] + 1, "carton")]

    units = w.client.get(f"/organizations/{w.org}/locations/{w.branch}/reservation-units", headers=w.headers[w.staff])
    assert units.status_code == 200 and units.json()["total"] == 2
    assert all(i["acknowledged"] for i in units.json()["items"])


def test_unit_change_refused_while_reservations_are_open(w):
    reserve(w)
    r = w.client.patch(f"/catalogue/products/{w.product}/reservation-settings", json={"pack_size": "10 tablets"},
                       headers=w.admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "open_reservations"
    before = unit_version(w.product)
    r = w.client.patch(f"/catalogue/products/{w.product}/reservation-settings", json={"max_reservation_quantity": 3},
                       headers=w.admin_headers)
    assert r.status_code == 200 and r.json()["unit_version"] == before
