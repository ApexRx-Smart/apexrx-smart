"""Browser test of the known-browser (device token) handling in js/api.js,
against a LOCAL backend. Never point this at production.

  1. Backend on http://127.0.0.1:8000 with a disposable database.
  2. Frontend on http://127.0.0.1:5501 (python -m http.server 5501 --directory frontend).
  3. pip install playwright && playwright install chromium
  4. python frontend/tests/e2e_known_browser.py

It registers a throwaway account per run, so it does not lock any real user.
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

SITE = os.environ.get("E2E_SITE", "http://127.0.0.1:5501")
API = os.environ.get("E2E_API", "http://127.0.0.1:8000")
EMAIL = f"known-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "Known-Browser-Pass-2026"
KEY = "apexrx_known_devices"
failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def api(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


LOGIN = """async ([email, password]) => {
  try { await ApexAPI.auth.login(email, password); return {ok: true, signedIn: ApexAPI.session.isSignedIn()}; }
  catch (e) { return {ok: false, status: e.status, message: e.message}; }
}"""

CORRUPTED = {
    "invalid JSON": "not json {",
    "JSON null": "null",
    "array": "[1, 2, 3]",
    "null entry for this email": json.dumps({EMAIL: None}),
    "string entry": json.dumps({EMAIL: "junk"}),
    "token is a number": json.dumps({EMAIL: {"token": 5, "savedAt": 1}}),
    "savedAt not a number": json.dumps({EMAIL: {"token": "abc.def", "savedAt": "soon"}, "other@x.com": None}),
    "forged token string": json.dumps({EMAIL: {"token": "forged.token", "savedAt": 1}}),
    "non-ASCII token": json.dumps({EMAIL: {"token": "abc.é", "savedAt": 1}}),
}


def main():
    assert api("/auth/register", {"name": "Known Browser", "email": EMAIL, "password": PASSWORD}) == 201

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("E2E_BROWSER_CHANNEL") or None, headless=True)

        def new_page():
            ctx = browser.new_context()
            ctx.route("**/js/config.js", lambda r: r.fulfill(
                content_type="application/javascript", body=f'window.APEX_CONFIG = {{ API_BASE_URL: "{API}" }};'))
            page = ctx.new_page()
            page.goto(SITE + "/ops-console-7f3k9q.html")
            page.wait_for_function("!!window.ApexAPI")
            return page

        page = new_page()
        # 1. Corrupted storage never makes a successful sign-in reject.
        for label, raw in CORRUPTED.items():
            page.evaluate("([k, v]) => { localStorage.setItem(k, v); sessionStorage.clear(); }", [KEY, raw])
            result = page.evaluate(LOGIN, [EMAIL, PASSWORD])
            stored = page.evaluate("k => JSON.parse(localStorage.getItem(k))", KEY)
            entry = stored.get(EMAIL) if isinstance(stored, dict) else None
            check(f"corrupted storage ({label}): sign-in resolves and session is saved",
                  result == {"ok": True, "signedIn": True})
            check(f"corrupted storage ({label}): repaired with a valid entry",
                  isinstance(entry, dict) and entry["token"].count(".") == 1 and isinstance(entry["savedAt"], int)
                  and all(isinstance(v, dict) for v in stored.values()))

        # 2. Storage that throws on write: sign-in still resolves.
        page.evaluate("() => { Storage.prototype.setItem = function () { throw new Error('quota'); }; }")
        result = page.evaluate(LOGIN, [EMAIL, PASSWORD])
        check("sign-in resolves when localStorage writes fail", result["ok"] is True)

        # 3. At most 5 remembered accounts.
        page = new_page()
        many = {f"old{i}@x.com": {"token": f"t{i}.s", "savedAt": i} for i in range(8)}
        page.evaluate("([k, v]) => localStorage.setItem(k, v)", [KEY, json.dumps(many)])
        page.evaluate(LOGIN, [EMAIL, PASSWORD])
        stored = page.evaluate("k => JSON.parse(localStorage.getItem(k))", KEY)
        check("keeps only the 5 most recent accounts, including this one",
              len(stored) == 5 and EMAIL in stored and "old0@x.com" not in stored)

        # 4. The known browser keeps working while the account is locked.
        codes = [api("/auth/login", {"email": EMAIL, "password": "attacker-guess"}) for _ in range(6)]
        check(f"attacker without a device token gets locked out {codes}", codes[:5] == [401] * 5 and codes[5] == 429)
        result = page.evaluate(LOGIN, [EMAIL, PASSWORD])
        check("known browser signs in during the lockout", result == {"ok": True, "signedIn": True})
        fresh = new_page()
        result = fresh.evaluate(LOGIN, [EMAIL, PASSWORD])
        check("a new browser is still locked out (429)", result["ok"] is False and result["status"] == 429)
        browser.close()

    print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
