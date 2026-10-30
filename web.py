#!/usr/bin/env python3
"""Aether Lite in a browser: the same engine and UI as the desktop app, served over HTTP.

Run:  ./run-web.sh                  (http://127.0.0.1:3910)
      .venv/bin/python web.py --host 127.0.0.1 --port 3910

Same data as the desktop app (~/.aether-lite), so sessions, engineers, keys and memory are shared.
The UI's pywebview bridge is replaced by web/bridge.js: API calls become POST /api/<method>, and
the engine's events stream to the page over Server-Sent Events (GET /events).

Engineers can run commands and edit files on this Mac, so the server only listens on loopback
unless AETHER_WEB_TOKEN is set; every API call and the event stream then need that token.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import webview  # noqa: F401  (app.py imports it; the browser mode never opens a window)
except ImportError:
    _stub = types.ModuleType("webview")
    _stub.FOLDER_DIALOG = 20
    sys.modules["webview"] = _stub

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app  # noqa: E402

# Api methods the UI calls (ui.html, ctxmenu.js). Nothing else is reachable over HTTP.
ALLOWED = {
    "add_memory", "approve", "archive_session", "bootstrap", "check_status", "clip_get", "clip_set",
    "delete_engineer", "delete_memory", "delete_session", "delete_ssh", "list_dirs", "list_models",
    "load_session", "new_session", "pick_dir", "rename_session", "save_engineer", "save_ssh", "send",
    "set_auto_memory", "ssh_config_hosts", "stop", "test_ssh", "update_settings",
}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
STATIC = {"/ctxmenu.js": HERE / "ctxmenu.js", "/web/bridge.js": HERE / "web" / "bridge.js"}
MAX_BODY = 2 * 1024 * 1024


class WebApi(app.Api):
    """The desktop engine with its window replaced by a fan-out to every open browser tab."""

    def __init__(self) -> None:
        super().__init__()
        self.clients: set[queue.Queue] = set()
        self.clients_lock = threading.Lock()

    def emit(self, ev: dict) -> None:
        with self.clients_lock:
            for q in list(self.clients):
                q.put(ev)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=10_000)
        with self.clients_lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.clients_lock:
            self.clients.discard(q)

    def pick_dir(self) -> str | None:   # no native folder dialog in a browser; the UI's folder browser still works
        return None


def make_handler(api: WebApi, token: str):
    cache: dict[float, bytes] = {}

    def page() -> bytes:
        """ui.html with the browser bridge loaded first; rebuilt when the file changes."""
        src = HERE / "ui.html"
        mtime = src.stat().st_mtime
        if mtime not in cache:
            html = src.read_text(encoding="utf-8").replace(
                '<script src="ctxmenu.js"></script>',
                '<script src="web/bridge.js"></script><script src="ctxmenu.js"></script>', 1)
            cache.clear()
            cache[mtime] = html.encode("utf-8")
        return cache[mtime]

    class Handler(BaseHTTPRequestHandler):
        server_version = "AetherWeb/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:   # keep the log to errors and startup
            pass

        # ── helpers
        def _send(self, status: int, body: bytes | str | dict, ctype: str = "application/json; charset=utf-8") -> None:
            if isinstance(body, dict):
                body = json.dumps(body)
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            # Blocks DNS rebinding: only IP literals and localhost may be used as the Host.
            raw = self.headers.get("Host") or ""
            host = raw[1:raw.index("]")] if raw.startswith("[") and "]" in raw else raw.rsplit(":", 1)[0]
            return host == "localhost" or bool(re.fullmatch(r"[\d.]+|[0-9a-fA-F:]*:[0-9a-fA-F:]*", host))

        def _token_ok(self, query: dict) -> bool:
            if not token:
                return True
            return self.headers.get("X-Aether-Token") == token or query.get("token", [""])[0] == token

        # ── routes
        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self._send(200, page(), "text/html; charset=utf-8")
            if url.path in STATIC:
                return self._send(200, STATIC[url.path].read_bytes(), "text/javascript; charset=utf-8")
            if url.path == "/healthz":
                return self._send(200, {"ok": True})
            if url.path == "/events":
                if not self._token_ok(parse_qs(url.query)):
                    return self._send(401, {"error": "token required"})
                return self._events()
            return self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            # A custom header forces a CORS preflight, which this server never approves,
            # so other websites cannot call the API from a visitor's browser.
            if self.headers.get("X-Aether-Web") != "1":
                return self._send(403, {"error": "missing header"})
            if not self._token_ok({}):
                return self._send(401, {"error": "token required"})
            name = url.path[len("/api/"):]
            if name not in ALLOWED:
                return self._send(404, {"error": f"unknown method {name}"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                args = body.get("args") or []
                if not isinstance(args, list):
                    raise ValueError("args must be a list")
                result = getattr(api, name)(*args)
                return self._send(200, {"result": result})
            except Exception as exc:  # the engine reports errors as values; anything else is a bug worth showing
                return self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:300]}"})

        def _events(self) -> None:
            q = api.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(b"data: " + json.dumps(ev).encode("utf-8") + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")   # keeps proxies and the browser from timing out
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                api.unsubscribe(q)
                self.close_connection = True

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description="Aether Lite in a browser")
    ap.add_argument("--host", default=os.environ.get("AETHER_WEB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("AETHER_WEB_PORT", "3910")))
    args = ap.parse_args()
    token = os.environ.get("AETHER_WEB_TOKEN", "")
    if args.host not in LOOPBACK and not token:
        print(f"Refusing to listen on {args.host} without AETHER_WEB_TOKEN: engineers can run commands on this Mac.",
              file=sys.stderr)
        return 1

    app.init_db()
    api = WebApi()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(api, token))
    server.daemon_threads = True
    shown = f"[{args.host}]" if ":" in args.host else args.host
    print(f"Aether web on http://{shown}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for sid in list(api.procs):
            api.stop(sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
