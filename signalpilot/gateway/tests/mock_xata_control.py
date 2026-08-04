"""Stand-in Xata control plane for exercising the demo-connector flow locally.

The real Xata org can be billing-disabled (writes 403), so this serves the
same REST surface the gateway uses: list/create/delete branches + credentials.
Every call is appended to mock_xata_control.log for test assertions.

Usage:  python tests/mock_xata_control.py [port]   (default 5099)
"""

from __future__ import annotations

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG = Path(__file__).with_name("mock_xata_control.log")

# Seeded parent branch. the "shared contoso demo db".
BRANCHES: dict[str, dict] = {
    "parent0main": {"id": "parent0main", "name": "main", "region": "us-east-1"},
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict | None = None) -> None:
        body = json.dumps(payload or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self, line: str) -> None:
        with LOG.open("a") as f:
            f.write(line + "\n")

    def do_GET(self):
        self._log(f"GET {self.path}")
        if self.path.endswith("/credentials") or "/credentials?" in self.path:
            self._send(200, {"username": "xata", "password": "mock-pw"})
        elif self.path.endswith("/branches"):
            self._send(200, {"branches": list(BRANCHES.values())})
        else:
            self._send(404, {"message": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self._log(f"POST {self.path} {json.dumps(body)}")
        if self.path.endswith("/branches"):
            bid = uuid.uuid4().hex[:12]
            branch = {"id": bid, "name": body.get("name"), "region": "us-east-1",
                      "parentID": body.get("parentID")}
            BRANCHES[bid] = branch
            self._send(201, branch)
        else:
            self._send(404, {"message": "not found"})

    def do_DELETE(self):
        self._log(f"DELETE {self.path}")
        bid = self.path.rstrip("/").split("/")[-1]
        if bid in BRANCHES:
            del BRANCHES[bid]
            self._send(200, {})
        else:
            self._send(404, {"message": f"branch {bid} not found"})

    def log_message(self, *args):  # silence default stderr logging
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5099
    LOG.write_text("")
    print(f"mock xata control plane on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
