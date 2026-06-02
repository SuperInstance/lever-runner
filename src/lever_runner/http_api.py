"""
http_api.py — minimal JSON HTTP API on :8765.

    POST /run   {"request": "check disk usage"}
    POST /teach {"intent_phrase": "...", "command": "..."}
    GET  /status

We use stdlib http.server so we don't pull in a web framework.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from dotenv import load_dotenv

from .orchestrator import do, status, teach

load_dotenv()
PORT = int(os.getenv("HTTP_PORT", "8765"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if urlparse(self.path).path == "/status":
            self._send(200, status())
        elif urlparse(self.path).path == "/healthz":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length) if length else b""
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as e:
            return self._send(400, {"error": f"bad json: {e}"})

        path = urlparse(self.path).path
        if path == "/run":
            request = data.get("request", "").strip()
            if not request:
                return self._send(400, {"error": "missing 'request'"})
            r = do(request, source="http")
            payload = {
                "ok": r.ok,
                "intent": r.intent,
                "command": r.match.command if r.match else None,
                "exit_code": r.run.exit_code if r.run else None,
                "stdout": r.run.stdout if r.run else "",
                "stderr": r.run.stderr if r.run else "",
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
            }
            return self._send(200, payload)
        if path == "/teach":
            phrase = (data.get("intent_phrase") or "").strip()
            command = (data.get("command") or "").strip()
            if not phrase or not command:
                return self._send(400, {"error": "missing intent_phrase or command"})
            return self._send(200, {"id": teach(phrase, command)})
        return self._send(404, {"error": "not found"})

    def log_message(self, format, *args):  # silence default access log
        return


def main() -> int:
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"lever-runner http api on :{PORT}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
