"""End-to-end test: real server.py driven by FakeQMT on this machine.

Skipped automatically unless both the server/ and devtools/ directories are
available. Override with QMT_SERVER_DIR / QMT_DEVTOOLS_DIR.
"""

from __future__ import annotations

import functools
import os
import sys
import threading

import pytest

from qmt_client import QMTClient

CLIENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.abspath(os.path.join(CLIENT_ROOT, os.pardir))
DEFAULT_SERVER_DIR = os.path.join(REPO_ROOT, "server")
DEFAULT_DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")


def _load_fake_qmt_server():
    server_dir = os.environ.get("QMT_SERVER_DIR") or DEFAULT_SERVER_DIR
    devtools_dir = os.environ.get("QMT_DEVTOOLS_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(server_dir)), "devtools"
    )
    if not os.path.isfile(os.path.join(server_dir, "server.py")):
        pytest.skip("qmt server.py not found; set QMT_SERVER_DIR to the qmt server directory")
    if not os.path.isdir(os.path.join(devtools_dir, "fake_qmt")):
        pytest.skip("fake_qmt not found; set QMT_DEVTOOLS_DIR to the qmt devtools directory")
    if devtools_dir not in sys.path:
        sys.path.insert(0, devtools_dir)
    from fake_qmt.runner import FakeQMTServer

    return functools.partial(FakeQMTServer, server_dir=server_dir)


def _next_with_timeout(iterator, timeout=5.0):
    result = {}

    def run():
        try:
            result["value"] = next(iterator)
        except BaseException as exc:  # noqa: BLE001 - propagated below
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if "value" in result:
        return result["value"]
    if "error" in result:
        raise result["error"]
    raise AssertionError("timed out waiting for a websocket message")


def test_end_to_end_trading_flow():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="e2e-token", port=0, quote_symbols=["600000.SH"]).start()
    client = None
    try:
        client = QMTClient(token="e2e-token", port=server.port, timeout=5.0)

        health = client.health()
        assert health["listener_ready"] is True
        assert health["auth_enabled"] is True
        assert health["account_id"] == "FAKE0001"
        assert health["account_source"] in ("config", "context_attr")

        positions = client.positions()
        assert positions["position_count"] >= 1

        order = client.place_order("600000.SH", "BUY", 10.5, 100, remark="e2e", batch_id="e2e-1")
        assert order["status"] == "submitted"
        assert order["symbol"] == "600000.SH"
        assert order["side"] == "BUY"

        orders = client.orders(symbol="600000.SH")
        assert orders["order_count"] >= 1
        order_id = QMTClient.order_id_of(orders["orders"][-1])
        assert order_id

        assert client.can_cancel_order(order_id)["can_cancel"] is True
        cancelled = client.cancel_order(order_id)
        assert cancelled["status"] == "cancel_requested"
        assert cancelled["signaled"] is True

        candles = client.candles("600000.SH", period="1d", count=5)
        assert len(candles["bars"]) == 5
        assert candles["bars"][0]["close"] is not None

        signals = client.signals("600000.SH")
        assert signals["point_count"] >= 1
    finally:
        if client is not None:
            client.close()
        server.stop()


def test_end_to_end_quote_stream():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(
        token="e2e-token", port=0, quote_symbols=["600000.SH"], tick_interval=0.01, quote_every=2
    ).start()
    client = None
    messages = None
    try:
        client = QMTClient(token="e2e-token", port=server.port, timeout=5.0)
        messages = client.quote_stream(reconnect=False, ping_interval=0.5).iter_messages()
        message = _next_with_timeout(messages, timeout=5.0)
        assert message["type"] == "quote_snapshot"
        assert "quotes" in message
    finally:
        if messages is not None:
            messages.close()
        if client is not None:
            client.close()
        server.stop()
