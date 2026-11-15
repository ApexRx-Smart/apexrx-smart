"""Dashboard insights (charts and management figures) are for owners and
managers only, on both pharmacy and supplier organizations. Staff are refused
by the API itself, while keeping the operational routes they work with."""

import pytest

from tests.helpers import World, catalogue_product, login, register, stock, user


def _member(client, org_id, owner_headers, email, role):
    register(client, email)
    r = client.post(f"/organizations/{org_id}/members", json={"email": email, "role": role}, headers=owner_headers)
    assert r.status_code == 201, r.text
    return login(client, email), r.json()["membership_id"]


@pytest.fixture
def teams(client):
    w = World(client)
    roles = {}
    for side, org, owner in (("pharmacy", w.pharmacy, w.pharmacy_owner), ("supplier", w.supplier, w.supplier_owner)):
        manager, _ = _member(client, org, owner, f"manager@{side}.example.com", "manager")
        staff, staff_mid = _member(client, org, owner, f"staff@{side}.example.com", "staff")
        roles[side] = {"org": org, "owner": owner, "manager": manager, "staff": staff, "staff_mid": staff_mid}
    return w, roles


def _insights(client, org, headers, **params):
    return client.get(f"/organizations/{org}/insights", params=params, headers=headers)


def _order(client, w, items, submit=True):
    r = client.post(
        "/purchase-orders",
        json={
            "pharmacy_organization_id": w.pharmacy,
            "supplier_organization_id": w.supplier,
            "pharmacy_location_id": w.branch,
            "items": items,
        },
        headers=w.pharmacy_owner,
    )
    assert r.status_code == 201, r.text
    oid = r.json()["purchase_order_id"]
    if submit:
        assert client.post(f"/purchase-orders/{oid}/submit", headers=w.pharmacy_owner).status_code == 200
    return oid


# ------------------------------------------------------------- who may read
@pytest.mark.parametrize("side", ["pharmacy", "supplier"])
@pytest.mark.parametrize("role", ["owner", "manager"])
def test_owner_and_manager_read_insights(client, teams, side, role):
    _, t = teams
    r = _insights(client, t[side]["org"], t[side][role])
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"stock_health", "order_pipeline", "open_order_value", "top_requested"}


@pytest.mark.parametrize("side", ["pharmacy", "supplier"])
def test_staff_are_refused_but_keep_their_workflows(client, teams, side):
    w, t = teams
    org, staff = t[side]["org"], t[side]["staff"]
    r = _insights(client, org, staff)
    assert r.status_code == 403
    assert "requires: manager, owner" in r.json()["detail"]
    # Also with a location filter: no way around it.
    loc = w.branch if side == "pharmacy" else w.warehouse
    assert _insights(client, org, staff, location_id=loc).status_code == 403

    # The operational routes staff use are unchanged.
    assert client.get(f"/organizations/{org}/inventory", headers=staff).status_code == 200
    assert client.get("/purchase-orders", params={"organization_id": org}, headers=staff).status_code == 200
    r = client.put(f"/organizations/{org}/locations/{loc}/stock/{w.paracetamol}", json={"quantity": 7}, headers=staff)
    assert r.status_code == 200, r.text


def test_outsiders_and_anonymous_are_refused(client, teams):
    w, t = teams
    org = t["pharmacy"]["org"]
    assert _insights(client, org, {}).status_code == 401
    assert _insights(client, org, {"Authorization": "Bearer not-a-token"}).status_code == 401
    # Another organization's owner, and a platform admin, are not members: 404.
    assert _insights(client, org, w.supplier_owner).status_code == 404
    assert _insights(client, org, w.admin).status_code == 404
    assert _insights(client, org, user(client, "nobody@example.com")).status_code == 404
    # A location of another organization is not found.
    assert _insights(client, org, w.pharmacy_owner, location_id=w.warehouse).status_code == 404


def test_role_changes_take_effect_immediately(client, teams):
    _, t = teams
    p = t["pharmacy"]
    assert _insights(client, p["org"], p["staff"]).status_code == 403
    r = client.patch(f"/organizations/{p['org']}/members/{p['staff_mid']}", json={"role": "manager"}, headers=p["owner"])
    assert r.status_code == 200, r.text
    assert _insights(client, p["org"], p["staff"]).status_code == 200  # same token
    r = client.patch(f"/organizations/{p['org']}/members/{p['staff_mid']}", json={"role": "staff"}, headers=p["owner"])
    assert r.status_code == 200, r.text
    assert _insights(client, p["org"], p["staff"]).status_code == 403
    r = client.patch(f"/organizations/{p['org']}/members/{p['staff_mid']}", json={"is_active": False}, headers=p["owner"])
    assert r.status_code == 200, r.text
    assert _insights(client, p["org"], p["staff"]).status_code == 404


# ------------------------------------------------------------- the figures
def test_figures_match_the_data(client, teams):
    w, t = teams
    ph = w.pharmacy_owner
    ibuprofen = catalogue_product(client, w.admin, "Ibuprofen", "Brufen 400mg", strength="400mg")
    stock(client, ph, w.pharmacy, w.branch, w.paracetamol, 100, "300.00", low_stock_threshold=10)  # in
    stock(client, ph, w.pharmacy, w.branch, w.amoxicillin, 8, "950.00", low_stock_threshold=10)  # low
    stock(client, ph, w.pharmacy, w.branch, ibuprofen, 0)  # out (no offer)

    r = _insights(client, w.pharmacy, t["pharmacy"]["manager"], location_id=w.branch).json()
    assert r["stock_health"] == {"in_stock": 1, "low_stock": 1, "out_of_stock": 1, "total": 3}
    assert r["location_id"] == w.branch

    # Two submitted orders and one draft. Supplier prices: paracetamol 150, amoxicillin 900.
    _order(client, w, [{"product_id": w.paracetamol, "quantity": 10}])
    _order(client, w, [{"product_id": w.paracetamol, "quantity": 5}, {"product_id": w.amoxicillin, "quantity": 2}])
    _order(client, w, [{"product_id": w.amoxicillin, "quantity": 50}], submit=False)

    p = _insights(client, w.pharmacy, t["pharmacy"]["owner"]).json()
    assert p["order_pipeline"]["draft"] == 1 and p["order_pipeline"]["submitted"] == 2
    assert p["open_order_value"] == "4050.00"  # 10*150 + 5*150 + 2*900
    assert p["currency"] == "RWF"
    assert [(x["product_name"], x["quantity"]) for x in p["top_requested"]] == [("Panadol 500mg", 15), ("Amoxil 250mg", 2)]

    s = _insights(client, w.supplier, t["supplier"]["manager"]).json()
    assert "draft" not in s["order_pipeline"]  # suppliers never see drafts
    assert s["order_pipeline"]["submitted"] == 2
    assert s["open_order_value"] == "4050.00"
    assert s["top_requested"][0]["product_name"] == "Panadol 500mg"
    # Supplier stock (World): paracetamol 1000 and amoxicillin 400, both above the threshold.
    assert s["stock_health"] == {"in_stock": 2, "low_stock": 0, "out_of_stock": 0, "total": 2}
