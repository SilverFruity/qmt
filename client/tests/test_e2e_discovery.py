"""Signed LAN discovery tests against the real server.py via FakeQMT."""

from __future__ import annotations

import socket

import pytest

from qmt_client import QMTClient, QMTDiscoveryError

from test_e2e_fake_qmt import _load_fake_qmt_server


def _free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def test_discovery_finds_server_and_returns_client():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="disc-token", port=0, discovery_secret="disc-secret").start()
    client = None
    try:
        client = QMTClient.discover(
            token="disc-token",
            secret="disc-secret",
            discovery_port=server.discovery_port,
            broadcast="127.0.0.1",
            discovery_timeout=2.0,
            cache_ttl=0,
        )
        health = client.health()
        assert health["listener_ready"] is True
        assert health["bind_port"] == server.port
        assert health["discovery_enabled"] is True
        assert health["discovery_ready"] is True
        assert health["discovery_probe_count"] >= 1
        assert client.positions()["position_count"] >= 1
    finally:
        if client is not None:
            client.close()
        server.stop()


def test_discovery_ignores_wrong_secret():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="disc-token", port=0, discovery_secret="disc-secret").start()
    try:
        with pytest.raises(QMTDiscoveryError):
            QMTClient.discover(
                token="disc-token",
                secret="wrong-secret",
                discovery_port=server.discovery_port,
                broadcast="127.0.0.1",
                discovery_timeout=1.0,
                cache_ttl=0,
            )
    finally:
        server.stop()


def test_discovery_with_secret_derived_from_token():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="derive-token", port=0, discovery_enabled=True).start()
    client = None
    try:
        assert server.discovery_port
        client = QMTClient.discover(
            token="derive-token",
            discovery_port=server.discovery_port,
            broadcast="127.0.0.1",
            discovery_timeout=2.0,
            cache_ttl=0,
        )
        health = client.health()
        assert health["discovery_enabled"] is True
        assert health["discovery_secret_source"] == "derived"
    finally:
        if client is not None:
            client.close()
        server.stop()


def test_discovery_disabled_without_secret():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="disc-token", port=0).start()
    try:
        assert server.discovery_port == 0
        with pytest.raises(QMTDiscoveryError):
            QMTClient.discover(
                token="disc-token",
                secret="disc-secret",
                discovery_port=_free_udp_port(),
                broadcast="127.0.0.1",
                discovery_timeout=1.0,
                cache_ttl=0,
            )
    finally:
        server.stop()
