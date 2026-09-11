"""Minimal stand-in for the QMT HTTP server used by the client tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeQMTServer:
    def __init__(self, token="secret", routes=None):
        self.token = token
        self.routes = dict(routes or {})
        self.requests = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return None

            def do_GET(self):
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                headers = {key.lower(): value for key, value in self.headers.items()}
                with server._lock:
                    server.requests.append({
                        "path": parsed.path,
                        "query": {key: values[0] for key, values in query.items()},
                        "headers": headers,
                    })
                route = server.routes.get(parsed.path)
                if route is None:
                    status, payload = 200, {"ok": True}
                elif callable(route):
                    status, payload = route(query, headers)
                elif isinstance(route, tuple):
                    status, payload = route
                else:
                    status, payload = 200, route

                provided = ""
                authorization = headers.get("authorization", "")
                if authorization.lower().startswith("bearer "):
                    provided = authorization[7:]
                elif headers.get("x-qmt-token"):
                    provided = headers["x-qmt-token"]
                if provided != server.token:
                    status, payload = 401, {"error": "unauthorized"}

                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
