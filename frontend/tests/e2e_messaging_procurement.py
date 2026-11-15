"""Browser test: in-platform messaging and procurement requests between a
pharmacy and a supplier, driven through both dashboards side by side.

Messaging: the supplier starts a conversation with the pharmacy, the pharmacy
sees it (unread count, notification), replies, the supplier receives the reply
by polling, history survives a reload, unread clears once read, an unrelated
organization cannot reach it, and nothing opens WhatsApp.

Procurement: the pharmacy sends one request with a medicine the supplier
lists, one it does not list and one that is not in the catalogue; the supplier
opens it, saves a draft, quotes two items and marks one unavailable; the
pharmacy asks for a revision; the supplier sends a revised quotation; staff
cannot accept; the manager accepts and creates the order; the order carries
the agreed items, quantities and prices and the supplier processes it in
Orders; the request and both revisions stay readable; a repeated conversion
returns the same order; another organization cannot read the request.

LOCAL backend and throwaway database only, as e2e_dashboards.py (same setup):
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_messaging_procurement.py
"""

import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_dashboards as D  # noqa: E402  (shared API and UI helpers)

RUN, call, check, failures = D.RUN, D.call, D.check, D.failures
PH_NAME, SUP_NAME = f"Msg Pharmacy {RUN}", f"Msg Supplier {RUN}"


def seed():
    admin = call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD})["access_token"]
    w = {"admin": admin}
    for key, name in (("listed", "Msgcillin"), ("unlisted", "Msgformin")):
        drug = call("POST", "/catalogue/drugs", {"name": f"{name} {RUN}", "therapeutic_class": "Antibiotic"}, admin)["drug_id"]
        w[key] = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"{name} {RUN} 500mg",
                                                      "pack_size": "B/20"}, admin)["product_id"]
    w["ph_email"] = f"msg-ph-{RUN}@example.com"
    w["ph"], w["ph_org"], (w["ph_loc"],) = D.org_with_owner(w["ph_email"], "Pharma Owner", PH_NAME, "pharmacy",
                                                            [{"name": "Kacyiru Branch", "city": "Gasabo"}], admin=admin)
    w["sup_email"] = f"msg-sup-{RUN}@example.com"
    w["sup"], w["sup_org"], (w["sup_loc"],) = D.org_with_owner(w["sup_email"], "Depot Owner", SUP_NAME, "supplier",
                                                               [{"name": "Gikondo Depot", "city": "Kicukiro"}], admin=admin)
    call("PUT", f"/organizations/{w['sup_org']}/locations/{w['sup_loc']}/stock/{w['listed']}", {"quantity": 900}, w["sup"])
    call("PUT", f"/organizations/{w['sup_org']}/locations/{w['sup_loc']}/stock/{w['listed']}/offer", {"unit_price": "170"}, w["sup"])
    # Pharmacy staff member, and an unrelated approved pharmacy.
    w["staff_email"] = f"msg-staff-{RUN}@example.com"
    w["staff"] = D.account(w["staff_email"], "Pharma Clerk")
    call("POST", f"/organizations/{w['ph_org']}/members", {"email": w["staff_email"], "role": "staff"}, w["ph"])
    w["other_email"] = f"msg-other-{RUN}@example.com"
    w["other"], w["other_org"], _ = D.org_with_owner(w["other_email"], "Other Owner", f"Other Pharmacy {RUN}", "pharmacy",
                                                     [{"name": "Remera"}], admin=admin)
    return w


def no_whatsapp(page):
    """Record any window.open (the old chat opened wa.me in a new tab)."""
    page.add_init_script("window.__opened = []; window.open = (...a) => { window.__opened.push(String(a[0])); return null; };")


def wait(page, selector, text, timeout=20000):
    D.wait_text(page, selector, text, timeout)


def settle(page):
    page.wait_for_function("() => !document.querySelector('#view').textContent.includes('Loading')", timeout=20000)


def bell_count(page):
    return 0 if page.is_hidden("#bell-n") else int(page.inner_text("#bell-n"))


def messaging(browser, w):
    sup = D.new_page(browser); no_whatsapp(sup)
    D.sign_in(sup, w["sup_email"], kind="supplier")
    # 1. The supplier starts a conversation with the pharmacy from the directory.
    D.open_view(sup, "msg")
    sup.click("#clist [data-a=newconv]")
    sup.fill("#nc-q", PH_NAME)
    sup.wait_for_selector(f"#nc-l .pick-i[data-s='{w['ph_org']}']")
    check("directory lists approved pharmacies only (no other suppliers)",
          sup.locator("#nc-l .pick-i").count() >= 1 and SUP_NAME not in sup.inner_text("#nc-l"))
    sup.click(f"#nc-l .pick-i[data-s='{w['ph_org']}']")
    wait(sup, "#thread .th", PH_NAME)
    sup.fill("#msg", "Hello from the depot. We can supply Msgcillin this week.")
    sup.click("#sendf .solid")
    wait(sup, "#msgs", "We can supply Msgcillin this week.")
    check("supplier: message sent in ApexRX and shown in the thread", sup.locator("#msgs .b.out .tx").count() == 1)
    convs = call("GET", f"/conversations?organization_id={w['sup_org']}", token=w["sup"])["items"]
    check("one stored conversation for the pair", len(convs) == 1 and convs[0]["counterpart"]["organization_id"] == w["ph_org"])
    w["conv"] = convs[0]["conversation_id"]

    # 2. The pharmacy sees it: notification, unread count, preview, "Supplier" label.
    ph = D.new_page(browser); no_whatsapp(ph)
    D.sign_in(ph, w["ph_email"])
    check("pharmacy: the bell shows the new message", bell_count(ph) == 1)
    ph.click("#bell")
    check("pharmacy: notification names the supplier", f"New message from {SUP_NAME}" in ph.inner_text("#npanel"))
    ph.click("#npanel [data-a=nopen]")
    wait(ph, "#msgs", "We can supply Msgcillin this week.")
    item = ph.locator(f"#clist .citem[data-c='{w['sup_org']}']")
    check("pharmacy: conversation listed with name, type and last message",
          SUP_NAME in item.inner_text() and "Supplier" in item.inner_text() and "We can supply" in item.inner_text())
    check("pharmacy: sender identified on the message", "Depot Owner" in ph.inner_text("#msgs .b.in"))
    ph.wait_for_function("() => document.querySelector('#bell-n').hidden && !document.querySelector('#clist .unread')", timeout=10000)
    unread = call("GET", f"/conversations?organization_id={w['ph_org']}", token=w["ph"])["unread_total"]
    check("pharmacy: reading the conversation clears the unread count and the bell (also on the server)",
          ph.locator("#clist .unread").count() == 0 and bell_count(ph) == 0 and unread == 0, str(unread))

    # 3. The pharmacy replies (Enter sends).
    ph.fill("#msg", "Great, please send prices for 100 boxes.")
    ph.press("#msg", "Enter")
    wait(ph, "#msgs", "please send prices for 100 boxes")
    # 4. The supplier's open thread receives it by polling.
    wait(sup, "#msgs", "please send prices for 100 boxes", timeout=20000)
    check("supplier: the reply arrives without reloading", "Pharma Owner" in sup.inner_text("#msgs"))
    # 5. History persists after a reload, in order.
    sup.reload(); D.ready(sup); D.open_view(sup, "msg")
    wait(sup, "#msgs", "please send prices")
    bodies = sup.locator("#msgs .tx").all_inner_texts()
    check("history persists after a reload, in order", bodies == [
        "Hello from the depot. We can supply Msgcillin this week.", "Great, please send prices for 100 boxes."], str(bodies))
    # 7. An unrelated organization cannot reach it.
    status, _ = call("GET", f"/conversations/{w['conv']}/messages", token=w["other"], expect_error=True)
    status2, _ = call("POST", f"/conversations/{w['conv']}/messages", {"body": "hi"}, token=w["other"], expect_error=True)
    check("unrelated organization: 404 on read and write", status == 404 and status2 == 404, f"{status} {status2}")
    # 8. Nothing redirects to WhatsApp.
    for name, page in (("supplier", sup), ("pharmacy", ph)):
        check(f"{name}: no wa.me link and nothing opened in a new tab",
              page.locator("a[href*='wa.me']").count() == 0 and page.evaluate("window.__opened.length") == 0
              and "WhatsApp" not in page.inner_text("#sendf"))
    # Phone width: the messaging screen fits.
    mob = D.new_page(browser, {"width": 390, "height": 844})
    D.sign_in(mob, w["ph_email"]); D.open_view(mob, "msg")
    wait(mob, "#msgs", "please send prices")
    check("phone width: messages fit without sideways scrolling",
          mob.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
    mob.context.close()
    return ph, sup


def procurement(browser, w, ph, sup):
    # 1-2. The pharmacy builds a request: listed, unlisted, and outside the catalogue.
    D.open_view(ph, "rq")
    ph.click("#view [data-a=rqnew]")
    ph.fill("#rq-sup", SUP_NAME)
    ph.wait_for_selector(f"#rq-supl .pick-i[data-s='{w['sup_org']}']")
    ph.click(f"#rq-supl .pick-i[data-s='{w['sup_org']}']")
    for key, term in (("listed", "Msgcillin"), ("unlisted", "Msgformin")):
        ph.fill("#rq-q", f"{term} {RUN}")
        ph.wait_for_selector(f"#rq-ql .pick-i[data-p='{w[key]}']")
        ph.click(f"#rq-ql .pick-i[data-p='{w[key]}']")
    ph.click("#rq-cd summary")
    ph.fill("#rc-n", "Artemether-Lumefantrine"); ph.fill("#rc-s", "20/120mg"); ph.fill("#rc-f", "tablet"); ph.fill("#rc-p", "B/24")
    ph.click("[data-a=rqaddc]")
    qty = ph.locator("#rq-items input[data-k=quantity]")
    for i, n in enumerate(("100", "20", "50")):
        qty.nth(i).fill(n)
    ph.locator("#rq-items input[data-k=notes]").nth(1).fill("Blister packs preferred")
    ph.fill("#rq-notes", "Deliver to Kacyiru before Friday.")
    ph.click("[data-a=rqreview]")
    wait(ph, "#rqn", "Review your request")
    check("review step lists the three medicines before sending",
          ph.locator("#rqn tbody tr").count() == 3 and "Not in the catalogue" in ph.inner_text("#rqn"))
    ph.click("[data-a=rqsend]")
    wait(ph, "#rqd", "Procurement request #")
    req = call("GET", f"/procurement-requests?organization_id={w['ph_org']}", token=w["ph"])["items"][0]
    rid = req["procurement_request_id"]
    detail = call("GET", f"/procurement-requests/{rid}", token=w["ph"])
    check("request stored with 3 items (catalogue, unlisted, described)",
          [(i["in_catalogue"], i["quantity"]) for i in detail["items"]] == [(True, 100), (True, 20), (False, 50)]
          and detail["items"][2]["medicine_name"] == "Artemether-Lumefantrine" and detail["status"] == "submitted")
    check("pharmacy: status shown as Sent", "Sent" in ph.inner_text("#rqd .rq-t"))

    # 3. The supplier receives it.
    sup.reload(); D.ready(sup)
    check("supplier: bell notification for the new request", bell_count(sup) >= 1)
    sup.click("#bell")
    check("supplier: notification text", f"{PH_NAME} sent you a procurement request." in sup.inner_text("#npanel"))
    sup.click("#npanel [data-a=nopen]:has-text('procurement request')")
    sup.wait_for_selector("#qf")
    check("supplier: request shows the pharmacy, items, notes and specifications",
          PH_NAME in sup.inner_text("#rqd") and "Deliver to Kacyiru" in sup.inner_text("#rqd")
          and "Blister packs preferred" in sup.inner_text("#rqd") and "20/120mg" in sup.inner_text("#rqd"))
    check("opening marks it seen for the pharmacy",
          call("GET", f"/procurement-requests/{rid}", token=w["ph"])["status"] == "viewed")

    # 4. Supplier: a draft first, then the quotation (two available, one unavailable).
    rows = sup.locator("#qf tr[data-qi]")
    rows.nth(0).locator("[data-q=price]").fill("160")
    rows.nth(1).locator("[data-q=qty]").fill("15"); rows.nth(1).locator("[data-q=price]").fill("2500")
    rows.nth(1).locator("[data-q=note]").fill("Only 15 boxes left")
    rows.nth(2).locator("[data-q=av]").uncheck()
    check("supplier: line totals and total computed as typed", "53,500 RWF" in sup.inner_text("#qf-total"))
    sup.click("[data-a=qsave]")
    wait(sup, "#toast", "Draft saved")
    check("draft is invisible to the pharmacy", call("GET", f"/procurement-requests/{rid}", token=w["ph"])["quotations"] == [])
    sup.fill("#qf-days", "3")
    sup.click("[data-a=qsend]")
    D.confirm(sup)
    wait(sup, "#rqd", "Quotation sent")
    check("supplier: revision 1 shown as waiting for the pharmacy", "Waiting for the pharmacy" in sup.inner_text("#rqd"))

    # 5. The pharmacy reviews it. Staff can only ask for a revision.
    staff = D.new_page(browser)
    D.sign_in(staff, w["staff_email"])
    staff.click(".nav[data-v=rq]"); staff.click(f"[data-a=rqopen][data-r='{rid}']")
    wait(staff, "#rqd", "Quotation, revision 1")
    acts = staff.locator("#rqd [data-a=rqact]").evaluate_all("els => els.map(e => e.dataset.x)")
    check("staff: may ask for a revision but not accept, reject or cancel", acts == ["request_revision"], str(acts))
    q1 = call("GET", f"/procurement-requests/{rid}", token=w["ph"])["quotations"][-1]["quotation_id"]
    status, _ = call("POST", f"/procurement-requests/{rid}/quotations/{q1}/accept", {}, token=w["staff"], expect_error=True)
    check("staff: accepting through the API is refused (403)", status == 403, str(status))
    staff.context.close()

    ph.reload(); D.ready(ph)
    ph.click("#bell")
    check("pharmacy: notified of the quotation", f"{SUP_NAME} sent you a quotation." in ph.inner_text("#npanel"))
    ph.click("#npanel [data-a=nopen]:has-text('quotation')")
    wait(ph, "#rqd", "Quotation, revision 1")
    block = ph.inner_text("#rqd .qb")
    check("pharmacy: quotation with prices, total, unavailable item and estimate",
          "53,500 RWF" in block and "Not available" in block and "Only 15 boxes left" in block and "3 days" in block, block[:300])

    # 6. Ask for a revision.
    ph.click("[data-a=rqact][data-x=request_revision]")
    D.confirm(ph, {"note": "Can you do 150 per box for Msgcillin?"})
    wait(ph, "#rqd .rq-t", "Revision requested")
    # 7. The supplier sends a revised quotation; the first is kept as superseded.
    sup.reload(); D.ready(sup)
    sup.click(".nav[data-v=rq]"); sup.click(f"[data-a=rqopen][data-r='{rid}']")
    sup.wait_for_selector("#qf")
    check("supplier: sees the pharmacy's revision note and a prefilled form",
          "Can you do 150 per box" in sup.inner_text("#rqd") and "Send a revised quotation" in sup.inner_text("#qf")
          and sup.locator("#qf tr[data-qi]").nth(1).locator("[data-q=price]").input_value() == "2500")
    sup.locator("#qf tr[data-qi]").nth(0).locator("[data-q=price]").fill("150")
    sup.click("[data-a=qsend]"); D.confirm(sup)
    wait(sup, "#rqd", "Quotation, revision 2")
    revs = [(q["revision"], q["status"]) for q in call("GET", f"/procurement-requests/{rid}", token=w["ph"])["quotations"]]
    check("revision history kept: 1 superseded, 2 submitted", revs == [(1, "superseded"), (2, "submitted")], str(revs))

    # 8. The manager (owner) accepts. No order yet.
    ph.reload(); D.ready(ph); ph.click(".nav[data-v=rq]"); ph.click(f"[data-a=rqopen][data-r='{rid}']")
    wait(ph, "#rqd", "Quotation, revision 2")
    check("pharmacy: earlier revision still readable", "1 earlier revision" in ph.inner_text("#rqd"))
    ph.click("[data-a=rqact][data-x=accept]"); D.confirm(ph)
    wait(ph, "#rqd .rq-t", "Quotation accepted")
    orders = call("GET", f"/purchase-orders?organization_id={w['ph_org']}", token=w["ph"])["items"]
    check("accepting does not create an order by itself", not [o for o in orders if o["procurement_request_id"] == rid])

    # 9-10. Create the order; it has the agreed lines and refers back.
    ph.click("[data-a=rqact][data-x=convert]"); D.confirm(ph)
    wait(ph, "#toast", "created")
    oid = call("GET", f"/procurement-requests/{rid}", token=w["ph"])["purchase_order_id"]
    order = call("GET", f"/purchase-orders/{oid}", token=w["sup"])
    lines = [(i["product_name"], i["confirmed_quantity"], i["confirmed_unit_price"]) for i in order["items"]]
    check("order created with the agreed items, quantities and prices",
          order["status"] == "accepted" and order["procurement_request_id"] == rid
          and lines == [(f"Msgcillin {RUN} 500mg", 100, "150.00"), (f"Msgformin {RUN} 500mg", 15, "2500.00")]
          and order["confirmed_total"] == "52500.00", str(lines))
    check("pharmacy: request shows the order and no further actions",
          ph.locator(f"[data-a=rqorder][data-o='{oid}']").count() == 1 and ph.locator("#rqd [data-a=rqact]").count() == 0)
    # 12. Repeating the conversion returns the same order.
    again = call("POST", f"/procurement-requests/{rid}/convert", {}, token=w["ph"])
    linked = [o for o in call("GET", f"/purchase-orders?organization_id={w['ph_org']}", token=w["ph"])["items"]
              if o["procurement_request_id"] == rid]
    check("no duplicate order on a repeated conversion", again["purchase_order_id"] == oid and not again["created"] and len(linked) == 1)

    # The supplier processes it in the existing Orders workflow.
    sup.reload(); D.ready(sup); D.open_view(sup, "ord")
    row = f"tr[data-order='{oid}']"
    sup.wait_for_selector(row)
    check("supplier: order in Orders with the agreed total", "52,500 RWF" in sup.inner_text(row))
    sup.click(f"{row} [data-x=start-processing]")
    wait(sup, row, "Being prepared")
    check("supplier: order moves on in the existing workflow",
          call("GET", f"/purchase-orders/{oid}", token=w["ph"])["status"] == "processing")
    # 11. The original request and its quotations stay accessible.
    D.open_view(sup, "rq"); sup.click(f"[data-a=rqopen][data-r='{rid}']")
    wait(sup, "#rqd", "Order created")
    check("supplier: request, accepted revision and history still readable",
          "Quotation, revision 2" in sup.inner_text("#rqd") and "1 earlier revision" in sup.inner_text("#rqd"))
    # 13. Another organization cannot read or act on it.
    statuses = [call("GET", f"/procurement-requests/{rid}", token=w["other"], expect_error=True)[0],
                call("POST", f"/procurement-requests/{rid}/convert", {}, token=w["other"], expect_error=True)[0]]
    check("another organization: 404", statuses == [404, 404], str(statuses))
    # The request appears in the pair's conversation too.
    D.open_view(ph, "msg"); ph.click(f"#clist .citem[data-c='{w['sup_org']}']")
    wait(ph, "#msgs", f"Procurement request #{rid}")
    check("the conversation shows the request and the resulting order",
          f"Order list #{oid}" in ph.inner_text("#msgs") and f"From procurement request #{rid}" in ph.inner_text("#msgs"))
    # French labels.
    ph.goto(ph.url.split("?")[0] + "?lang=fr"); D.ready(ph)
    check("French: the new screen is translated", "Demandes d’approvisionnement" in ph.inner_text("#nav"))
    mob = D.new_page(browser, {"width": 390, "height": 844})
    D.sign_in(mob, w["sup_email"], kind="supplier"); D.open_view(mob, "rq")
    mob.click(f"[data-a=rqopen][data-r='{rid}']"); wait(mob, "#rqd", "Requested medicines")
    check("phone width: request detail fits without sideways scrolling",
          mob.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
    mob.context.close()
    for name, page in (("pharmacy", ph), ("supplier", sup)):
        check(f"{name}: no page errors", not page.errors, "; ".join(page.errors))


def main():
    w = seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        ph, sup = messaging(browser, w)
        procurement(browser, w, ph, sup)
        browser.close()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
