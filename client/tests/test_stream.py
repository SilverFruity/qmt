"""Tests for the WebSocket quote stream."""

from __future__ import annotations

import time

from qmt_client import QMTClient

from fake_ws import FakeWSServer


def test_stream_receives_snapshot():
    def on_connect(connection):
        connection.send_json({"type": "quote_snapshot", "quote_count": 1, "quotes": []})

    server = FakeWSServer(on_connect).start()
    client = QMTClient(token="tok", port=server.port)
    messages = client.quote_stream(reconnect=False).iter_messages()
    try:
        message = next(messages)
        assert message["type"] == "quote_snapshot"
        assert message["quote_count"] == 1
    finally:
        messages.close()
        server.stop()
        client.close()


def test_stream_reconnects_after_server_close():
    state = {"count": 0}

    def on_connect(connection):
        state["count"] += 1
        if state["count"] == 1:
            connection.send_json({"type": "quote_snapshot", "sequence": 1})
            time.sleep(0.05)
            connection.close()
        else:
            connection.send_json({"type": "quote_snapshot", "sequence": 2})
            time.sleep(1.0)

    server = FakeWSServer(on_connect).start()
    client = QMTClient(token="tok", port=server.port)
    stream = client.quote_stream(reconnect_delay=0.1, max_reconnect_delay=0.1)
    messages = stream.iter_quotes()
    try:
        first = next(messages)
        second = next(messages)
        assert first["sequence"] == 1
        assert second["sequence"] == 2
    finally:
        messages.close()
        server.stop()
        client.close()
