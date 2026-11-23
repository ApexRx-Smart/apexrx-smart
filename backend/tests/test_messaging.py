"""In-platform messaging between a pharmacy and a supplier: starting a
conversation (no duplicates), sending and polling, history, unread counts and
notifications, permissions (only the two organizations' members), validation
and rate limiting."""

from sqlalchemy import text

from app.core.database import engine
from tests.helpers import World, approve, login, organization, register_for, user


def _member(client, owner_headers, org_id, email, role="staff"):
    register_for(client, email, org_id)
    r = client.post(f"/organizations/{org_id}/members", json={"email": email, "role": role}, headers=owner_headers)
    assert r.status_code == 201, r.text
    return login(client, email)


def _start(client, headers, org_id, other_id):
    return client.post("/conversations", json={"organization_id": org_id, "counterpart_organization_id": other_id},
                       headers=headers)


def test_supplier_starts_pharmacy_replies_history_and_unread(client):
    w = World(client)
    # 1. The supplier starts the conversation with the pharmacy.
    r = _start(client, w.supplier_owner, w.supplier, w.pharmacy)
    assert r.status_code == 201, r.text
    conv = r.json()
    cid = conv["conversation_id"]
    assert conv["counterpart"] == {"organization_id": w.pharmacy, "name": "Kigali Pharmacy", "type": "pharmacy",
                                   "city": None, "phone": None}
    # Starting again (from either side) returns the same conversation, never a duplicate.
    again = _start(client, w.supplier_owner, w.supplier, w.pharmacy)
    assert again.status_code == 200 and again.json()["conversation_id"] == cid
    from_pharmacy = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier)
    assert from_pharmacy.status_code == 200 and from_pharmacy.json()["conversation_id"] == cid

    r = client.post(f"/conversations/{cid}/messages", json={"body": "  Hello, we have Amoxicillin in stock.  "},
                    headers=w.supplier_owner)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["body"] == "Hello, we have Amoxicillin in stock." and first["mine"] is True
    assert first["sender_name"] == "Supplier Owner"

    # 2. The pharmacy sees it, unread, with a notification.
    lst = client.get("/conversations", params={"organization_id": w.pharmacy}, headers=w.pharmacy_owner).json()
    assert lst["unread_total"] == 1
    item = lst["items"][0]
    assert item["conversation_id"] == cid and item["unread_count"] == 1
    assert item["counterpart"]["name"] == "Rwanda Med Supply" and item["counterpart"]["type"] == "supplier"
    assert item["last_message"]["body"] == "Hello, we have Amoxicillin in stock." and item["last_message"]["mine"] is False
    notes = client.get("/notifications", params={"organization_id": w.pharmacy}, headers=w.pharmacy_owner).json()
    assert notes["unread_count"] == 1
    assert notes["items"][0]["kind"] == "message" and notes["items"][0]["from_organization_name"] == "Rwanda Med Supply"
    assert notes["items"][0]["conversation_id"] == cid
    # The sender's own side has nothing unread.
    sup_list = client.get("/conversations", params={"organization_id": w.supplier}, headers=w.supplier_owner).json()
    assert sup_list["unread_total"] == 0

    # 3. The pharmacy reads and replies.
    page = client.get(f"/conversations/{cid}/messages", headers=w.pharmacy_owner).json()
    assert [m["body"] for m in page["items"]] == ["Hello, we have Amoxicillin in stock."]
    assert page["last_read_message_id"] is None
    assert client.post(f"/conversations/{cid}/read", json={"last_message_id": first["message_id"]},
                       headers=w.pharmacy_owner).status_code == 204
    lst = client.get("/conversations", params={"organization_id": w.pharmacy}, headers=w.pharmacy_owner).json()
    assert lst["unread_total"] == 0
    notes = client.get("/notifications", params={"organization_id": w.pharmacy}, headers=w.pharmacy_owner).json()
    assert notes["unread_count"] == 0 and notes["items"][0]["read"] is True
    reply = client.post(f"/conversations/{cid}/messages", json={"body": "Great, what is your price?"},
                        headers=w.pharmacy_owner).json()

    # 4. The supplier polls for newer messages and receives the reply.
    newer = client.get(f"/conversations/{cid}/messages", params={"after_id": first["message_id"]},
                       headers=w.supplier_owner).json()
    assert [(m["body"], m["mine"], m["sender_name"]) for m in newer["items"]] == [
        ("Great, what is your price?", False, "Pharmacy Owner")
    ]
    assert client.get("/conversations", params={"organization_id": w.supplier},
                      headers=w.supplier_owner).json()["unread_total"] == 1

    # 5. History persists (a new sign-in, i.e. after a refresh, sees all of it in order).
    fresh = login(client, "owner@supplier.example.com")
    hist = client.get(f"/conversations/{cid}/messages", headers=fresh).json()
    assert [m["message_id"] for m in hist["items"]] == [first["message_id"], reply["message_id"]]
    # Older pages work too.
    older = client.get(f"/conversations/{cid}/messages", params={"before_id": reply["message_id"]}, headers=fresh).json()
    assert [m["message_id"] for m in older["items"]] == [first["message_id"]]


def test_unread_is_per_user_and_every_member_can_take_part(client):
    w = World(client)
    staff = _member(client, w.pharmacy_owner, w.pharmacy, "clerk@pharmacy.example.com")
    cid = _start(client, w.supplier_owner, w.supplier, w.pharmacy).json()["conversation_id"]
    m = client.post(f"/conversations/{cid}/messages", json={"body": "Price list attached below"},
                    headers=w.supplier_owner).json()
    # The owner reads it; the staff member still has it unread.
    client.post(f"/conversations/{cid}/read", json={"last_message_id": m["message_id"]}, headers=w.pharmacy_owner)
    assert client.get("/conversations", params={"organization_id": w.pharmacy},
                      headers=staff).json()["unread_total"] == 1
    # Staff of the organization can reply in the organization's conversation.
    r = client.post(f"/conversations/{cid}/messages", json={"body": "Thanks"}, headers=staff)
    assert r.status_code == 201 and r.json()["sender_name"] == "Test User"


def test_unrelated_organizations_cannot_see_or_write(client):
    w = World(client)
    cid = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier).json()["conversation_id"]
    mid = client.post(f"/conversations/{cid}/messages", json={"body": "Private"}, headers=w.pharmacy_owner).json()["message_id"]

    other = user(client, "owner@other-pharmacy.example.com", "Other Owner")
    other_org = organization(client, other, "pharmacy", "Other Pharmacy")
    approve(client, w.admin, other_org)
    outsider = user(client, "nobody@example.com")
    for headers in (other, outsider, w.admin):
        assert client.get(f"/conversations/{cid}", headers=headers).status_code == 404
        assert client.get(f"/conversations/{cid}/messages", headers=headers).status_code == 404
        assert client.post(f"/conversations/{cid}/messages", json={"body": "hi"}, headers=headers).status_code == 404
        assert client.post(f"/conversations/{cid}/read", json={"last_message_id": mid}, headers=headers).status_code == 404
    # Their own list does not include it, and they cannot list the pharmacy's.
    assert client.get("/conversations", params={"organization_id": other_org}, headers=other).json()["items"] == []
    assert client.get("/conversations", params={"organization_id": w.pharmacy}, headers=other).status_code == 404
    assert client.get("/notifications", params={"organization_id": w.supplier}, headers=other).status_code == 404
    # No token at all.
    assert client.get(f"/conversations/{cid}/messages").status_code == 401
    # A pharmacy cannot open a conversation with another pharmacy.
    assert _start(client, other, other_org, w.pharmacy).status_code == 404


def test_validation_approval_and_rate_limit(client):
    w = World(client)
    cid = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier).json()["conversation_id"]
    for body in ("", "    ", "x" * 4001):
        assert client.post(f"/conversations/{cid}/messages", json={"body": body},
                           headers=w.pharmacy_owner).status_code == 422
    assert client.post(f"/conversations/{cid}/messages", json={}, headers=w.pharmacy_owner).status_code == 422
    # Text is stored as text (escaping is the page's job), never interpreted.
    r = client.post(f"/conversations/{cid}/messages", json={"body": "<script>alert(1)</script>"}, headers=w.pharmacy_owner)
    assert r.status_code == 201 and r.json()["body"] == "<script>alert(1)</script>"

    # 30 messages a minute per user, then 429 with Retry-After.
    for i in range(29):
        assert client.post(f"/conversations/{cid}/messages", json={"body": f"m{i}"},
                           headers=w.pharmacy_owner).status_code == 201
    r = client.post(f"/conversations/{cid}/messages", json={"body": "one too many"}, headers=w.pharmacy_owner)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1

    # A suspended counterpart: history stays readable, but no new messages.
    with engine.begin() as conn:
        conn.execute(text("UPDATE organization SET status = 'suspended' WHERE organization_id = :o"), {"o": w.supplier})
    assert client.get(f"/conversations/{cid}/messages", headers=w.supplier_owner).status_code == 200
    assert client.post(f"/conversations/{cid}/messages", json={"body": "hello"}, headers=w.supplier_owner).status_code == 403
    # Nor can a suspended organization start conversations.
    assert _start(client, w.supplier_owner, w.supplier, w.pharmacy).status_code == 403


def test_messages_are_permanent_and_contacts_directory(client):
    w = World(client)
    cid = _start(client, w.pharmacy_owner, w.pharmacy, w.supplier).json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"body": "Keep me"}, headers=w.pharmacy_owner)
    with engine.begin() as conn:
        for sql in ("UPDATE message SET body = 'changed'", "DELETE FROM message"):
            try:
                with conn.begin_nested():
                    conn.execute(text(sql))
                raise AssertionError(f"{sql} should be refused")
            except Exception as exc:  # noqa: BLE001 - the trigger raises
                assert "cannot be edited or deleted" in str(exc)
    # Pharmacies see approved suppliers; suppliers see approved pharmacies.
    sup = client.get("/conversations/contacts", params={"organization_id": w.pharmacy, "q": "med"},
                     headers=w.pharmacy_owner).json()
    assert [c["name"] for c in sup] == ["Rwanda Med Supply"]
    ph = client.get("/conversations/contacts", params={"organization_id": w.supplier}, headers=w.supplier_owner).json()
    assert [c["name"] for c in ph] == ["Kigali Pharmacy"]
    pending_owner = user(client, "pending@example.com")
    organization(client, pending_owner, "pharmacy", "Pending Pharmacy")
    ph = client.get("/conversations/contacts", params={"organization_id": w.supplier}, headers=w.supplier_owner).json()
    assert [c["name"] for c in ph] == ["Kigali Pharmacy"]  # not approved, not listed
