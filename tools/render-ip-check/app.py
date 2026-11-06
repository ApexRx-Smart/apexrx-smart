"""Temporary Render diagnostic: which client-IP headers reach a Render app?

Deploy as a SEPARATE, temporary Render web service (not the ApexRx backend):
    Root directory: tools/render-ip-check
    Build command:  (leave empty, or `true`)
    Start command:  python app.py

It returns only the IP-related request headers and the TCP peer address
(no cookies, no other headers) and stores nothing. Delete the service after
the test. See README.md in this folder for the test procedure.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEADERS = ("True-Client-IP", "CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP", "CF-Ray", "CF-IPCountry")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {
                "tcp_peer": self.client_address[0],
                "headers": {name: self.headers.get(name) for name in HEADERS},
            },
            indent=2,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # do not log client IPs
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Handler).serve_forever()
