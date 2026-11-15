"""Procurement requests and quotations, end to end: a pharmacy asks a supplier
for several medicines (including ones the supplier does not list and one that
is not in the catalogue), the supplier quotes some and marks others
unavailable, the pharmacy asks for a revision, accepts the revised quotation
and converts it into a supplier order through the existing order workflow.
Also: history, notifications, roles, other organizations, invalid status
changes and duplicate orders."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.core.database import engine
from tests.helpers import World, approve, catalogue_product, login, organization, register, user


def _member(client, owner_headers, org_id, email, role):
    register(client, email)
    r = client.post(f"/organizations/{org_id}/members", json={"email": email, "role": role}, headers=owner_headers)
    assert r.status_code == 201, r.text
    return login(client, email)


def _request(client, w, headers=None, items=None, **extra):
    body = {
        "pharmacy_organization_id": w.pharmacy,
        "supplier_organization_id": w.supplier,
        "pharmacy_location_id": w.branch,
        "notes": "Delivery to Downtown branch, mornings only.",
        "items": items if items is not None else [
            # Listed by the supplier.
            {"product_id": w.paracetamol, "quantity": 100},
            # In the catalogue but not listed by this supplier.
            {"product_id": w.unlisted, "quantity": 20, "notes": "Blister packs preferred"},
            # Not in the catalogue at all: described in words.
            {"medicine_name": "Artemether-Lumefantrine", "strength": "20/120mg", "dosage_form": "tablet",
             "pack_size": "B/24", "quantity": 50},
        ],
        **extra,
    }
    return client.post("/procurement-requests", json=body, headers=headers or w.pharmacy_owner)


def _world(client):
    w = World(client)
    w.unlisted = catalogue_product(client, w.admin, "Metformin", "Glucophage 850mg", strength="850mg",
                                   dosage_form="tablet", pack_size="B/30")
    return w


def _quote(client, w, rid, lines, submit=True, note=None, days=None, headers=None):
    return client.post(f"/procurement-requests/{rid}/quotation",
                       json={"items": lines, "submit": submit, "note": note, "estimated_days": days},
                       headers=headers or w.supplier_owner)


def _kinds(client, headers, org):
    return [n["kind"] for n in client.get("/notifications", params={"organization_id": org}, headers=headers).json()["items"]]


def test_full_procurement_workflow_to_order(client):
    w = _world(client)
    catalogue_before = client.get("/catalogue/products", params={"limit": 100}).json()["total"]

    # 1-2. Pharmacy sends one request with three medicines, two not listed by the supplier.
    r = _request(client, w, needed_by="2026-12-01")
    assert r.status_code == 201, r.text
    req = r.json()
    rid = req["procurement_request_id"]
    assert req["status"] == "submitted" and req["item_count"] == 3
    items = req["items"]
    assert [(i["medicine_name"], i["in_catalogue"], i["quantity"]) for i in items] == [
        ("Panadol 500mg", True, 100), ("Glucophage 850mg", True, 20), ("Artemether-Lumefantrine", False, 50)]
    assert items[2]["strength"] == "20/120mg" and items[2]["pack_size"] == "B/24"
    # The central catalogue is unchanged.
    assert client.get("/catalogue/products", params={"limit": 100}).json()["total"] == catalogue_before
    assert set(req["allowed_actions"]) == {"cancel"}

    # 3. Supplier receives it: notification, list, detail.
    assert _kinds(client, w.supplier_owner, w.supplier) == ["request_submitted"]
    inbox = client.get("/procurement-requests", params={"organization_id": w.supplier}, headers=w.supplier_owner).json()
    assert inbox["total"] == 1 and inbox["items"][0]["pharmacy"]["name"] == "Kigali Pharmacy"
    assert inbox["items"][0]["needs_my_action"] is True
    r = client.post(f"/procurement-requests/{rid}/viewed", headers=w.supplier_owner)
    assert r.json()["status"] == "viewed" and r.json()["viewed_at"]
    assert set(r.json()["allowed_actions"]) == {"quote", "decline"}

    # 4. Supplier quotes two items and marks the third unavailable; a draft first.
    ids = [i["procurement_request_item_id"] for i in items]
    lines = [
        {"procurement_request_item_id": ids[0], "available": True, "quantity": 100, "unit_price": "160.00"},
        {"procurement_request_item_id": ids[1], "available": True, "quantity": 15, "unit_price": "2500.00",
         "note": "Only 15 boxes left"},
        {"procurement_request_item_id": ids[2], "available": False, "note": "Out of stock until January"},
    ]
    r = _quote(client, w, rid, lines, submit=False)
    assert r.status_code == 200, r.text
    assert r.json()["quotations"][0]["status"] == "draft" and r.json()["status"] == "viewed"
    # The pharmacy never sees an unsent draft.
    ph = client.get(f"/procurement-requests/{rid}", headers=w.pharmacy_owner).json()
    assert ph["quotations"] == [] and ph["status"] == "viewed"
    r = _quote(client, w, rid, lines, note="Prices valid for 7 days", days=3)
    assert r.status_code == 200, r.text
    q1 = r.json()["quotations"][0]
    assert q1["status"] == "submitted" and q1["revision"] == 1 and q1["estimated_days"] == 3
    assert q1["total"] == "53500.00"  # 100 x 160 + 15 x 2500
    assert [i["line_total"] for i in q1["items"]] == ["16000.00", "37500.00", None]
    assert r.json()["status"] == "quoted"

    # 5. Pharmacy receives and reviews it.
    assert _kinds(client, w.pharmacy_owner, w.pharmacy)[0] == "quotation_submitted"
    ph = client.get(f"/procurement-requests/{rid}", headers=w.pharmacy_owner).json()
    assert ph["status"] == "quoted" and ph["quotations"][0]["submitted_by_name"] == "Supplier Owner"
    assert set(ph["allowed_actions"]) == {"request_revision", "accept", "reject", "cancel"}

    # 6. Pharmacy asks for a revision.
    r = client.post(f"/procurement-requests/{rid}/quotations/{q1['quotation_id']}/request-revision",
                    json={"note": "Can you do 150 for Panadol?"}, headers=w.pharmacy_owner)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "negotiation"
    assert r.json()["quotations"][0]["status"] == "revision_requested"
    assert _kinds(client, w.supplier_owner, w.supplier)[0] == "revision_requested"

    # 7. Supplier sends a revised quotation; the first stays in the history as superseded.
    lines[0]["unit_price"] = "150.00"
    r = _quote(client, w, rid, lines, note="Revised as asked")
    assert r.status_code == 200, r.text
    revs = r.json()["quotations"]
    assert [(q["revision"], q["status"]) for q in revs] == [(1, "superseded"), (2, "submitted")]
    assert revs[0]["items"][0]["unit_price"] == "160.00" and revs[0]["response_note"] == "Can you do 150 for Panadol?"
    q2 = revs[1]
    assert q2["total"] == "52500.00"

    # A superseded quotation can no longer be answered.
    assert client.post(f"/procurement-requests/{rid}/quotations/{q1['quotation_id']}/accept",
                       headers=w.pharmacy_owner).status_code == 409

    # 8. Pharmacy accepts. No order exists yet.
    r = client.post(f"/procurement-requests/{rid}/quotations/{q2['quotation_id']}/accept", headers=w.pharmacy_owner)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted" and r.json()["purchase_order_id"] is None
    assert r.json()["allowed_actions"] == ["convert", "cancel"]
    assert client.get("/purchase-orders", params={"organization_id": w.pharmacy},
                      headers=w.pharmacy_owner).json()["total"] == 0
    assert _kinds(client, w.supplier_owner, w.supplier)[0] == "quotation_accepted"

    # 9. Pharmacy converts it into a supplier order.
    r = client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner)
    assert r.status_code == 201, r.text
    oid = r.json()["purchase_order_id"]
    assert r.json()["created"] is True and r.json()["request"]["status"] == "converted"

    # 10. The order has the agreed items, quantities and prices, and refers back.
    order = client.get(f"/purchase-orders/{oid}", headers=w.supplier_owner).json()
    assert order["status"] == "accepted"
    assert order["procurement_request_id"] == rid and order["quotation_id"] == q2["quotation_id"]
    assert [(i["product_id"], i["product_name"], i["confirmed_quantity"], i["confirmed_unit_price"])
            for i in order["items"]] == [(w.paracetamol, "Panadol 500mg", 100, "150.00"),
                                         (w.unlisted, "Glucophage 850mg", 15, "2500.00")]
    assert order["confirmed_total"] == "52500.00"
    assert [(h["from_status"], h["to_status"], h["changed_by_name"]) for h in order["history"]] == [
        (None, "draft", "Pharmacy Owner"), ("draft", "submitted", "Pharmacy Owner"),
        ("submitted", "accepted", "Supplier Owner")]
    assert f"Procurement request #{rid}, quotation revision 2" in order["history"][2]["note"]
    # The supplier processes it in the existing order workflow.
    assert set(order["allowed_actions"]) == {"start_processing", "dispatch", "cancel"}
    for action, st in (("start-processing", "processing"), ("dispatch", "dispatched")):
        assert client.post(f"/purchase-orders/{oid}/{action}", headers=w.supplier_owner).json()["status"] == st
    assert _kinds(client, w.supplier_owner, w.supplier)[0] == "order_created"

    # 11. The original request and both quotations stay available, linked to the order.
    final = client.get(f"/procurement-requests/{rid}", headers=w.supplier_owner).json()
    assert final["status"] == "converted" and final["purchase_order_id"] == oid
    assert [(q["revision"], q["status"]) for q in final["quotations"]] == [(1, "superseded"), (2, "accepted")]
    assert final["allowed_actions"] == []

    # 12. Converting again returns the same order; no duplicate.
    r = client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner)
    assert r.status_code == 200 and r.json()["purchase_order_id"] == oid and r.json()["created"] is False
    assert client.get("/purchase-orders", params={"organization_id": w.pharmacy},
                      headers=w.pharmacy_owner).json()["total"] == 1


def test_medicine_outside_catalogue_reaches_the_order(client):
    w = _world(client)
    rid = _request(client, w, items=[{"medicine_name": "Artemether-Lumefantrine", "strength": "20/120mg",
                                      "pack_size": "B/24", "quantity": 50}]).json()["procurement_request_id"]
    item = client.get(f"/procurement-requests/{rid}", headers=w.supplier_owner).json()["items"][0]
    _quote(client, w, rid, [{"procurement_request_item_id": item["procurement_request_item_id"], "available": True,
                            "quantity": 40, "unit_price": "3200.00"}])
    q = client.get(f"/procurement-requests/{rid}", headers=w.pharmacy_owner).json()["quotations"][0]
    client.post(f"/procurement-requests/{rid}/quotations/{q['quotation_id']}/accept", headers=w.pharmacy_owner)
    oid = client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner).json()["purchase_order_id"]
    order = client.get(f"/purchase-orders/{oid}", headers=w.pharmacy_owner).json()
    line = order["items"][0]
    assert line["product_id"] is None and line["product_name"] == "Artemether-Lumefantrine 20/120mg B/24"
    assert (line["confirmed_quantity"], line["confirmed_unit_price"], order["confirmed_total"]) == (40, "3200.00", "128000.00")
    # Lists, the supplier's view and the dashboard insights still work with such a line.
    assert client.get("/purchase-orders", params={"organization_id": w.supplier}, headers=w.supplier_owner).status_code == 200
    assert client.get(f"/organizations/{w.supplier}/insights", headers=w.supplier_owner).status_code == 200


def test_concurrent_conversion_creates_one_order(client):
    w = _world(client)
    rid = _request(client, w, items=[{"product_id": w.paracetamol, "quantity": 10}]).json()["procurement_request_id"]
    item = client.get(f"/procurement-requests/{rid}", headers=w.supplier_owner).json()["items"][0]
    _quote(client, w, rid, [{"procurement_request_item_id": item["procurement_request_item_id"], "available": True,
                            "quantity": 10, "unit_price": "150.00"}])
    q = client.get(f"/procurement-requests/{rid}", headers=w.pharmacy_owner).json()["quotations"][0]
    client.post(f"/procurement-requests/{rid}/quotations/{q['quotation_id']}/accept", headers=w.pharmacy_owner)

    def convert(_):
        return client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(convert, range(4)))
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    assert len({r.json()["purchase_order_id"] for r in results}) == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM purchase_order WHERE procurement_request_id = :r"),
                            {"r": rid}).scalar() == 1


def test_invalid_status_changes_are_refused(client):
    w = _world(client)
    rid = _request(client, w, items=[{"product_id": w.paracetamol, "quantity": 10}]).json()["procurement_request_id"]
    item_id = client.get(f"/procurement-requests/{rid}", headers=w.supplier_owner).json()["items"][0]["procurement_request_item_id"]
    good = [{"procurement_request_item_id": item_id, "available": True, "quantity": 10, "unit_price": "150.00"}]

    # No order before a quotation is accepted.
    assert client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner).status_code == 409
    # The pharmacy cannot quote; the supplier cannot accept, cancel or convert.
    assert _quote(client, w, rid, good, headers=w.pharmacy_owner).status_code == 403
    assert client.post(f"/procurement-requests/{rid}/cancel", json={"reason": "x"}, headers=w.supplier_owner).status_code == 403
    assert client.post(f"/procurement-requests/{rid}/convert", headers=w.supplier_owner).status_code == 403
    # Quotation validation: every item answered, quantities within the request, prices given.
    assert _quote(client, w, rid, [{**good[0], "quantity": 11}]).status_code == 400
    assert _quote(client, w, rid, [{**good[0], "unit_price": None}]).status_code == 400
    assert _quote(client, w, rid, [{**good[0], "unit_price": "-1"}]).status_code == 422
    assert _quote(client, w, rid, good + good).status_code == 400
    other_item = {"procurement_request_item_id": 999999, "available": False}
    assert _quote(client, w, rid, [other_item]).status_code == 400
    # A quotation with nothing available cannot be accepted.
    _quote(client, w, rid, [{"procurement_request_item_id": item_id, "available": False}])
    q = client.get(f"/procurement-requests/{rid}", headers=w.pharmacy_owner).json()["quotations"][0]
    assert client.post(f"/procurement-requests/{rid}/quotations/{q['quotation_id']}/accept",
                       headers=w.pharmacy_owner).status_code == 409
    # Reject closes the request; nothing more can happen to it.
    r = client.post(f"/procurement-requests/{rid}/quotations/{q['quotation_id']}/reject",
                    json={"reason": "Nothing available"}, headers=w.pharmacy_owner)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert _kinds(client, w.supplier_owner, w.supplier)[0] == "quotation_rejected"
    assert _quote(client, w, rid, good).status_code == 409
    assert client.post(f"/procurement-requests/{rid}/cancel", json={"reason": "x"}, headers=w.pharmacy_owner).status_code == 409
    assert client.post(f"/procurement-requests/{rid}/convert", headers=w.pharmacy_owner).status_code == 409
    # A sent quotation is never edited in the database either.
    with engine.begin() as conn:
        try:
            with conn.begin_nested():
                conn.execute(text("UPDATE quotation_item SET unit_price = 1"))
            raise AssertionError("editing a sent quotation should be refused")
        except Exception as exc:  # noqa: BLE001 - the trigger raises
            assert "cannot change once the quotation is sent" in str(exc)

    # Supplier declines; pharmacy cancels.
    rid2 = _request(client, w, items=[{"product_id": w.paracetamol, "quantity": 1}]).json()["procurement_request_id"]
    r = client.post(f"/procurement-requests/{rid2}/decline", json={"reason": "We do not supply this area"},
                    headers=w.supplier_owner)
    assert r.json()["status"] == "rejected" and r.json()["status_reason"] == "We do not supply this area"
    assert _kinds(client, w.pharmacy_owner, w.pharmacy)[0] == "request_declined"
    rid3 = _request(client, w, items=[{"product_id": w.paracetamol, "quantity": 1}]).json()["procurement_request_id"]
    assert client.post(f"/procurement-requests/{rid3}/cancel", json={"reason": "Found elsewhere"},
                       headers=w.pharmacy_owner).json()["status"] == "cancelled"
    assert _kinds(client, w.supplier_owner, w.supplier)[0] == "request_cancelled"
    # Request validation.
    assert _request(client, w, items=[]).status_code == 422
    assert _request(client, w, items=[{"quantity": 3}]).status_code == 422
    assert _request(client, w, items=[{"medicine_name": "X", "quantity": 0}]).status_code == 422
    assert _request(client, w, items=[{"product_id": w.paracetamol, "quantity": 1}] * 2).status_code == 422
    assert _request(client, w, items=[{"product_id": 999999, "quantity": 1}]).status_code == 404


def test_roles_and_other_organizations(client):
    w = _world(client)
    staff = _member(client, w.pharmacy_owner, w.pharmacy, "clerk@pharmacy.example.com", "staff")
    manager = _member(client, w.pharmacy_owner, w.pharmacy, "boss@pharmacy.example.com", "manager")
    sup_staff = _member(client, w.supplier_owner, w.supplier, "clerk@supplier.example.com", "staff")

    # Staff may send requests and ask for revisions; supplier staff may quote.
    r = _request(client, w, headers=staff, items=[{"product_id": w.paracetamol, "quantity": 5}])
    assert r.status_code == 201, r.text
    rid = r.json()["procurement_request_id"]
    item_id = r.json()["items"][0]["procurement_request_item_id"]
    line = [{"procurement_request_item_id": item_id, "available": True, "quantity": 5, "unit_price": "150.00"}]
    assert _quote(client, w, rid, line, headers=sup_staff).status_code == 200
    q = client.get(f"/procurement-requests/{rid}", headers=staff).json()
    assert q["allowed_actions"] == ["request_revision"]
    qid = q["quotations"][0]["quotation_id"]
    # Committing is for owners and managers.
    for path, body in (("accept", None), ("reject", {"reason": "no"})):
        assert client.post(f"/procurement-requests/{rid}/quotations/{qid}/{path}", json=body,
                           headers=staff).status_code == 403
    assert client.post(f"/procurement-requests/{rid}/cancel", json={"reason": "x"}, headers=staff).status_code == 403
    assert client.post(f"/procurement-requests/{rid}/quotations/{qid}/accept", headers=manager).status_code == 200
    assert client.post(f"/procurement-requests/{rid}/convert", headers=staff).status_code == 403
    assert client.post(f"/procurement-requests/{rid}/convert", headers=manager).status_code == 201

    # Other organizations, outsiders and platform admins cannot see or change it.
    other = user(client, "owner@other-supplier.example.com")
    other_org = organization(client, other, "supplier", "Other Supply")
    approve(client, w.admin, other_org)
    outsider = user(client, "nobody@example.com")
    for headers in (other, outsider, w.admin):
        assert client.get(f"/procurement-requests/{rid}", headers=headers).status_code == 404
        assert _quote(client, w, rid, line, headers=headers).status_code == 404
        assert client.post(f"/procurement-requests/{rid}/convert", headers=headers).status_code == 404
        assert client.post(f"/procurement-requests/{rid}/quotations/{qid}/accept", headers=headers).status_code == 404
    assert client.get("/procurement-requests", params={"organization_id": other_org}, headers=other).json()["total"] == 0
    assert client.get("/procurement-requests", params={"organization_id": w.pharmacy}, headers=other).status_code == 404
    assert client.get(f"/procurement-requests/{rid}").status_code == 401
    # A pharmacy cannot address a request to a pharmacy, or send one for another pharmacy.
    body = {"pharmacy_organization_id": w.pharmacy, "supplier_organization_id": w.pharmacy,
            "pharmacy_location_id": w.branch, "items": [{"product_id": w.paracetamol, "quantity": 1}]}
    assert client.post("/procurement-requests", json=body, headers=w.pharmacy_owner).status_code == 404
    body["supplier_organization_id"] = w.supplier
    assert client.post("/procurement-requests", json=body, headers=other).status_code == 404
    # The request lives in the pair's conversation.
    convs = client.get("/conversations", params={"organization_id": w.supplier}, headers=w.supplier_owner).json()["items"]
    assert [c["counterpart"]["name"] for c in convs] == ["Kigali Pharmacy"]
    assert convs[0]["conversation_id"] == client.get(f"/procurement-requests/{rid}",
                                                    headers=w.pharmacy_owner).json()["conversation_id"]


def test_unapproved_pharmacy_cannot_send_requests(client):
    w = _world(client)
    pending = user(client, "pending@pharmacy.example.com")
    org = organization(client, pending, "pharmacy", "Pending Pharmacy")
    body = {"pharmacy_organization_id": org, "supplier_organization_id": w.supplier,
            "pharmacy_location_id": w.branch, "items": [{"product_id": w.paracetamol, "quantity": 1}]}
    assert client.post("/procurement-requests", json=body, headers=pending).status_code == 403
