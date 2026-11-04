import time

from sqlalchemy import text

from app.core.database import engine
from tests.helpers import (
    World,
    admin,
    catalogue_product,
    location,
    login,
    organization,
    register,
    stock,
    user,
)


def test_catalogue_admin_only_and_dedup(client):
    admin_h = admin(client)
    normal = user(client, "u@x.example.com")
    assert client.post("/catalogue/drugs", json={"name": "Ibuprofen"}, headers=normal).status_code == 403

    drug = client.post("/catalogue/drugs", json={"name": "Ibuprofen"}, headers=admin_h).json()
    assert client.post("/catalogue/drugs", json={"name": " ibuprofen "}, headers=admin_h).status_code == 409

    body = {"drug_id": drug["drug_id"], "product_name": "Brufen 400", "brand": "Brufen", "strength": "400mg", "barcode": "123"}
    product = client.post("/catalogue/products", json=body, headers=admin_h).json()
    assert product["drug_name"] == "Ibuprofen"
    assert client.post("/catalogue/products", json={**body, "barcode": None, "brand": "BRUFEN"}, headers=admin_h).status_code == 409
    assert client.post("/catalogue/products", json={**body, "strength": "200mg"}, headers=admin_h).status_code == 409  # barcode

    # Public browsing
    assert client.get("/catalogue/products", params={"q": "ibu"}).json()["total"] == 1
    client.patch(f"/catalogue/products/{product['product_id']}", json={"is_active": False}, headers=admin_h)
    assert client.get("/catalogue/products", params={"q": "ibu"}).json()["total"] == 0


def test_stock_requires_approval_and_roles(client):
    world = World(client)
    pending_owner = user(client, "pending@x.example.com")
    pending = organization(client, pending_owner, "pharmacy", "Not Yet")
    loc = location(client, pending_owner, pending, "Shop")
    r = client.put(f"/organizations/{pending}/locations/{loc}/stock/{world.paracetamol}", json={"quantity": 3}, headers=pending_owner)
    assert r.status_code == 403

    # Staff update stock but cannot set prices.
    register(client, "staff@x.example.com")
    client.post(f"/organizations/{world.pharmacy}/members", json={"email": "staff@x.example.com", "role": "staff"}, headers=world.pharmacy_owner)
    staff = login(client, "staff@x.example.com")
    base = f"/organizations/{world.pharmacy}/locations/{world.branch}/stock/{world.paracetamol}"
    assert client.put(base, json={"quantity": 20}, headers=staff).status_code == 200
    assert client.put(f"{base}/offer", json={"unit_price": "200"}, headers=staff).status_code == 403
    assert client.delete(base, headers=staff).status_code == 403
    # Another org's member cannot touch this location.
    assert client.put(base, json={"quantity": 1}, headers=world.supplier_owner).status_code == 404


def test_stock_audit_trail_and_freshness(client):
    world = World(client)
    org, loc, product = world.pharmacy, world.branch, world.paracetamol
    base = f"/organizations/{org}/locations/{loc}/stock/{product}"

    # An offer needs a stock row first.
    assert client.put(f"{base}/offer", json={"unit_price": "200"}, headers=world.pharmacy_owner).status_code == 404

    first = stock(client, world.pharmacy_owner, org, loc, product, 10, "200.00")
    assert first["offer"]["currency"] == "RWF" and first["availability_status"] == "in_stock"
    owner_id = client.get("/auth/me", headers=world.pharmacy_owner).json()["user_id"]
    assert first["updated_by"] == owner_id  # stamped by trigger from app.user_id

    time.sleep(0.05)
    again = client.put(base, json={"quantity": 10}, headers=world.pharmacy_owner).json()
    assert again["last_updated"] > first["last_updated"]  # re-save = "still accurate"

    low = client.put(base, json={"quantity": 3}, headers=world.pharmacy_owner).json()
    assert low["availability_status"] == "low_stock"
    assert client.put(base, json={"quantity": 0}, headers=world.pharmacy_owner).json()["availability_status"] == "unavailable"

    audit = client.get(f"{base}/adjustments", headers=world.pharmacy_owner).json()["items"]
    assert [(a["change_type"], a["old_quantity"], a["new_quantity"]) for a in audit] == [
        ("quantity_update", 3, 0),
        ("quantity_update", 10, 3),
        ("initial_stock", None, 10),
    ]
    assert audit[0]["changed_by_name"] == "Pharmacy Owner"

    r = client.post(f"/organizations/{org}/locations/{loc}/stock/confirm", headers=world.pharmacy_owner)
    assert r.json()["detail"] == "Confirmed 1 stock records."

    assert client.delete(base, headers=world.pharmacy_owner).status_code == 204
    audit = client.get(f"{base}/adjustments", headers=world.pharmacy_owner).json()["items"]
    assert audit[0]["change_type"] == "stock_deleted" and audit[0]["old_quantity"] == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM product_offer")).scalar() == 2  # supplier's only

    inventory = client.get(f"/organizations/{world.supplier}/inventory", headers=world.supplier_owner).json()
    assert inventory["total"] == 2


def test_patient_search(client):
    world = World(client)
    admin_h = world.admin
    # Two pharmacies: one close and pricier, one far and cheaper.
    stock(client, world.pharmacy_owner, world.pharmacy, world.branch, world.paracetamol, 50, "300.00")
    far = location(client, world.pharmacy_owner, world.pharmacy, "Far Branch", -2.6, 29.74)
    stock(client, world.pharmacy_owner, world.pharmacy, far, world.paracetamol, 2, "100.00")
    # An unapproved pharmacy never shows up.
    other_owner = user(client, "o@x.example.com")
    other = organization(client, other_owner, "pharmacy", "Pending Pharmacy")
    with engine.begin() as conn:  # bypass the API approval check to prove the view filters it
        conn.execute(text("SELECT set_config('app.user_id', '1', true)"))
        loc = conn.execute(text("INSERT INTO location (organization_id, name) VALUES (:o, 'L') RETURNING location_id"), {"o": other}).scalar()
        conn.execute(text("INSERT INTO stock (location_id, product_id, quantity) VALUES (:l, :p, 100)"), {"l": loc, "p": world.paracetamol})
        conn.execute(text("INSERT INTO product_offer (location_id, product_id, unit_price) VALUES (:l, :p, 1)"), {"l": loc, "p": world.paracetamol})

    r = client.get("/search/pharmacies", params={"q": "paracetamol", "lat": -1.95, "lng": 30.06})
    assert r.status_code == 200
    results = r.json()["items"]
    assert [x["location_name"] for x in results] == ["Downtown", "Far Branch"]  # distance sort
    assert all("quantity" not in x for x in results)  # never exposed to patients
    assert results[0]["availability_status"] == "in_stock" and results[1]["availability_status"] == "low_stock"
    assert results[0]["distance_km"] < 2 and results[0]["directions_url"].startswith("https://www.google.com/maps/dir/")

    by_price = client.get("/search/pharmacies", params={"product_id": world.paracetamol, "sort": "price"}).json()["items"]
    assert [x["unit_price"] for x in by_price] == ["100.00", "300.00"]

    near = client.get("/search/pharmacies", params={"q": "panadol", "lat": -1.95, "lng": 30.06, "radius_km": 10}).json()
    assert near["total"] == 1

    # Supplier offers are not patient-visible.
    assert client.get("/search/pharmacies", params={"q": "amoxil"}).json()["total"] == 0
    assert client.get("/search/pharmacies").status_code == 400

    meds = client.get("/search/medicines", params={"q": "para"}).json()["items"]
    assert meds[0]["available_pharmacy_count"] == 2

    detail = client.get(f"/search/pharmacies/{world.branch}").json()
    assert detail["pharmacy_name"] == "Kigali Pharmacy" and len(detail["medicines"]) == 1
    assert client.get(f"/search/pharmacies/{world.warehouse}").status_code == 404  # a supplier location

    legacy = client.get("/medicines/availability").json()
    assert {x["availability"] for x in legacy} == {"in_stock", "low_stock"} and "quantity" not in legacy[0]

    # Searches are logged with coarse coordinates only.
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT query_text, approx_latitude, results_count FROM search_event ORDER BY 1")).all()
    assert ("paracetamol", -1.95, 2) in [(q, float(lat) if lat is not None else None, n) for q, lat, n in rows]
    insights = client.get("/admin/insights/searches", headers=admin_h).json()
    assert any(i["query"] == "amoxil" and i["zero_result_searches"] == 1 for i in insights)

    # Deactivating a location removes it from search.
    client.patch(f"/organizations/{world.pharmacy}/locations/{far}", json={"is_active": False}, headers=world.pharmacy_owner)
    assert client.get("/search/pharmacies", params={"q": "paracetamol"}).json()["total"] == 1


def test_supplier_search(client):
    world = World(client)
    r = client.get("/supplier-offers", params={"pharmacy_organization_id": world.pharmacy, "q": "paracetamol", "lat": -1.95, "lng": 30.06}, headers=world.pharmacy_owner)
    assert r.status_code == 200, r.text
    [offer] = r.json()["items"]
    assert offer["quantity"] == 1000 and offer["unit_price"] == "150.00"
    assert offer["whatsapp_url"] == "https://wa.me/250788123456" and offer["distance_km"] > 0

    # Only members of an approved pharmacy may search suppliers.
    assert client.get("/supplier-offers", params={"pharmacy_organization_id": world.supplier, "q": "x"}, headers=world.supplier_owner).status_code == 403
    assert client.get("/supplier-offers", params={"pharmacy_organization_id": world.pharmacy, "q": "x"}, headers=world.supplier_owner).status_code == 404
    assert client.get("/supplier-offers", params={"pharmacy_organization_id": world.pharmacy, "q": "x"}).status_code == 401

    catalogue = client.get("/supplier-offers", params={"pharmacy_organization_id": world.pharmacy, "supplier_organization_id": world.supplier, "sort": "quantity"}, headers=world.pharmacy_owner).json()
    assert [o["quantity"] for o in catalogue["items"]] == [1000, 400]

    # A suspended supplier disappears.
    client.post(f"/admin/organizations/{world.supplier}/review", json={"decision": "suspended", "notes": "audit"}, headers=world.admin)
    assert client.get("/supplier-offers", params={"pharmacy_organization_id": world.pharmacy, "q": "paracetamol"}, headers=world.pharmacy_owner).json()["total"] == 0


def test_unlisted_offer_hidden(client):
    world = World(client)
    product = catalogue_product(client, world.admin, "Cetirizine", "Zyrtec 10mg")
    stock(client, world.pharmacy_owner, world.pharmacy, world.branch, product, 30, "500", is_listed=False)
    assert client.get("/search/pharmacies", params={"q": "zyrtec"}).json()["total"] == 0
