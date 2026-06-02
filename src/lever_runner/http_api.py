"""
http_api.py — minimal JSON HTTP API.

    POST /run   {"request": "check disk usage", "chat_id": "..."}
    POST /teach {"intent_phrase": "...", "command": "...", "chat_id": "..."}
    GET  /status?chat_id=...
    GET  /healthz

Security model:
- Binds to 127.0.0.1 by default (loopback only). Set HTTP_BIND=0.0.0.0
  if you really need LAN access; that is almost never the right call.
- If HTTP_API_TOKEN is set, /run and /teach require
  `Authorization: Bearer <token>`. /healthz and /status stay open
  so external monitors can poll them. /run executes pre-approved
  commands; /teach can insert arbitrary shell, so /teach is the
  privileged one and always requires auth when a token is set.
- If HTTP_API_TOKEN is unset and the bind is loopback, the API is
  open (trusted local user). If HTTP_API_TOKEN is unset and the
  bind is non-loopback, the API refuses to start.

chat_id is optional in every request. Defaults to "default" if
unspecified. We use stdlib http.server so we don't pull in a web
framework.
"""

from __future__ import annotations

import json
import os
import sys
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
BIND = os.getenv("HTTP_BIND", "127.0.0.1")
API_TOKEN = os.getenv("HTTP_API_TOKEN", "").strip()
_STARTED_AT = time.time()


def _is_loopback(host: str) -> bool:
    """True if the bind address is loopback (127.0.0.0/8 or ::1)."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    if host.startswith("127."):
        return True
    return False


def _check_token(headers) -> bool:
    """True if the request's Authorization header matches HTTP_API_TOKEN."""
    if not API_TOKEN:
        return True  # no token configured = open
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    return auth.split(" ", 1)[1].strip() == API_TOKEN


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
        # All POST endpoints can mutate state (/teach) or trigger
        # command execution (/run). Require the bearer token if one
        # is configured.
        if not _check_token(self.headers):
            self._send(401, {"error": "missing or invalid bearer token (set HTTP_API_TOKEN)"})
            return
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
    if not _is_loopback(BIND) and not API_TOKEN:
        print(
            f"refusing to start: HTTP_BIND={BIND!r} is non-loopback and HTTP_API_TOKEN is unset. "
            "Anyone who can reach this host could /teach and /run arbitrary commands. "
            "Either set HTTP_BIND=127.0.0.1 (default) or set HTTP_API_TOKEN to a strong secret.",
            file=sys.stderr,
        )
        return 1
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    bind_label = BIND
    auth_label = "auth=off (loopback only)" if _is_loopback(BIND) and not API_TOKEN else (
        f"auth=bearer (token={API_TOKEN[:4]}…{API_TOKEN[-4:]})" if API_TOKEN
        else "auth=off (loopback, no token)"
    )
    print(f"lever-runner http api on {bind_label}:{PORT}  {auth_label}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
