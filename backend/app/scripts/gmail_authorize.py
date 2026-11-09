"""Get the Gmail API refresh token for the ApexRX sending account (run once, locally).

    python -m app.scripts.gmail_authorize --client-id ID --client-secret SECRET

Needs a Google Cloud OAuth client of type "Desktop app" (see the root README,
"Email delivery with the Gmail API"). It opens Google's consent page in your
browser; sign in as the dedicated ApexRX Gmail account and allow "Send email
on your behalf" (scope gmail.send only). Google redirects back to a temporary
local address (127.0.0.1), and the script exchanges the code for tokens using
PKCE.

The refresh token is printed ONCE, on this terminal only. Put it in Render as
GMAIL_REFRESH_TOKEN (and in your local backend/.env if you test locally). Never
commit it, paste it in chat or share it: it lets anyone send email as the account.
"""

import argparse
import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.send"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("ApexRX: authorization received. You can close this tab.".encode())

        def log_message(self, *a):  # keep the terminal quiet (the URL holds the code)
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("Opening Google's consent page. If it does not open, visit:\n" + url + "\n")
    print("Sign in as the ApexRX sending account and allow sending email.")
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    webbrowser.open(url)
    thread.join(timeout=300)
    server.server_close()

    if result.get("state") != state or "code" not in result:
        print(f"Authorization failed: {result.get('error', 'no answer within 5 minutes')}", file=sys.stderr)
        return 1
    response = httpx.post(TOKEN_URL, data={
        "code": result["code"], "client_id": args.client_id, "client_secret": args.client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    }, timeout=30)
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or "refresh_token" not in data:
        print(f"Token exchange failed: HTTP {response.status_code} {data.get('error', '')}", file=sys.stderr)
        return 1
    if SCOPE not in data.get("scope", ""):
        print("Warning: the gmail.send permission was not granted.", file=sys.stderr)
    print("\nGMAIL_REFRESH_TOKEN (shown once; store it only in Render / backend/.env):\n")
    print(data["refresh_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
