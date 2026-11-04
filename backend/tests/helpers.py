"""Small API helpers shared by the tests."""

from sqlalchemy import text

from app.core.database import engine

PASSWORD = "correct-horse-battery"


def register(client, email: str, name: str = "Test User") -> dict:
    r = client.post("/auth/register", json={"name": name, "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def user(client, email: str, name: str = "Test User") -> dict:
    register(client, email, name)
    return login(client, email)


def admin(client, email: str = "admin@apexrx.example.com") -> dict:
    register(client, email, "Admin")
    with engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET is_platform_admin = true WHERE email = :e"), {"e": email})
    return login(client, email)


def organization(client, headers, type_: str, name: str) -> int:
    r = client.post("/organizations", json={"name": name, "type": type_}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["organization_id"]


def approve(client, admin_headers, organization_id: int) -> None:
    r = client.post(
        f"/admin/organizations/{organization_id}/review",
        json={"decision": "approved"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


def location(client, headers, organization_id: int, name: str, lat=None, lng=None, **extra) -> int:
    body = {"name": name, **extra}
    if lat is not None:
        body.update(latitude=lat, longitude=lng)
    r = client.post(f"/organizations/{organization_id}/locations", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["location_id"]


def catalogue_product(client, admin_headers, drug: str, product: str, **extra) -> int:
    r = client.get("/catalogue/drugs", params={"q": drug})
    match = [d for d in r.json()["items"] if d["name"] == drug]
    if match:
        drug_id = match[0]["drug_id"]
    else:
        r = client.post("/catalogue/drugs", json={"name": drug}, headers=admin_headers)
        assert r.status_code == 201, r.text
        drug_id = r.json()["drug_id"]
    r = client.post(
        "/catalogue/products",
        json={"drug_id": drug_id, "product_name": product, **extra},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["product_id"]


def stock(client, headers, org_id, loc_id, product_id, quantity, price=None, **offer):
    base = f"/organizations/{org_id}/locations/{loc_id}/stock/{product_id}"
    r = client.put(base, json={"quantity": quantity}, headers=headers)
    assert r.status_code == 200, r.text
    if price is not None:
        r = client.put(f"{base}/offer", json={"unit_price": price, **offer}, headers=headers)
        assert r.status_code == 200, r.text
    return r.json()


class World:
    """An approved pharmacy and supplier with one location each and a product
    the supplier stocks."""

    def __init__(self, client):
        self.client = client
        self.admin = admin(client)
        self.pharmacy_owner = user(client, "owner@pharmacy.example.com", "Pharmacy Owner")
        self.supplier_owner = user(client, "owner@supplier.example.com", "Supplier Owner")
        self.pharmacy = organization(client, self.pharmacy_owner, "pharmacy", "Kigali Pharmacy")
        self.supplier = organization(client, self.supplier_owner, "supplier", "Rwanda Med Supply")
        approve(client, self.admin, self.pharmacy)
        approve(client, self.admin, self.supplier)
        self.branch = location(
            client, self.pharmacy_owner, self.pharmacy, "Downtown", -1.9441, 30.0619, address="KN 4 Ave"
        )
        self.warehouse = location(
            client, self.supplier_owner, self.supplier, "Main Warehouse", -1.9706, 30.1044,
            whatsapp_phone="+250 788 123 456",
        )
        self.paracetamol = catalogue_product(
            client, self.admin, "Paracetamol", "Panadol 500mg", strength="500mg", dosage_form="tablet"
        )
        self.amoxicillin = catalogue_product(
            client, self.admin, "Amoxicillin", "Amoxil 250mg", strength="250mg", dosage_form="capsule"
        )
        stock(client, self.supplier_owner, self.supplier, self.warehouse, self.paracetamol, 1000, "150.00")
        stock(client, self.supplier_owner, self.supplier, self.warehouse, self.amoxicillin, 400, "900.00")
