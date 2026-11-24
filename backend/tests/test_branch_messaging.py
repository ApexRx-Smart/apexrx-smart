"""Branch-scoped pharmacy messaging.

A conversation belongs to one pharmacy branch and one supplier. Pharmacy
owners see every branch; managers and staff only the branches they are
assigned to (none when unassigned); supplier members every conversation of
their supplier. Everyone else gets 404, whatever ids they try."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.helpers import World, location, login, organization, register_for, user


def _member(client, owner, org, email, role):
    register_for(client, email, org)
    r = client.post(f"/organizations/{org}/members", json={"email": email, "role": role}, headers=owner)
    assert r.status_code == 201, r.text
    return login(client, email), r.json()


def _start(client, h, org, other, branch=None):
    body = {"organization_id": org, "counterpart_organization_id": other}
    if branch is not None:
        body["pharmacy_location_id"] = branch
    return client.post("/conversations", json=body, headers=h)


def _send(client, h, cid, text_):
    r = client.post(f"/conversations/{cid}/messages", json={"body": text_}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _listed(client, h, org, **params):
    r = client.get("/conversations", params={"organization_id": org, **params}, headers=h)
    assert r.status_code == 200, r.text
    return {c["conversation_id"] for c in r.json()["items"]}


@pytest.fixture
def w(client):
    """A pharmacy with two branches (Downtown, Remera) and a supplier.
    Downtown staff joined while Downtown was the only branch (assigned to it
    automatically); Remera staff assigned by the owner; a manager unassigned."""
    w = World(client)
    w.downtown = w.branch
    w.down_staff, w.down_member = _member(client, w.pharmacy_owner, w.pharmacy, "down@x.example.com", "staff")
    w.remera = location(client, w.pharmacy_owner, w.pharmacy, "Remera", -1.9577, 30.1127)
    w.rem_staff, w.rem_member = _member(client, w.pharmacy_owner, w.pharmacy, "rem@x.example.com", "staff")
    w.manager, w.mgr_member = _member(client, w.pharmacy_owner, w.pharmacy, "mgr@x.example.com", "manager")
    r = client.put(f"/organizations/{w.pharmacy}/members/{w.rem_member['membership_id']}/branches",
                   json={"location_ids": [w.remera]}, headers=w.pharmacy_owner)
    assert r.status_code == 200, r.text
    w.sup_staff, _ = _member(client, w.supplier_owner, w.supplier, "clerk@x.example.com", "staff")
    w.conv_down = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier, w.downtown).json()["conversation_id"]
    w.conv_rem = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier, w.remera).json()["conversation_id"]
    return w


def test_single_branch_members_are_assigned_and_multi_branch_ones_wait(client, w):
    assert w.down_member["branch_ids"] == [w.downtown]  # joined while Downtown was the only branch
    assert w.mgr_member["branch_ids"] == []             # joined with two branches: waits for the owner
    members = {m["email"]: m["branch_ids"] for m in
               client.get(f"/organizations/{w.pharmacy}/members", headers=w.pharmacy_owner).json()}
    assert members["rem@x.example.com"] == [w.remera] and members["owner@pharmacy.example.com"] == []


def test_each_branch_has_its_own_conversation_with_a_supplier(client, w):
    assert w.conv_down != w.conv_rem
    # Several branches: the branch must be chosen.
    r = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier)
    assert r.status_code == 422 and r.json()["code"] == "branch_required"
    # Starting again returns the same branch conversation.
    again = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier, w.remera)
    assert again.status_code == 200 and again.json()["conversation_id"] == w.conv_rem
    conv = again.json()
    assert conv["pharmacy_location"] == {"location_id": w.remera, "name": "Remera", "city": None}


def test_staff_see_only_their_branch(client, w):
    assert _listed(client, w.down_staff, w.pharmacy) == {w.conv_down}
    assert _listed(client, w.rem_staff, w.pharmacy) == {w.conv_rem}
    # Another branch's conversation by id: invisible, whatever the route.
    for path in (f"/conversations/{w.conv_rem}", f"/conversations/{w.conv_rem}/messages"):
        assert client.get(path, headers=w.down_staff).status_code == 404, path
    assert client.post(f"/conversations/{w.conv_rem}/messages", json={"body": "hi"}, headers=w.down_staff).status_code == 404
    assert client.post(f"/conversations/{w.conv_rem}/read", json={"last_message_id": 1}, headers=w.down_staff).status_code == 404
    # Asking for the other branch, or starting there, is refused too.
    r = client.get("/conversations", params={"organization_id": w.pharmacy, "location_id": w.remera}, headers=w.down_staff)
    assert r.status_code == 404
    assert _start(client, w.down_staff, w.pharmacy, w.supplier, w.remera).status_code == 404
    assert _start(client, w.down_staff, w.pharmacy, w.supplier, w.downtown).json()["conversation_id"] == w.conv_down


def test_unassigned_staff_see_nothing_until_assigned(client, w):
    assert _listed(client, w.manager, w.pharmacy) == set()
    assert client.get(f"/conversations/{w.conv_down}/messages", headers=w.manager).status_code == 404
    assert _start(client, w.manager, w.pharmacy, w.supplier, w.downtown).status_code == 404
    r = client.put(f"/organizations/{w.pharmacy}/members/{w.mgr_member['membership_id']}/branches",
                   json={"location_ids": [w.downtown, w.remera]}, headers=w.pharmacy_owner)
    assert r.status_code == 200 and r.json()["branch_ids"] == sorted([w.downtown, w.remera])
    assert _listed(client, w.manager, w.pharmacy) == {w.conv_down, w.conv_rem}
    # Removing every branch removes the access again.
    client.put(f"/organizations/{w.pharmacy}/members/{w.mgr_member['membership_id']}/branches",
               json={"location_ids": []}, headers=w.pharmacy_owner)
    assert _listed(client, w.manager, w.pharmacy) == set()


def test_owner_sees_every_branch_and_can_filter(client, w):
    assert _listed(client, w.pharmacy_owner, w.pharmacy) == {w.conv_down, w.conv_rem}
    assert _listed(client, w.pharmacy_owner, w.pharmacy, location_id=w.remera) == {w.conv_rem}


def test_supplier_members_see_every_branch_conversation(client, w):
    for h in (w.supplier_owner, w.sup_staff):
        r = client.get("/conversations", params={"organization_id": w.supplier}, headers=h).json()
        branches = {c["conversation_id"]: c["pharmacy_location"]["name"] for c in r["items"]}
        assert branches == {w.conv_down: "Downtown", w.conv_rem: "Remera"}
    # A supplier writes to a pharmacy branch: contacts list the branches.
    contacts = client.get("/conversations/contacts", params={"organization_id": w.supplier}, headers=w.sup_staff).json()
    pharmacy = next(c for c in contacts if c["organization_id"] == w.pharmacy)
    assert {b["name"] for b in pharmacy["branches"]} == {"Downtown", "Remera"}
    assert _start(client, w.sup_staff, w.supplier, w.pharmacy).status_code == 422
    assert _start(client, w.sup_staff, w.supplier, w.pharmacy, w.remera).json()["conversation_id"] == w.conv_rem


def test_messages_carry_sender_organization_and_branch(client, w):
    m = _send(client, w.rem_staff, w.conv_rem, "We need amoxicillin at Remera.")
    assert m["sender_name"] == "Test User" and m["sender_organization_name"] == "Kigali Pharmacy" and m["mine"]
    reply = _send(client, w.sup_staff, w.conv_rem, "Available tomorrow.")
    page = client.get(f"/conversations/{w.conv_rem}/messages", headers=w.pharmacy_owner).json()["items"]
    assert [(x["sender_organization_name"], x["body"]) for x in page] == [
        ("Kigali Pharmacy", "We need amoxicillin at Remera."), ("Rwanda Med Supply", "Available tomorrow.")]
    assert reply["sender_organization_name"] == "Rwanda Med Supply"
    conv = client.get(f"/conversations/{w.conv_rem}", headers=w.sup_staff).json()
    assert conv["pharmacy_location"]["name"] == "Remera"
    with engine.connect() as c:
        row = c.execute(text("""SELECT m.sender_user_id IS NOT NULL, m.sender_organization_id, cv.pharmacy_location_id,
                                       cv.supplier_organization_id, m.created_at IS NOT NULL
                                  FROM message m JOIN conversation cv USING (conversation_id)
                                 WHERE m.message_id = :m"""), {"m": m["message_id"]}).one()
    assert tuple(row) == (True, w.pharmacy, w.remera, w.supplier, True)


def test_message_notifications_follow_the_branches(client, w):
    _send(client, w.sup_staff, w.conv_rem, "Remera only.")
    def message_notes(h):
        items = client.get("/notifications", params={"organization_id": w.pharmacy}, headers=h).json()["items"]
        return [n["conversation_id"] for n in items if n["kind"] == "message"]
    assert message_notes(w.rem_staff) == [w.conv_rem]
    assert message_notes(w.pharmacy_owner) == [w.conv_rem]
    assert message_notes(w.down_staff) == [] and message_notes(w.manager) == []


def test_procurement_requests_only_for_your_branches(client, w):
    body = {"pharmacy_organization_id": w.pharmacy, "supplier_organization_id": w.supplier,
            "items": [{"product_id": w.paracetamol, "quantity": 5}]}
    r = client.post("/procurement-requests", json={**body, "pharmacy_location_id": w.remera}, headers=w.down_staff)
    assert r.status_code == 404
    r = client.post("/procurement-requests", json={**body, "pharmacy_location_id": w.downtown}, headers=w.down_staff)
    assert r.status_code == 201, r.text
    assert r.json()["conversation_id"] == w.conv_down  # the request goes into its branch's conversation


def test_branch_assignment_rules(client, w):
    url = f"/organizations/{w.pharmacy}/members/{w.mgr_member['membership_id']}/branches"
    assert client.put(url, json={"location_ids": [w.downtown]}, headers=w.rem_staff).status_code == 403
    # Owners are never assigned; another organization's branch does not exist here.
    owner_id = next(m["membership_id"] for m in client.get(f"/organizations/{w.pharmacy}/members",
                                                         headers=w.pharmacy_owner).json() if m["role"] == "owner")
    r = client.put(f"/organizations/{w.pharmacy}/members/{owner_id}/branches", json={"location_ids": [w.downtown]},
                   headers=w.pharmacy_owner)
    assert r.status_code == 409
    assert client.put(url, json={"location_ids": [w.warehouse]}, headers=w.pharmacy_owner).status_code == 404
    # Suppliers are not split by branch.
    sup_member = next(m for m in client.get(f"/organizations/{w.supplier}/members", headers=w.supplier_owner).json()
                      if m["email"] == "clerk@x.example.com")
    r = client.put(f"/organizations/{w.supplier}/members/{sup_member['membership_id']}/branches",
                   json={"location_ids": [w.warehouse]}, headers=w.supplier_owner)
    assert r.status_code == 409


def test_other_organizations_see_nothing(client, w):
    other_owner = user(client, "other@x.example.com", account_type="pharmacy")
    other = organization(client, other_owner, "pharmacy", "Other Pharmacy")
    with engine.begin() as c:  # approved, so only the conversation rules apply
        c.execute(text("UPDATE organization SET status = 'approved', submitted_at = now(), reviewed_at = now(), "
                       "reviewed_by = (SELECT user_id FROM app_user WHERE is_platform_admin LIMIT 1) "
                       "WHERE organization_id = :o"), {"o": other})
    for cid in (w.conv_down, w.conv_rem):
        assert client.get(f"/conversations/{cid}/messages", headers=other_owner).status_code == 404
    assert _listed(client, other_owner, other) == set()


def test_an_invitation_into_a_single_branch_pharmacy_assigns_its_branch(client):
    owner = user(client, "solo@x.example.com", account_type="pharmacy")
    org = organization(client, owner, "pharmacy", "Solo Pharmacy")
    branch = location(client, owner, org, "Only Branch")
    client.post(f"/organizations/{org}/invitations", json={"email": "new@x.example.com", "role": "staff"}, headers=owner)
    token = client.get("/dev/email/latest-to", params={"to": "new@x.example.com"}).json()["token"]
    r = client.post("/invitations/accept-new", json={"token": token, "name": "New Staff", "password": "Staff-Pass-2026"})
    assert r.status_code == 201, r.text
    members = {m["email"]: m["branch_ids"] for m in client.get(f"/organizations/{org}/members", headers=owner).json()}
    assert members["new@x.example.com"] == [branch]
