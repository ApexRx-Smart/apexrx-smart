from tests.helpers import World, location, login, organization, register, stock, user


def _create(client, world, items=None, **extra):
    body = {
        "pharmacy_organization_id": world.pharmacy,
        "supplier_organization_id": world.supplier,
        "pharmacy_location_id": world.branch,
        "items": items if items is not None else [{"product_id": world.paracetamol, "quantity": 100}],
        **extra,
    }
    return client.post("/purchase-orders", json=body, headers=world.pharmacy_owner)


def test_full_order_lifecycle(client):
    world = World(client)
    r = _create(client, world, notes="Urgent")
    assert r.status_code == 201, r.text
    order = r.json()
    oid = order["purchase_order_id"]
    assert order["status"] == "draft"
    assert order["items"][0]["requested_unit_price"] == "150.00"  # server-side price snapshot
    assert order["requested_total"] == "15000.00"
    assert set(order["allowed_actions"]) == {"submit", "edit", "delete", "cancel"}

    # Suppliers never see drafts.
    assert client.get(f"/purchase-orders/{oid}", headers=world.supplier_owner).status_code == 404
    listed = client.get("/purchase-orders", params={"organization_id": world.supplier}, headers=world.supplier_owner).json()
    assert listed["total"] == 0

    # Draft editing
    r = client.post(f"/purchase-orders/{oid}/items", json={"product_id": world.amoxicillin, "quantity": 10}, headers=world.pharmacy_owner)
    assert r.status_code == 201 and r.json()["item_count"] == 2
    item_id = r.json()["items"][1]["purchase_order_item_id"]
    r = client.patch(f"/purchase-orders/{oid}/items/{item_id}", json={"quantity": 20}, headers=world.pharmacy_owner)
    assert r.json()["items"][1]["requested_quantity"] == 20
    assert client.post(f"/purchase-orders/{oid}/items", json={"product_id": world.amoxicillin, "quantity": 1}, headers=world.pharmacy_owner).status_code == 409

    # The pharmacy cannot accept its own order.
    assert client.post(f"/purchase-orders/{oid}/accept", headers=world.pharmacy_owner).status_code == 403

    r = client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted" and r.json()["submitted_at"]
    assert client.post(f"/purchase-orders/{oid}/items", json={"product_id": world.paracetamol, "quantity": 1}, headers=world.pharmacy_owner).status_code == 409
    assert client.delete(f"/purchase-orders/{oid}", headers=world.pharmacy_owner).status_code == 409

    supplier_view = client.get(f"/purchase-orders/{oid}", headers=world.supplier_owner).json()
    assert set(supplier_view["allowed_actions"]) == {"accept", "counter", "reject"}
    inbox = client.get("/purchase-orders", params={"organization_id": world.supplier, "status": "submitted"}, headers=world.supplier_owner).json()
    assert inbox["total"] == 1 and inbox["items"][0]["pharmacy"]["name"] == "Kigali Pharmacy"

    r = client.post(f"/purchase-orders/{oid}/accept", json={"supplier_location_id": world.warehouse, "note": "Ready Monday"}, headers=world.supplier_owner)
    assert r.status_code == 200, r.text
    accepted = r.json()
    supplier_user = client.get("/auth/me", headers=world.supplier_owner).json()["user_id"]
    assert accepted["status"] == "accepted" and accepted["responded_by"] == supplier_user
    assert accepted["confirmed_total"] == accepted["requested_total"] == "33000.00"
    assert accepted["supplier"]["location_name"] == "Main Warehouse"

    for action, status_ in (("start-processing", "processing"), ("dispatch", "dispatched")):
        r = client.post(f"/purchase-orders/{oid}/{action}", headers=world.supplier_owner)
        assert r.json()["status"] == status_, r.text
    r = client.post(f"/purchase-orders/{oid}/mark-delivered", json={"note": "All received"}, headers=world.pharmacy_owner)
    final = r.json()
    assert final["status"] == "delivered" and final["allowed_actions"] == []

    history = [(h["from_status"], h["to_status"], h["changed_by_name"], h["note"]) for h in final["history"]]
    assert history == [
        (None, "draft", "Pharmacy Owner", None),
        ("draft", "submitted", "Pharmacy Owner", None),
        ("submitted", "accepted", "Supplier Owner", "Ready Monday"),
        ("accepted", "processing", "Supplier Owner", None),
        ("processing", "dispatched", "Supplier Owner", None),
        ("dispatched", "delivered", "Pharmacy Owner", "All received"),
    ]


def test_counteroffer(client):
    world = World(client)
    oid = _create(client, world).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    item_id = client.get(f"/purchase-orders/{oid}", headers=world.supplier_owner).json()["items"][0]["purchase_order_item_id"]

    too_many = {"items": [{"purchase_order_item_id": item_id, "confirmed_quantity": 101, "confirmed_unit_price": "150"}]}
    assert client.post(f"/purchase-orders/{oid}/counter", json=too_many, headers=world.supplier_owner).status_code == 400
    same = {"items": [{"purchase_order_item_id": item_id, "confirmed_quantity": 100, "confirmed_unit_price": "150.00"}]}
    assert client.post(f"/purchase-orders/{oid}/counter", json=same, headers=world.supplier_owner).status_code == 400

    offer = {"items": [{"purchase_order_item_id": item_id, "confirmed_quantity": 80, "confirmed_unit_price": "160.00"}], "note": "Only 80 left"}
    r = client.post(f"/purchase-orders/{oid}/counter", json=offer, headers=world.supplier_owner)
    assert r.json()["status"] == "countered" and r.json()["confirmed_total"] == "12800.00"
    # The supplier cannot approve its own counteroffer.
    assert client.post(f"/purchase-orders/{oid}/accept-counter", headers=world.supplier_owner).status_code == 403
    pharmacy_view = client.get(f"/purchase-orders/{oid}", headers=world.pharmacy_owner).json()
    assert set(pharmacy_view["allowed_actions"]) == {"accept_counter", "cancel"}

    r = client.post(f"/purchase-orders/{oid}/accept-counter", headers=world.pharmacy_owner)
    assert r.json()["status"] == "accepted"


def test_reject_and_cancel(client):
    world = World(client)
    oid = _create(client, world).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    assert client.post(f"/purchase-orders/{oid}/reject", json={"reason": ""}, headers=world.supplier_owner).status_code == 422
    r = client.post(f"/purchase-orders/{oid}/reject", json={"reason": "Out of stock"}, headers=world.supplier_owner)
    assert r.json()["status"] == "rejected" and r.json()["rejection_reason"] == "Out of stock"
    assert client.post(f"/purchase-orders/{oid}/cancel", json={"reason": "x"}, headers=world.pharmacy_owner).status_code == 409

    oid2 = _create(client, world).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid2}/submit", headers=world.pharmacy_owner)
    # Supplier cannot cancel before accepting; pharmacy can.
    assert client.post(f"/purchase-orders/{oid2}/cancel", json={"reason": "x"}, headers=world.supplier_owner).status_code == 409
    r = client.post(f"/purchase-orders/{oid2}/cancel", json={"reason": "Found elsewhere"}, headers=world.pharmacy_owner)
    assert r.json()["status"] == "cancelled" and r.json()["history"][-1]["note"] == "Found elsewhere"


def test_draft_delete_and_validation(client):
    world = World(client)
    oid = _create(client, world).json()["purchase_order_id"]
    assert client.delete(f"/purchase-orders/{oid}", headers=world.pharmacy_owner).status_code == 204
    assert client.get(f"/purchase-orders/{oid}", headers=world.pharmacy_owner).status_code == 404

    # Product the supplier does not list
    unlisted = client.post("/catalogue/drugs", json={"name": "Rare"}, headers=world.admin).json()["drug_id"]
    product = client.post("/catalogue/products", json={"drug_id": unlisted, "product_name": "Rare 1"}, headers=world.admin).json()["product_id"]
    assert _create(client, world, items=[{"product_id": product, "quantity": 1}]).status_code == 409
    # Currency mismatch: the supplier lists in RWF only
    assert _create(client, world, currency="USD").status_code == 409
    # Empty draft cannot be submitted
    empty = _create(client, world, items=[]).json()["purchase_order_id"]
    assert client.post(f"/purchase-orders/{empty}/submit", headers=world.pharmacy_owner).status_code == 409
    # Pharmacy location must belong to the pharmacy
    r = _create(client, world, pharmacy_location_id=world.warehouse)
    assert r.status_code == 404
    # Suppliers cannot create orders as a pharmacy
    body = {"pharmacy_organization_id": world.supplier, "supplier_organization_id": world.supplier, "pharmacy_location_id": world.warehouse, "items": []}
    assert client.post("/purchase-orders", json=body, headers=world.supplier_owner).status_code == 403
    # Strangers see nothing
    stranger = user(client, "s@x.example.com")
    assert client.get(f"/purchase-orders/{empty}", headers=stranger).status_code == 404


def test_price_change_requires_reprice(client):
    world = World(client)
    oid = _create(client, world).json()["purchase_order_id"]
    stock(client, world.supplier_owner, world.supplier, world.warehouse, world.paracetamol, 1000, "175.00")

    r = client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    assert r.status_code == 409
    assert r.json()["price_changes"][0]["current_unit_price"] == "175.00"

    changes = client.post(f"/purchase-orders/{oid}/reprice", headers=world.pharmacy_owner).json()
    assert changes[0]["previous_unit_price"] == "150.00"
    r = client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    assert r.status_code == 200 and r.json()["items"][0]["requested_unit_price"] == "175.00"


def test_staff_can_handle_orders_and_suspension_blocks(client):
    world = World(client)
    register(client, "clerk@x.example.com")
    client.post(f"/organizations/{world.supplier}/members", json={"email": "clerk@x.example.com", "role": "staff"}, headers=world.supplier_owner)
    clerk = login(client, "clerk@x.example.com")

    oid = _create(client, world).json()["purchase_order_id"]
    client.post(f"/purchase-orders/{oid}/submit", headers=world.pharmacy_owner)
    assert client.post(f"/purchase-orders/{oid}/accept", headers=clerk).status_code == 200

    # A suspended pharmacy cannot create orders but can still cancel.
    client.post(f"/admin/organizations/{world.pharmacy}/review", json={"decision": "suspended", "notes": "x"}, headers=world.admin)
    assert _create(client, world).status_code == 403
    r = client.post(f"/purchase-orders/{oid}/cancel", json={"reason": "Suspended"}, headers=world.pharmacy_owner)
    assert r.json()["status"] == "cancelled"


def test_order_with_preferred_warehouse_prices(client):
    world = World(client)
    second = location(client, world.supplier_owner, world.supplier, "Second Warehouse")
    stock(client, world.supplier_owner, world.supplier, second, world.paracetamol, 50, "120.00")

    cheapest = _create(client, world).json()
    assert cheapest["items"][0]["requested_unit_price"] == "120.00"
    chosen = _create(client, world, supplier_location_id=world.warehouse).json()
    assert chosen["items"][0]["requested_unit_price"] == "150.00"
    other_org = organization(client, world.pharmacy_owner, "supplier", "Other")
    assert _create(client, world, supplier_location_id=second, supplier_organization_id=other_org).status_code == 404
