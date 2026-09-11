"""LAN-oriented tests: configurable bind address and Host allowlist.

Uses the real server.py through FakeQMT, so the server_config.json path is the
same as production.
"""

from __future__ import annotations

import socket

import pytest

from qmt_client import QMTClient, QMTTransportError

from test_e2e_fake_qmt import _load_fake_qmt_server


def _raw_http(port, path, headers):
    host_header = headers.get("Host", "127.0.0.1:%d" % port)
    request = "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n" % (path, host_header)
    for key, value in headers.items():
        if key.lower() == "host":
            continue
        request += "%s: %s\r\n" % (key, value)
    request += "\r\n"
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        sock.sendall(request.encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", "replace")
    finally:
        sock.close()


def _lan_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def test_host_whitelist_rejects_unknown_host():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="lan-token", port=0).start()
    try:
        response = _raw_http(server.port, "/health", {
            "Host": "evil.example",
            "Authorization": "Bearer lan-token",
        })
        assert response.startswith("HTTP/1.1 403")
        assert "host_not_allowed" in response

        response = _raw_http(server.port, "/health", {
            "Host": "127.0.0.1:%d" % server.port,
            "Authorization": "Bearer lan-token",
        })
        assert response.startswith("HTTP/1.1 200")
    finally:
        server.stop()


def test_configured_extra_allowed_host():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="lan-token", port=0, allowed_hosts=["qmt.lan"]).start()
    try:
        response = _raw_http(server.port, "/health", {
            "Host": "qmt.lan",
            "Authorization": "Bearer lan-token",
        })
        assert response.startswith("HTTP/1.1 200")
    finally:
        server.stop()


def test_bind_host_and_port_come_from_config():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="lan-token", port=0).start()
    client = None
    try:
        client = QMTClient(token="lan-token", port=server.port, timeout=5.0)
        health = client.health()
        assert health["bind_host"] == "127.0.0.1"
        assert health["bind_port"] == server.port
        assert health["http_port"] == server.port
        assert health["configured_bind_port"] == server.port
        assert "127.0.0.1:%d" % server.port in health["allowed_hosts"]
    finally:
        if client is not None:
            client.close()
        server.stop()


def test_bind_to_lan_interface():
    ip = _lan_ip()
    if not ip or ip.startswith("127."):
        pytest.skip("no non-loopback IPv4 available")
    FakeQMTServer = _load_fake_qmt_server()
    try:
        server = FakeQMTServer(token="lan-token", host=ip, port=0).start()
    except RuntimeError as exc:
        pytest.skip("cannot bind %s: %s" % (ip, exc))
    client = None
    try:
        client = QMTClient(token="lan-token", host=ip, port=server.port, timeout=5.0)
        health = client.health()
        assert health["bind_host"] == ip
        assert health["bind_port"] == server.port
        assert client.positions()["position_count"] >= 1
    except (OSError, QMTTransportError) as exc:
        pytest.skip("cannot reach %s from this host: %s" % (ip, exc))
    finally:
        if client is not None:
            client.close()
        server.stop()
