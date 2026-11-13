"""Browser test: dashboard charts, analytics and forecasting are for owners and
managers only, on both the pharmacy and the supplier dashboard.

For each dashboard, an owner, a manager and a staff member of the same real
organization sign in. Checked for each role:
  * owners and managers see the charts (stock health, order pipeline and open
    order value, most requested medicines), Forecasting and the Premium cards,
    with figures from the API;
  * staff see none of them, with no empty gap, no error and no request to the
    insights endpoint; their stock and order screens still work;
  * staff cannot get round it: forcing the hidden Forecasting button, or
    calling the insights endpoint with their own token (403);
  * a role change takes effect: a manager demoted while the page is open loses
    the charts on the next refresh.

LOCAL backend and throwaway database only, as e2e_dashboards.py (same setup):
  E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... python frontend/tests/e2e_dashboard_roles.py
"""

import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_dashboards as D  # noqa: E402  (shared API and UI helpers)

RUN, call, check, failures = D.RUN, D.call, D.check, D.failures
CHARTS = "#ins-health, #ins-pipe, #toprq, .ins"


def seed():
    admin = call("POST", "/auth/login", {"email": D.ADMIN_EMAIL, "password": D.ADMIN_PASSWORD})["access_token"]
    w = {"admin": admin}
    for key, name in (("p1", "Rolecillin"), ("p2", "Rolemycin"), ("p3", "Rolezole")):
        drug = call("POST", "/catalogue/drugs", {"name": f"{name} {RUN}", "therapeutic_class": "Antibiotic"}, admin)["drug_id"]
        w[key] = call("POST", "/catalogue/products", {"drug_id": drug, "product_name": f"{name} {RUN} 500mg"}, admin)["product_id"]
    for kind, locname in (("pharmacy", "Role Branch"), ("supplier", "Role Depot")):
        email = f"roles-{kind}-owner-{RUN}@example.com"
        token, org, (loc,) = D.org_with_owner(email, f"{kind.title()} Owner", f"Role {kind.title()} {RUN}", kind,
                                              [{"name": locname}], admin=admin)
        side = {"org": org, "loc": loc, "owner": token, "owner_email": email}
        for role in ("manager", "staff"):
            e = f"roles-{kind}-{role}-{RUN}@example.com"
            side[role] = D.account(e, f"{kind.title()} {role.title()}")
            side[role + "_email"] = e
            side[role + "_mid"] = call("POST", f"/organizations/{org}/members", {"email": e, "role": role}, token)["membership_id"]
        w[kind] = side
    ph, sp = w["pharmacy"], w["supplier"]
    # Pharmacy stock: one in stock, one low (8 <= 10), one out.
    base = f"/organizations/{ph['org']}/locations/{ph['loc']}/stock"
    for prod, qty, thr in ((w["p1"], 100, 10), (w["p2"], 8, 10), (w["p3"], 0, None)):
        call("PUT", f"{base}/{prod}", {"quantity": qty}, ph["owner"])
        if thr:
            call("PUT", f"{base}/{prod}/offer", {"unit_price": "1500", "low_stock_threshold": thr}, ph["owner"])
    # Supplier stock and price, then one real submitted order: 12 x 900 = 10,800 RWF open.
    call("PUT", f"/organizations/{sp['org']}/locations/{sp['loc']}/stock/{w['p1']}", {"quantity": 5000}, sp["owner"])
    call("PUT", f"/organizations/{sp['org']}/locations/{sp['loc']}/stock/{w['p1']}/offer", {"unit_price": "900"}, sp["owner"])
    order = call("POST", "/purchase-orders", {"pharmacy_organization_id": ph["org"], "supplier_organization_id": sp["org"],
                                              "pharmacy_location_id": ph["loc"], "items": [{"product_id": w["p1"], "quantity": 12}]}, ph["owner"])
    call("POST", f"/purchase-orders/{order['purchase_order_id']}/submit", {}, ph["owner"])
    w["order"] = order["purchase_order_id"]
    return w


def watch_insights(page):
    page.insights_calls = []
    page.on("request", lambda r: page.insights_calls.append(r.url) if "/insights" in r.url else None)


def settle(page):
    page.wait_for_function("() => !document.querySelector('#view').textContent.includes('Loading')", timeout=20000)


def api_from_page(page, path):
    """Call the API from inside the page with the signed-in user's own token."""
    return page.evaluate("""async ([api, path]) => {
        const s = JSON.parse(sessionStorage.getItem('apexrx_session') || 'null');
        const r = await fetch(api + path, { headers: { Authorization: 'Bearer ' + s.token } });
        return r.status;
    }""", [D.API, path])


def manager_view(page, kind, w, who):
    side = w[kind]
    settle(page)
    nav = page.locator(".nav[data-v=prem]")
    check(f"{kind} {who}: Forecasting in the menu and the Premium cards shown",
          nav.count() == 1 and page.is_visible(".pcard") and page.locator(".ov-premium").count() == 1)
    if kind == "pharmacy":
        legend = page.inner_text("#ins-health")
        check(f"{kind} {who}: stock health chart from the API (1 in, 1 low, 1 out)",
              page.locator("#ins-health .health span").count() == 3
              and [page.inner_text(f"#ins-health .health-l li:nth-child({i}) b") for i in (1, 2, 3)] == ["1", "1", "1"], legend)
    else:
        pipe = page.inner_text("#ins-pipe")
        check(f"{kind} {who}: order pipeline and open order value from the API",
              page.inner_text("#ins-pipe .pipe-s:first-child b") == "1" and "10,800 RWF" in pipe, pipe)
        check(f"{kind} {who}: most requested medicines from the API",
              f"Rolecillin {RUN} 500mg" in page.inner_text("#toprq") and "12 boxes" in page.inner_text("#toprq"))
    check(f"{kind} {who}: figures came from GET /insights", any("/insights" in u for u in page.insights_calls))
    check(f"{kind} {who}: the API answers 200", api_from_page(page, f"/organizations/{side['org']}/insights") == 200)
    D.open_view(page, "prem")
    page.wait_for_selector("#fc-root svg", timeout=15000)
    check(f"{kind} {who}: Forecasting screen opens with its charts", page.locator("#fc-root svg").count() > 0)
    D.open_view(page, "home")


def staff_view(page, kind, w):
    side = w[kind]
    settle(page)
    page.wait_for_timeout(800)  # anything late (an insights call) would show up now
    check(f"{kind} staff: labelled Staff", page.inner_text("#dash-user").endswith("· Staff"))
    check(f"{kind} staff: no charts, analytics or Premium cards",
          page.locator(CHARTS).count() == 0 and page.locator(".ov-premium").count() == 0 and page.is_hidden(".pcard")
          and page.locator(".nav[data-v=prem]").count() == 0)
    txt = page.inner_text("#view")
    check(f"{kind} staff: no error or 'not allowed' message", all(s not in txt for s in
          ("could not be loaded", "not allowed", "Your role does not allow", "requires:")))
    check(f"{kind} staff: the page never asks for the insights", page.insights_calls == [], str(page.insights_calls))
    check(f"{kind} staff: their attention list is still there", page.locator(".ov-act").count() >= 3)
    # No large gap: the expiry panel takes the whole row (pharmacy) or sits beside the attention list (supplier).
    if kind == "pharmacy":
        widths = page.evaluate("() => [document.querySelector('#shelf-life').getBoundingClientRect().width, document.querySelector('.ov-actions').getBoundingClientRect().width]")
        check("pharmacy staff: no gap where the chart was (shelf-life panel spans the row)", widths[0] >= widths[1] - 2, str(widths))
    else:
        check("supplier staff: the right column holds the shelf-life panel, no empty block",
              page.evaluate("() => document.querySelector('.sup-grid > div:nth-child(2)').children.length") == 1)
    # Getting round it.
    page.evaluate("() => { const c = document.querySelector('.pcard'); c.hidden = false; }")
    page.click("#p-b")
    page.wait_for_timeout(300)
    check(f"{kind} staff: forcing the hidden Forecasting button still shows the overview",
          page.inner_text("#title") == "Overview" and page.locator("#fc-root").count() == 0)
    page.evaluate("() => { document.querySelector('.pcard').hidden = true; }")
    status = api_from_page(page, f"/organizations/{side['org']}/insights")
    status_loc = api_from_page(page, f"/organizations/{side['org']}/insights?location_id={side['loc']}")
    check(f"{kind} staff: direct API call with their own token is refused (403)", status == 403 and status_loc == 403, f"{status} {status_loc}")
    # Their workflows.
    D.open_view(page, "stk")
    page.wait_for_selector("#view input[data-f=qty]", timeout=15000)
    check(f"{kind} staff: stock screen works, quantities editable", page.locator("#view input[data-f=qty]").first.is_enabled())
    D.open_view(page, "ord")
    page.wait_for_selector(f"tr[data-order='{w['order']}']", timeout=15000)
    check(f"{kind} staff: orders screen lists the real order", page.locator(f"tr[data-order='{w['order']}']").count() == 1)
    D.open_view(page, "msg")
    check(f"{kind} staff: messages screen opens", page.locator("#clist").count() == 1)
    D.open_view(page, "home")


def main():
    w = seed()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)
        for kind in ("pharmacy", "supplier"):
            side = w[kind]
            for who in ("owner", "manager"):
                page = D.new_page(browser)
                watch_insights(page)
                D.sign_in(page, side[f"{who}_email"], kind=kind)
                manager_view(page, kind, w, who)
                check(f"{kind} {who}: no page errors", not page.errors, "; ".join(page.errors))
                page.context.close()

            staff = D.new_page(browser)
            watch_insights(staff)
            D.sign_in(staff, side["staff_email"], kind=kind)
            staff_view(staff, kind, w)
            check(f"{kind} staff: no page errors", not staff.errors, "; ".join(staff.errors))
            staff.context.close()

            # Phone width: staff layout stays clean.
            mob = D.new_page(browser, {"width": 390, "height": 844})
            watch_insights(mob)
            D.sign_in(mob, side["staff_email"], kind=kind)
            settle(mob)
            check(f"{kind} staff (phone): no charts and no sideways scrolling",
                  mob.locator(CHARTS).count() == 0 and mob.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
            mob.context.close()

        # A manager demoted while the dashboard is open loses the charts on the next refresh.
        ph = w["pharmacy"]
        page = D.new_page(browser)
        watch_insights(page)
        D.sign_in(page, ph["manager_email"])
        settle(page)
        had = page.locator("#ins-health").count() == 1
        call("PATCH", f"/organizations/{ph['org']}/members/{ph['manager_mid']}", {"role": "staff"}, ph["owner"])
        page.click(".nav[data-v=home]")
        page.wait_for_function("() => document.querySelector('#dash-user')?.textContent.endsWith('· Staff')", timeout=20000)
        settle(page)
        check("demoted manager: charts gone after the refresh, now labelled Staff",
              had and page.locator(CHARTS).count() == 0 and page.locator(".nav[data-v=prem]").count() == 0)
        call("PATCH", f"/organizations/{ph['org']}/members/{ph['manager_mid']}", {"role": "manager"}, ph["owner"])
        page.reload()
        D.ready(page)
        settle(page)
        page.wait_for_selector("#ins-health .health-l", timeout=15000)
        check("promoted back to manager: charts return", page.locator("#ins-health").count() == 1)
        page.context.close()
        browser.close()

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
