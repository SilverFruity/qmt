"""Unit tests for the discovery protocol: no QMT and no server required."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from qmt_client import QMTDiscovery
from qmt_client.discovery import (
    DEFAULT_BROADCAST,
    DiscoveredService,
    derive_secret,
    normalize_broadcast_targets,
    response_canonical,
    sign,
)


def _response(secret, nonce, host="10.0.0.5", port=18080, account_type="STOCK", ts=None):
    stamp = int(time.time()) if ts is None else int(ts)
    payload = {
        "service": "qmt",
        "version": 1,
        "host": host,
        "http_port": port,
        "account_type": account_type,
        "nonce": nonce,
        "ts": stamp,
    }
    payload["sig"] = sign(secret, response_canonical(host, port, account_type, nonce, stamp))
    return json.dumps(payload).encode("utf-8")


def test_derive_secret_matches_hmac():
    expected = hmac.new(b"tok", b"qmt-discovery-v1", hashlib.sha256).hexdigest()
    assert derive_secret("tok") == expected
    assert derive_secret("") is None


def test_discovery_requires_secret_or_token():
    with pytest.raises(ValueError):
        QMTDiscovery()
    assert QMTDiscovery(token="tok").secret == derive_secret("tok")
    assert QMTDiscovery(secret="explicit").secret == "explicit"


def test_broadcast_targets_normalization():
    assert normalize_broadcast_targets(None) == [DEFAULT_BROADCAST]
    assert normalize_broadcast_targets("a, b") == ["a", "b"]
    assert normalize_broadcast_targets(["a", "a"]) == ["a"]
    assert DEFAULT_BROADCAST in normalize_broadcast_targets("auto")


def test_verify_accepts_valid_and_rejects_tampering():
    secret = derive_secret("tok")
    discovery = QMTDiscovery(secret=secret, cache_ttl=0)
    nonce = "abc123"
    assert discovery._verify(_response(secret, nonce), nonce) is not None
    assert discovery._verify(_response(secret, "other"), nonce) is None
    assert discovery._verify(_response("wrong", nonce), nonce) is None
    assert discovery._verify(_response(secret, nonce, ts=time.time() - 100000), nonce) is None
    assert discovery._verify(b"not json", nonce) is None


def test_cache_avoids_second_probe(monkeypatch):
    calls = {"n": 0}

    def fake_probe(self):
        calls["n"] += 1
        return [DiscoveredService(host="1.2.3.4", port=18080)]

    monkeypatch.setattr(QMTDiscovery, "_probe", fake_probe)
    discovery = QMTDiscovery(secret="s", cache_ttl=60)
    first = discovery.discover()
    second = discovery.discover()
    assert calls["n"] == 1
    assert first[0].host == "1.2.3.4"
    assert second[0].port == 18080
    discovery.discover(force=True)
    assert calls["n"] == 2


def test_cli_requires_secret_or_token(monkeypatch):
    monkeypatch.delenv("QMT_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("QMT_DISCOVERY_SECRET", raising=False)
    from qmt_client.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--no-verify", "--discovery-port", "1"])
    assert exc.value.code == 2
