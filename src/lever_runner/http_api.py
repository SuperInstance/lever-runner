"""
http_api.py — minimal JSON HTTP API on :8765.

    POST /run   {"request": "check disk usage", "chat_id": "..."}
    POST /teach {"intent_phrase": "...", "command": "...", "chat_id": "..."}
    GET  /status?chat_id=...

chat_id is optional in every request. Defaults to "default" if
unspecified. We use stdlib http.server so we don't pull in a web
framework.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from .orchestrator import do, status, teach
from .store import LANCEDB_PATH, LANCEDB_TABLE_PREFIX, LEGACY_TABLE
from .__init__ import __version__
import lancedb
import time

load_dotenv()
PORT = int(os.getenv("HTTP_PORT", "8765"))
_STARTED_AT = time.time()


def _chat_id_from(data: dict, qs: dict) -> str:
    """chat_id may come from JSON body or query string. Default = 'default'."""
    cid = data.get("chat_id") or qs.get("chat_id", [None])[0]
    return str(cid) if cid else "default"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/status":
            chat_id = _chat_id_from({}, qs)
            self._send(200, status(chat_id=chat_id))
        elif url.path == "/healthz":
            # Return liveness + a few cheap metrics. We do NOT touch
            # the embedder here (it costs ~1s to load) — just count rows
            # in the per-chat tables.
            try:
                db = lancedb.connect(LANCEDB_PATH)
                tables = sorted(db.list_tables().tables)
                counts = {}
                total = 0
                for t in tables:
                    n = db.open_table(t).count_rows()
                    counts[t] = n
                    total += n
            except Exception as e:
                # DB unreachable counts as unhealthy but we still return
                # the endpoint so the operator can diagnose.
                return self._send(503, {
                    "ok": False,
                    "version": __version__,
                    "uptime_sec": round(time.time() - _STARTED_AT, 1),
                    "error": f"lancedb unavailable: {e}",
                })
            return self._send(200, {
                "ok": True,
                "version": __version__,
                "uptime_sec": round(time.time() - _STARTED_AT, 1),
                "tables": counts,
                "total_commands": total,
                "lancedb_path": LANCEDB_PATH,
            })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length) if length else b""
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as e:
            return self._send(400, {"error": f"bad json: {e}"})

        url = urlparse(self.path)
        qs = parse_qs(url.query)
        path = url.path
        chat_id = _chat_id_from(data, qs)

        if path == "/run":
            request = data.get("request", "").strip()
            if not request:
                return self._send(400, {"error": "missing 'request'"})
            r = do(request, source="http", chat_id=chat_id)
            payload = {
                "ok": r.ok,
                "intent": r.intent,
                "command": r.match.command if r.match else None,
                "exit_code": r.run.exit_code if r.run else None,
                "stdout": r.run.stdout if r.run else "",
                "stderr": r.run.stderr if r.run else "",
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "chat_id": chat_id,
            }
            return self._send(200, payload)
        if path == "/teach":
            phrase = (data.get("intent_phrase") or "").strip()
            command = (data.get("command") or "").strip()
            if not phrase or not command:
                return self._send(400, {"error": "missing intent_phrase or command"})
            return self._send(200, {"id": teach(phrase, command, chat_id=chat_id), "chat_id": chat_id})
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
