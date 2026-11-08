"""Purchase-order role policy: only pharmacy owners and managers may submit or
cancel orders. Staff may view orders and prepare drafts. Supplier-side rules
are unchanged. Also: receiving-branch ownership and cross-branch listing."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.helpers import World, location, login, organization, register, user


def _member(client, world, email, role):
    register(client, email)
    r = client.post(f"/organizations/{world.pharmacy}/members", json={"email": email, "role": role},
                    headers=world.pharmacy_owner)
    assert r.status_code == 201, r.text
    return login(client, email), r.json()["membership_id"]


def _create(client, world, headers, **extra):
    body = {
        "pharmacy_organization_id": world.pharmacy,
        "supplier_organization_id": world.supplier,
        "pharmacy_location_id": world.branch,
        "items": [{"product_id": world.paracetamol, "quantity": 10}],
        **extra,
    }
    return client.post("/purchase-orders", json=body, headers=headers)


@pytest.fixture
def team(client):
    world = World(client)
    manager, manager_mid = _member(client, world, "manager@x.example.com", "manager")
    staff, staff_mid = _member(client, world, "staff@x.example.com", "staff")
    return world, {"owner": world.pharmacy_owner, "manager": manager, "staff": staff,
                   "manager_mid": manager_mid, "staff_mid": staff_mid}


def _status(order_id):
    with engine.connect() as c:
        return c.execute(text("SELECT status FROM purchase_order WHERE purchase_order_id = :o"), {"o": order_id}).scalar()


# ---------------------------------------------------------------- submit
def test_staff_prepares_a_draft_but_cannot_submit(client, team):
    world, t = team
    r = _create(client, world, t["staff"])
    assert r.status_code == 201
    order = r.json()
    assert set(order["allowed_actions"]) == {"edit", "delete"}  # no submit / cancel for staff
    oid = order["purchase_order_id"]

    # Staff can still edit the draft.
    item = order["items"][0]["purchase_order_item_id"]
    assert client.patch(f"/purchase-orders/{oid}/items/{item}", json={"quantity": 12}, headers=t["staff"]).status_code == 200

    r = client.post(f"/purchase-orders/{oid}/submit", headers=t["staff"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only pharmacy owners and managers can submit purchase orders."
    assert _status(oid) == "draft"

    # The same draft is submittable by a manager, and the owner sees submit too.
    assert "submit" in client.get(f"/purchase-orders/{oid}", headers=t["owner"]).json()["allowed_actions"]
    r = client.post(f"/purchase-orders/{oid}/submit", headers=t["manager"])
    assert r.status_code == 200 and r.json()["status"] == "submitted"


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_owner_and_manager_can_submit(client, team, role):
    world, t = team
    oid = _create(client, world, t[role]).json()["purchase_order_id"]
    r = client.post(f"/purchase-orders/{oid}/submit", headers=t[role])
    assert r.status_code == 200 and _status(oid) == "submitted"


# ---------------------------------------------------------------- cancel
def test_staff_cannot_cancel_draft_or_submitted(client, team):
    world, t = team
    draft = _create(client, world, t["staff"]).json()["purchase_order_id"]
    assert client.post(f"/purchase-orders/{draft}/cancel", json={"reason": "x"}, headers=t["staff"]).status_code == 403
    submitted = _create(client, world, t["owner"]).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{submitted}/submit", headers=t["owner"])
    view = client.get(f"/purchase-orders/{submitted}", headers=t["staff"]).json()
    assert "cancel" not in view["allowed_actions"] and view["status"] == "submitted"  # staff can view
    r = client.post(f"/purchase-orders/{submitted}/cancel", json={"reason": "x"}, headers=t["staff"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only pharmacy owners and managers can cancel purchase orders."
    assert _status(submitted) == "submitted"


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_owner_and_manager_can_cancel(client, team, role):
    world, t = team
    oid = _create(client, world, t["owner"]).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=t["owner"])
    assert "cancel" in client.get(f"/purchase-orders/{oid}", headers=t[role]).json()["allowed_actions"]
    r = client.post(f"/purchase-orders/{oid}/cancel", json={"reason": "Not needed"}, headers=t[role])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_promotion_and_demotion_take_effect_immediately(client, team):
    world, t = team
    oid = _create(client, world, t["staff"]).json()["purchase_order_id"]
    client.patch(f"/organizations/{world.pharmacy}/members/{t['staff_mid']}", json={"role": "manager"},
                 headers=world.pharmacy_owner)
    assert client.post(f"/purchase-orders/{oid}/submit", headers=t["staff"]).status_code == 200
    client.patch(f"/organizations/{world.pharmacy}/members/{t['manager_mid']}", json={"role": "staff"},
                 headers=world.pharmacy_owner)
    r = client.post(f"/purchase-orders/{oid}/cancel", json={"reason": "x"}, headers=t["manager"])
    assert r.status_code == 403


def test_deactivated_manager_loses_order_access(client, team):
    world, t = team
    oid = _create(client, world, t["manager"]).json()["purchase_order_id"]
    client.patch(f"/organizations/{world.pharmacy}/members/{t['manager_mid']}", json={"is_active": False},
                 headers=world.pharmacy_owner)
    assert client.post(f"/purchase-orders/{oid}/submit", headers=t["manager"]).status_code == 404
    assert client.get("/purchase-orders", params={"organization_id": world.pharmacy}, headers=t["manager"]).status_code == 404


# ---------------------------------------------------------------- supplier side unchanged
def test_supplier_staff_workflow_unchanged(client, team):
    world, t = team
    register(client, "clerk@x.example.com")
    client.post(f"/organizations/{world.supplier}/members", json={"email": "clerk@x.example.com", "role": "staff"},
                headers=world.supplier_owner)
    clerk = login(client, "clerk@x.example.com")
    oid = _create(client, world, t["owner"]).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=t["owner"])
    view = client.get(f"/purchase-orders/{oid}", headers=clerk).json()
    assert set(view["allowed_actions"]) == {"accept", "counter", "reject"}
    assert client.post(f"/purchase-orders/{oid}/accept", json={}, headers=clerk).status_code == 200
    # Supplier staff may still cancel an accepted order they cannot fulfil.
    assert "cancel" in client.get(f"/purchase-orders/{oid}", headers=clerk).json()["allowed_actions"]
    r = client.post(f"/purchase-orders/{oid}/cancel", json={"reason": "Out of stock"}, headers=clerk)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_supplier_cannot_submit_or_act_as_pharmacy(client, team):
    world, t = team
    oid = _create(client, world, t["owner"]).json()["purchase_order_id"]
    # Drafts are invisible to the supplier.
    assert client.post(f"/purchase-orders/{oid}/submit", headers=world.supplier_owner).status_code == 404


# ---------------------------------------------------------------- branches
def test_receiving_branch_rules_and_cross_branch_listing(client, team):
    world, t = team
    second = location(client, world.pharmacy_owner, world.pharmacy, "Remera Branch", -1.95, 30.11)
    r = _create(client, world, t["staff"], pharmacy_location_id=second)
    assert r.status_code == 201 and r.json()["pharmacy"]["location_name"] == "Remera Branch"
    oid = r.json()["purchase_order_id"]
    _create(client, world, t["owner"])  # first branch

    listed = client.get("/purchase-orders", params={"organization_id": world.pharmacy}, headers=t["staff"]).json()
    assert {o["pharmacy"]["location_name"] for o in listed["items"]} == {"Downtown", "Remera Branch"}

    # Another pharmacy's branch cannot receive this organization's order.
    other_owner = user(client, "other@x.example.com")
    other = organization(client, other_owner, "pharmacy", "Other")
    foreign = location(client, other_owner, other, "Foreign Branch")
    assert _create(client, world, t["owner"], pharmacy_location_id=foreign).status_code == 404
    assert client.patch(f"/purchase-orders/{oid}", json={"pharmacy_location_id": foreign}, headers=t["staff"]).status_code == 404
    # A deactivated branch cannot receive orders.
    client.patch(f"/organizations/{world.pharmacy}/locations/{second}", json={"is_active": False},
                 headers=world.pharmacy_owner)
    assert _create(client, world, t["owner"], pharmacy_location_id=second).status_code == 409


# ---------------------------------------------------------------- counteroffers
def _countered(client, world, t):
    """A submitted order that the supplier countered (lower quantity and price)."""
    oid = _create(client, world, t["owner"]).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=t["owner"])
    order = client.get(f"/purchase-orders/{oid}", headers=world.supplier_owner).json()
    item = order["items"][0]["purchase_order_item_id"]
    r = client.post(f"/purchase-orders/{oid}/counter", json={"items": [{"purchase_order_item_id": item,
                    "confirmed_quantity": 8, "confirmed_unit_price": "140.00"}], "note": "Only 8 left"},
                    headers=world.supplier_owner)
    assert r.status_code == 200 and r.json()["status"] == "countered", r.text
    return oid


def test_staff_sees_counteroffer_but_cannot_accept(client, team):
    world, t = team
    oid = _countered(client, world, t)
    view = client.get(f"/purchase-orders/{oid}", headers=t["staff"]).json()
    assert view["status"] == "countered"
    assert view["items"][0]["confirmed_quantity"] == 8 and view["items"][0]["confirmed_unit_price"] == "140.00"
    assert view["allowed_actions"] == []  # neither accept_counter nor cancel
    r = client.post(f"/purchase-orders/{oid}/accept-counter", json={}, headers=t["staff"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only pharmacy owners and managers can accept a supplier's counteroffer."
    assert _status(oid) == "countered"


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_owner_and_manager_can_accept_counteroffer(client, team, role):
    world, t = team
    oid = _countered(client, world, t)
    assert set(client.get(f"/purchase-orders/{oid}", headers=t[role]).json()["allowed_actions"]) == {"accept_counter", "cancel"}
    r = client.post(f"/purchase-orders/{oid}/accept-counter", json={}, headers=t[role])
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["confirmed_total"] == "1120.00"


def test_supplier_cannot_accept_its_own_counteroffer(client, team):
    world, t = team
    oid = _countered(client, world, t)
    supplier_view = client.get(f"/purchase-orders/{oid}", headers=world.supplier_owner).json()
    assert "accept_counter" not in supplier_view["allowed_actions"]
    r = client.post(f"/purchase-orders/{oid}/accept-counter", json={}, headers=world.supplier_owner)
    assert r.status_code == 403 and r.json()["detail"] == "Only the pharmacy can accept counter this order."
