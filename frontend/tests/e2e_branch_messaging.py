"""Branch-scoped pharmacy messaging in a real browser, against a LOCAL backend
and a throwaway database (run like the other e2e tests):

  1. The owner assigns a staff member to a branch from Settings -> Team.
  2. Staff see their branch's supplier conversation and messages only; on
     another branch they are told they are not assigned to it.
  3. The owner sees every branch's conversation by switching branch; a
     message notification opens the right branch.
  4. The supplier sees one thread per pharmacy branch ("Pharmacy · Branch");
     a reply stays in that branch's conversation. Messages show who sent them
     and for which organization.
  5. Phone width.

Accounts, branches and messages are created through the API with
example.com addresses in the throwaway database only.
"""

import sys

from playwright.sync_api import sync_playwright

import e2e_dashboards as D  # noqa: E402

RUN, PW, check, failures = D.RUN, D.PW, D.check, D.failures


def main():
    admin = D.call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD,
                                           "account_type": "admin"})["access_token"]
    owner_email = f"bm-owner-{RUN}@example.com"
    owner, ph, (down, rem) = D.org_with_owner(owner_email, "Branch Owner", f"Branch Pharmacy {RUN}", "pharmacy",
                                              [{"name": "Downtown"}, {"name": "Remera", "latitude": -1.9577, "longitude": 30.1127}],
                                              admin=admin)
    sup_email = f"bm-supplier-{RUN}@example.com"
    sup, sp, _ = D.org_with_owner(sup_email, "Supply Owner", f"Branch Supplies {RUN}", "supplier",
                                  [{"name": "Depot"}], admin=admin)
    staff_email, rem_email = f"bm-down-{RUN}@example.com", f"bm-rem-{RUN}@example.com"
    for email, name in ((staff_email, "Dina Downtown"), (rem_email, "Remy Remera")):
        D.account(email, name, "pharmacy")
        D.call("POST", f"/organizations/{ph}/members", {"email": email, "role": "staff"}, owner)
    members = {m["email"]: m for m in D.call("GET", f"/organizations/{ph}/members", token=owner)}
    D.call("PUT", f"/organizations/{ph}/members/{members[rem_email]['membership_id']}/branches",
           {"location_ids": [rem]}, owner)
    conv_down = D.call("POST", "/conversations", {"organization_id": ph, "counterpart_organization_id": sp,
                                                  "pharmacy_location_id": down}, owner)["conversation_id"]
    conv_rem = D.call("POST", "/conversations", {"organization_id": sp, "counterpart_organization_id": ph,
                                                 "pharmacy_location_id": rem}, sup)["conversation_id"]
    D.call("POST", f"/conversations/{conv_down}/messages", {"body": f"Downtown order {RUN}"}, sup)
    D.call("POST", f"/conversations/{conv_rem}/messages", {"body": f"Remera order {RUN}"}, sup)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=D.os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        errors = []

        # ---- 1. the owner assigns Dina to Downtown in Settings -> Team
        page = D.new_page(browser)
        D.sign_in(page, owner_email)
        D.open_view(page, "set")
        row = f"#team tr[data-member='{staff_email}']"
        page.wait_for_selector(row)
        check("1. a staff member with no branch is flagged: sees no supplier messages",
              "No branch" in page.inner_text(row))
        page.click(f"{row} [data-a=brs]")
        page.wait_for_selector("#dlg[open] input[name=b]")
        page.check(f"#dlg input[name=b][value='{down}']")
        page.click("#dlg button.solid")
        D.wait_text(page, row, "Messages: Downtown")
        assigned = {m["email"]: m["branch_ids"] for m in D.call("GET", f"/organizations/{ph}/members", token=owner)}
        check("1. the assignment is saved", assigned[staff_email] == [down] and assigned[rem_email] == [rem], assigned)

        # ---- 3. owner: every branch, by switching branch
        page.select_option("#br", str(down))
        D.open_view(page, "msg")
        page.click("#clist .citem")
        D.wait_text(page, "#msgs", f"Downtown order {RUN}")
        check("3. owner on Downtown: the Downtown conversation only",
              f"Remera order {RUN}" not in page.inner_text("#msgs"))
        check("4. a message shows its sender and the sender's organization",
              f"Supply Owner · Branch Supplies {RUN}" in page.inner_text("#msgs"))
        page.select_option("#br", str(rem))
        page.wait_for_function("document.querySelector('#clist .citem') !== null", timeout=20000)
        page.click("#clist .citem")
        D.wait_text(page, "#msgs", f"Remera order {RUN}")
        check("3. owner switching to Remera sees Remera's conversation", f"Downtown order {RUN}" not in page.inner_text("#msgs"))
        # A notification about Downtown opens Downtown.
        D.call("POST", f"/conversations/{conv_down}/messages", {"body": f"Downtown again {RUN}"}, sup)
        page.reload()
        D.ready(page)
        page.select_option("#br", str(rem))
        page.click("#bell")
        page.wait_for_selector("#npanel:not([hidden]) [data-a=nopen]")
        page.click("#npanel [data-a=nopen]")
        D.wait_text(page, "#msgs", f"Downtown again {RUN}")
        check("3. a message notification opens its branch's conversation", page.input_value("#br") == str(down))
        page.context.close()

        # ---- 2. staff: their branch only
        page = D.new_page(browser)
        D.sign_in(page, staff_email)
        page.select_option("#br", str(down))
        D.open_view(page, "msg")
        page.click("#clist .citem")
        D.wait_text(page, "#msgs", f"Downtown order {RUN}")
        check("2. staff see their branch's conversation", f"Remera order {RUN}" not in page.inner_text("#msgs"))
        page.fill("#msg", f"Dina here {RUN}")
        page.click("#sendf .solid")
        D.wait_text(page, "#msgs", f"Dina here {RUN}")
        page.select_option("#br", str(rem))
        D.wait_text(page, "#clist", "not assigned to this branch")
        check("2. on another branch: told they are not assigned, and no messages",
              page.locator("#clist .citem").count() == 0 and f"Remera order {RUN}" not in page.inner_text("#view"))
        token = page.evaluate("JSON.parse(sessionStorage.getItem('apexrx_session')).token")
        status, _ = D.call("GET", f"/conversations/{conv_rem}/messages", token=token, expect_error=True)
        check("2. the API refuses another branch's conversation (404)", status == 404)
        page.context.close()

        # ---- 4. supplier: one thread per pharmacy branch
        page = D.new_page(browser)
        D.sign_in(page, sup_email, kind="supplier")
        D.open_view(page, "msg")
        page.wait_for_function("document.querySelectorAll('#clist .citem').length >= 2", timeout=20000)
        names = page.locator("#clist .citem strong").all_text_contents()
        check("4. the supplier sees each pharmacy branch as its own thread",
              {f"Branch Pharmacy {RUN} · Downtown", f"Branch Pharmacy {RUN} · Remera"} <= set(names), names)
        page.click(f"#clist .citem:has-text('· Remera')")
        D.wait_text(page, "#msgs", f"Remera order {RUN}")
        check("4. the Remera thread shows only Remera's messages",
              f"Downtown order {RUN}" not in page.inner_text("#msgs") and f"Dina here {RUN}" not in page.inner_text("#msgs"))
        page.fill("#msg", f"Delivery to Remera {RUN}")
        page.click("#sendf .solid")
        D.wait_text(page, "#msgs", f"Delivery to Remera {RUN}")
        in_rem = [m["body"] for m in D.call("GET", f"/conversations/{conv_rem}/messages", token=owner)["items"]]
        in_down = [m["body"] for m in D.call("GET", f"/conversations/{conv_down}/messages", token=owner)["items"]]
        check("4. the reply is stored in Remera's conversation only",
              f"Delivery to Remera {RUN}" in in_rem and f"Delivery to Remera {RUN}" not in in_down)
        page.click("[data-a=newconv]")
        page.wait_for_selector("#dlg[open] #nc-q")
        page.fill("#nc-q", f"Branch Pharmacy {RUN}")
        page.wait_for_function("document.querySelectorAll('#nc-l .pick-i').length >= 2", timeout=20000)
        picks = page.locator("#nc-l .pick-i strong").all_text_contents()
        check("4. starting a conversation, the supplier chooses the pharmacy branch",
              {f"Branch Pharmacy {RUN} · Downtown", f"Branch Pharmacy {RUN} · Remera"} <= set(picks), picks)
        page.keyboard.press("Escape")
        page.context.close()

        # ---- 5. phone width
        page = D.new_page(browser, {"width": 390, "height": 844})
        D.sign_in(page, rem_email)
        page.select_option("#br", str(rem))
        D.open_view(page, "msg")
        page.wait_for_selector("#clist .citem")
        check("5. phone: the branch's conversation is listed and nothing scrolls sideways",
              not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        errors += page.errors
        page.context.close()

        check("no script errors", not errors, errors[:3])
        browser.close()
    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
