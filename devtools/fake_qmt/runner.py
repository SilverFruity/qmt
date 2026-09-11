"""Load and drive the real server.py with a fake QMT environment."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import traceback

from .context import FakeContextInfo
from .globals import build_qmt_globals
from .store import FakeBrokerStore

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SERVER_DIR = os.path.join(_REPO_ROOT, 'server')
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _free_port(host):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def _free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def _allowed_hosts(host, port, extra):
    values = []
    for name in (host,) + LOCAL_HOSTS:
        if not name:
            continue
        for candidate in ("%s:%d" % (name, port), name):
            text = candidate.strip().lower()
            if text and text not in values:
                values.append(text)
    for item in extra or []:
        text = str(item).strip().lower()
        if text and text not in values:
            values.append(text)
    return values


class FakeQMTServer:
    """Run server.py on this machine as if QMT had loaded it.

    It loads the real server.py, injects fake QMT globals, calls
    init/after_init with a FakeContextInfo, then drives server_tick on a
    background thread. Bind address, port and Host allowlist are passed through
    server_config.json, so the same config path as production is exercised.
    """

    def __init__(self, server_dir=None, server_file="server.py", host="127.0.0.1",
                 port=0, token="fake-token", account_id="FAKE0001",
                 account_type="STOCK", quote_symbols=("600000.SH", "000001.SZ"),
                 allowed_hosts=None, discovery_secret=None, discovery_port=0,
                 discovery_enabled=None, tick_interval=0.02, quote_every=10, config_path=None):
        self.server_dir = os.path.abspath(server_dir or DEFAULT_SERVER_DIR)
        self.server_file = os.path.join(self.server_dir, server_file)
        self.host = host
        self.requested_port = int(port)
        self.port = 0
        self.token = token
        self.account_id = account_id
        self.account_type = account_type
        self.quote_symbols = list(quote_symbols)
        self.allowed_hosts = list(allowed_hosts or [])
        self.discovery_secret = discovery_secret
        self.discovery_enabled = discovery_enabled
        self.requested_discovery_port = int(discovery_port or 0)
        self.discovery_port = 0
        self.tick_interval = float(tick_interval)
        self.quote_every = max(1, int(quote_every))
        self._config_path = config_path
        self._owns_config = config_path is None
        self._module = None
        self._context = None
        self._thread = None
        self._stop = threading.Event()
        self._tick_count = 0
        self.store = None

    @property
    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    @property
    def ws_url(self):
        return "ws://%s:%d/ws" % (self.host, self.port)

    def _write_config(self, bind_port, discovery_port=None):
        payload = {
            "account_id": self.account_id,
            "account_type": self.account_type,
            "auth_token": self.token,
            "bind_host": self.host,
            "bind_port": bind_port,
            "allowed_hosts": _allowed_hosts(self.host, bind_port, self.allowed_hosts),
            "quote_symbols": self.quote_symbols,
            "quote_period": "tick",
            "quote_dividend_type": "none",
        }
        if discovery_port:
            payload["discovery_enabled"] = True
            if self.discovery_secret:
                payload["discovery_secret"] = self.discovery_secret
            payload["discovery_port"] = discovery_port
        if self._config_path is None:
            handle, path = tempfile.mkstemp(prefix="fake_qmt_config_", suffix=".json")
            os.close(handle)
            self._config_path = path
        with open(self._config_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        return self._config_path

    def _load_server(self):
        if not os.path.isfile(self.server_file):
            raise RuntimeError("server.py not found: %s" % self.server_file)
        if self.server_dir not in sys.path:
            sys.path.insert(0, self.server_dir)
        module_name = "fake_qmt_server_%d" % id(self)
        spec = importlib.util.spec_from_file_location(module_name, self.server_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot create loader for %s" % self.server_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        module.__dict__.update(build_qmt_globals(self.store, self._context))
        spec.loader.exec_module(module)
        return module

    def start(self):
        if self._module is not None:
            raise RuntimeError("FakeQMTServer already started")
        bind_port = self.requested_port or _free_port(self.host)
        discovery_port = None
        if self.discovery_secret or self.discovery_enabled:
            discovery_port = self.requested_discovery_port or _free_udp_port()
        self.store = FakeBrokerStore(account_id=self.account_id, account_type=self.account_type)
        self._context = FakeContextInfo(self.store)
        config_path = self._write_config(bind_port, discovery_port)

        module = self._load_server()
        self._module = module
        module.SERVER_CONFIG_FILE = config_path
        module.RUNTIME = module._create_runtime()
        sys.modules[module.RUNTIME_MODULE_NAME] = module.RUNTIME

        module.init(self._context)
        module.after_init(self._context)

        self.port = module.RUNTIME.state.get("http_port") or bind_port
        if module.RUNTIME.state.get("discovery_enabled"):
            self.discovery_port = module.RUNTIME.state.get("discovery_port") or (discovery_port or 0)
        else:
            self.discovery_port = 0
        if not module.RUNTIME.state.get("listener_ready"):
            self.stop()
            raise RuntimeError("FakeQMT listener failed: %s" % module.RUNTIME.state.get("last_error"))

        self._thread = threading.Thread(target=self._loop, name="fake-qmt-ticker", daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            self._tick_count += 1
            try:
                self._module.server_tick(self._context)
                if self._tick_count % self.quote_every == 0:
                    self._context.emit_quotes()
            except Exception:
                traceback.print_exc()
            self._stop.wait(self.tick_interval)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None
        if self._module is not None:
            try:
                self._module.stop(self._context)
            except Exception:
                traceback.print_exc()
            self._module = None
        if self._owns_config and self._config_path and os.path.exists(self._config_path):
            try:
                os.remove(self._config_path)
            except OSError:
                pass
            self._config_path = None
        return None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
