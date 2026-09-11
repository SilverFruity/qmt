"""Tests for the synchronous HTTP client."""

from __future__ import annotations

import pytest
import requests

from qmt_client import (
    QMTAPIError,
    QMTAuthError,
    QMTCancelRejected,
    QMTHostError,
    QMTClient,
    QMTTransportError,
)

from fake_server import FakeQMTServer


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FlakySession:
    def __init__(self, failures, response):
        self.failures = failures
        self.calls = 0
        self._response = response

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("simulated connection failure")
        return self._response

    def close(self):
        return None


def candles_bulk_route(query, headers):
    symbols = (query.get("symbols") or [""])[0].split(",")
    symbols = [symbol for symbol in symbols if symbol]
    return 200, {
        "bars_by_symbol": {symbol: [{"time": "20240101"}] for symbol in symbols},
        "errors": [],
        "requested": len(symbols),
        "returned": len(symbols),
    }


def test_token_is_required():
    with pytest.raises(ValueError):
        QMTClient(token="")
    with pytest.raises(ValueError):
        QMTClient(token="   ")


def test_sends_bearer_token_and_loopback_host():
    with FakeQMTServer(token="tok") as server:
        client = QMTClient(token="tok", port=server.port)
        assert client.health() == {"ok": True}
        request = server.requests[-1]
        assert request["path"] == "/health"
        assert request["headers"]["authorization"] == "Bearer tok"
        assert request["headers"]["host"] == "127.0.0.1:%d" % server.port
        client.close()


def test_x_qmt_token_scheme():
    with FakeQMTServer(token="tok") as server:
        client = QMTClient(token="tok", port=server.port, auth_scheme="X-QMT-Token")
        assert client.health() == {"ok": True}
        assert server.requests[-1]["headers"]["x-qmt-token"] == "tok"
        client.close()


def test_401_raises_auth_error():
    with FakeQMTServer(token="expected") as server:
        client = QMTClient(token="wrong", port=server.port)
        with pytest.raises(QMTAuthError):
            client.health()


def test_403_raises_host_error():
    routes = {"/health": (403, {"error": "host_not_allowed"})}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port)
        with pytest.raises(QMTHostError):
            client.health()


def test_error_inside_http_200_raises_api_error():
    routes = {"/candles": (200, {"error": "get_market_data_failed", "bars": []})}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port)
        with pytest.raises(QMTAPIError) as info:
            client.candles("600000.SH")
        assert info.value.error == "get_market_data_failed"
        assert info.value.path == "/candles"


def test_none_params_dropped_and_symbols_joined():
    with FakeQMTServer(token="tok") as server:
        client = QMTClient(token="tok", port=server.port)
        client.orders(symbol="600000.SH", limit=5)
        query = server.requests[-1]["query"]
        assert query["symbol"] == "600000.SH"
        assert query["limit"] == "5"
        assert "strategy_name" not in query
        client.candles_bulk(["600000.SH", "000001.SZ"], period="1d")
        assert server.requests[-1]["query"]["symbols"] == "600000.SH,000001.SZ"
        client.close()


def test_invalid_symbol_is_rejected_locally():
    client = QMTClient(token="tok")
    with pytest.raises(ValueError):
        client.candles("600000")
    client.close()


def test_bulk_chunking_merges_results():
    routes = {"/candles-bulk": candles_bulk_route}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port, batch_size=2)
        symbols = ["600000.SH", "000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
        result = client.candles_bulk(symbols)
        assert set(result["bars_by_symbol"]) == set(symbols)
        assert result["requested"] == 5
        assert result["returned"] == 5
        calls = [item for item in server.requests if item["path"] == "/candles-bulk"]
        assert len(calls) == 3
        client.close()


def test_transport_errors_are_retried():
    session = _FlakySession(failures=2, response=_Response(200, {"ok": True}))
    client = QMTClient(token="tok", session=session, retries=2, backoff_factor=0)
    assert client.health() == {"ok": True}
    assert session.calls == 3


def test_transport_error_raises_after_retries():
    session = _FlakySession(failures=10, response=_Response(200, {}))
    client = QMTClient(token="tok", session=session, retries=1, backoff_factor=0)
    with pytest.raises(QMTTransportError):
        client.health()
    assert session.calls == 2


def test_order_is_never_retried():
    session = _FlakySession(failures=10, response=_Response(200, {}))
    client = QMTClient(token="tok", session=session, retries=3, backoff_factor=0)
    with pytest.raises(QMTTransportError):
        client.place_order("600000.SH", "BUY", 10.0, 100)
    assert session.calls == 1


def test_order_validation_is_local():
    client = QMTClient(token="tok")
    with pytest.raises(ValueError):
        client.place_order("600000.SH", "HOLD", 10.0, 100)
    with pytest.raises(ValueError):
        client.place_order("600000.SH", "BUY", 0, 100)
    with pytest.raises(ValueError):
        client.place_order("600000.SH", "BUY", 10.0, 0)
    client.close()


def test_order_rejection_uses_guardrail_error():
    routes = {"/order": (400, {"error": "notional_limit_exceeded", "detail": "too big"})}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port)
        from qmt_client import QMTOrderRejected

        with pytest.raises(QMTOrderRejected) as info:
            client.place_order("600000.SH", "BUY", 100.0, 100000)
        assert info.value.error == "notional_limit_exceeded"
        client.close()


def test_cancel_order_sends_order_id():
    with FakeQMTServer(token="tok") as server:
        client = QMTClient(token="tok", port=server.port)
        result = client.cancel_order("12345")
        assert result == {"ok": True}
        request = server.requests[-1]
        assert request["path"] == "/cancel"
        assert request["query"]["order_id"] == "12345"
        client.close()


def test_cancel_validation_is_local():
    client = QMTClient(token="tok")
    with pytest.raises(ValueError):
        client.cancel_order("")
    client.close()


def test_cancel_error_maps_to_cancel_rejected():
    routes = {"/cancel": (400, {"error": "cancel_rate_limited"})}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port)
        with pytest.raises(QMTCancelRejected) as info:
            client.cancel_order("12345")
        assert info.value.error == "cancel_rate_limited"
        client.close()


def test_cancel_is_never_retried_on_transport_error():
    session = _FlakySession(failures=10, response=_Response(200, {}))
    client = QMTClient(token="tok", session=session, retries=3, backoff_factor=0)
    with pytest.raises(QMTTransportError):
        client.cancel_order("12345")
    assert session.calls == 1


def test_can_cancel_order():
    routes = {"/can-cancel": (200, {"order_id": "12345", "can_cancel": True})}
    with FakeQMTServer(token="tok", routes=routes) as server:
        client = QMTClient(token="tok", port=server.port)
        result = client.can_cancel_order("12345")
        assert result["can_cancel"] is True
        assert server.requests[-1]["path"] == "/can-cancel"
        client.close()


def test_order_id_of_prefers_order_sys_id():
    assert QMTClient.order_id_of({"order_sys_id": "A1", "order_id": 7}) == "A1"
    assert QMTClient.order_id_of({"order_id": 7}) == 7
    assert QMTClient.order_id_of(None) is None


def test_from_env(monkeypatch):
    monkeypatch.setenv("QMT_AUTH_TOKEN", "envtok")
    monkeypatch.setenv("QMT_PORT", "12345")
    client = QMTClient.from_env()
    assert client.token == "envtok"
    assert client.base_url == "http://127.0.0.1:12345"
    client.close()


def test_websocket_headers():
    client = QMTClient(token="abc")
    assert client.websocket_headers() == ["Authorization: Bearer abc"]
    client.close()
    client = QMTClient(token="abc", auth_scheme="x-qmt-token")
    assert client.websocket_headers() == ["X-QMT-Token: abc"]
    client.close()
