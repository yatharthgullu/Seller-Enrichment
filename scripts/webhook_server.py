"""
Tiny webhook receiver for Sarvam's outbound-call completion events.

    python scripts/webhook_server.py            # listens on :8787

Sarvam must be able to reach it, so expose it with a tunnel while developing:
    ngrok http 8787            (or)   cloudflared tunnel --url http://localhost:8787
then put the public URL in .env as
    WEBHOOK_URL=https://<tunnel-host>/sarvam/webhook
    WEBHOOK_TOKEN=<any random string>      # checked as ?token=... (Sarvam documents no signature)

Each event (campaign or instant-outbound shape) is saved to
outputs/calls/<attempt_id>.result.json, which the Streamlit app reads and
matches to a seller by GLID. Standard library only, so it runs under the same
locked-down Python as the rest of the project.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sarvam_calls  # noqa: E402
from src.voice import env_value  # noqa: E402

PORT = 8787
MAX_BODY = 2_000_000


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply(200, {"ok": True, "service": "seller-enrichment webhook"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path.rstrip("/") != "/sarvam/webhook":
            return self._reply(404, {"error": "not found"})
        token = env_value("WEBHOOK_TOKEN")
        if token and parse_qs(url.query).get("token", [""])[0] != token:
            return self._reply(403, {"error": "bad token"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self._reply(400, {"error": "bad body size"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("attempt_id"):
                raise ValueError("no attempt_id")
        except ValueError as e:
            return self._reply(400, {"error": str(e)})
        sarvam_calls.save_raw(payload)
        rec = sarvam_calls.normalize(payload)
        print(f"[webhook] {rec['attempt_id']} glid={rec['glid'] or '?'} status={rec['status']}", flush=True)
        self._reply(200, {"ok": True})

    def log_message(self, *args):  # keep the console quiet
        pass


if __name__ == "__main__":
    print(f"[webhook] listening on http://0.0.0.0:{PORT}/sarvam/webhook  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
