"""HMAC-authenticated UDP discovery of QMT servers on the LAN.

Active probing: send a signed probe to one or more broadcast addresses, collect
signed unicast replies. Only a holder of the shared secret (explicit, or derived
from the API token) can produce a valid reply, so an impostor cannot lure a
client into handing over its bearer token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field

SERVICE_NAME = "qmt"
PROTOCOL_VERSION = 1
DEFAULT_DISCOVERY_PORT = 18081
DEFAULT_MAX_SKEW_SECONDS = 300
DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_CACHE_TTL = 30.0
AUTO_BROADCAST = "auto"
DISCOVERY_KDF_LABEL = b"qmt-discovery-v1"

_CACHE_LOCK = threading.Lock()
_CACHE = {}


def sign(secret, canonical):
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def probe_canonical(nonce, ts):
    return "qmt|probe|%s|%s" % (nonce, ts)


def response_canonical(host, http_port, account_type, nonce, ts):
    return "qmt|response|%s|%s|%s|%s|%s" % (host, http_port, account_type, nonce, ts)


def derive_secret(token):
    """Derive the discovery secret from the API token (must match the server)."""
    if not token:
        return None
    return hmac.new(str(token).encode("utf-8"), DISCOVERY_KDF_LABEL, hashlib.sha256).hexdigest()


def local_broadcast_candidates():
    """Best-effort broadcast addresses for this host.

    Uses the primary-route address plus any addresses the hostname resolves to,
    then assumes a /24 netmask. That is a heuristic: pass explicit addresses
    (or the real subnet broadcast) when the layout is different.
    """
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    candidates = [DEFAULT_BROADCAST]
    for address in sorted(addresses):
        text = str(address)
        parts = text.split(".")
        if len(parts) != 4 or text.startswith("127."):
            continue
        candidate = "%s.%s.%s.255" % (parts[0], parts[1], parts[2])
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def normalize_broadcast_targets(broadcast):
    """Accept None / a string / a list; expand the special value 'auto'."""
    if broadcast is None:
        return [DEFAULT_BROADCAST]
    if isinstance(broadcast, str):
        items = [item.strip() for item in broadcast.split(",")]
    else:
        items = [str(item).strip() for item in broadcast]
    targets = []
    for item in items:
        if not item:
            continue
        if item.lower() == AUTO_BROADCAST:
            for candidate in local_broadcast_candidates():
                if candidate not in targets:
                    targets.append(candidate)
        elif item not in targets:
            targets.append(item)
    return targets or [DEFAULT_BROADCAST]


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


@dataclass
class DiscoveredService:
    """A signed discovery reply that passed verification."""

    host: str
    port: int
    account_type: str = ""
    version: int = 0
    advertised_host: str = ""
    raw: dict = field(default_factory=dict)


class QMTDiscovery:
    """Probe the LAN for QMT servers signed with a shared discovery secret.

    The secret may be given explicitly or derived from the API token with
    derive_secret(), matching the server's derivation.
    """

    def __init__(self, secret=None, token=None, port=DEFAULT_DISCOVERY_PORT,
                 broadcast=DEFAULT_BROADCAST, timeout=2.0,
                 max_skew=DEFAULT_MAX_SKEW_SECONDS, cache_ttl=DEFAULT_CACHE_TTL,
                 first_only=False):
        resolved = (secret or "").strip()
        if not resolved:
            resolved = derive_secret(token) or ""
        if not resolved:
            raise ValueError(
                "discovery needs a secret or a token; unsigned LAN discovery is not "
                "supported because a rogue responder could capture the bearer token"
            )
        self.secret = resolved
        self.port = int(port)
        self.broadcast = broadcast
        self.targets = normalize_broadcast_targets(broadcast)
        self.timeout = float(timeout)
        self.max_skew = float(max_skew)
        self.cache_ttl = float(cache_ttl)
        self.first_only = bool(first_only)

    def discover(self, force=False):
        """Return verified servers, reusing a recent result unless forced."""
        key = self._cache_key()
        if self.cache_ttl > 0 and not force:
            with _CACHE_LOCK:
                entry = _CACHE.get(key)
            if entry is not None and entry[0] > time.time():
                return list(entry[1])
        results = self._probe()
        if self.cache_ttl > 0:
            with _CACHE_LOCK:
                _CACHE[key] = (time.time() + self.cache_ttl, list(results))
        return results

    def _cache_key(self):
        digest = hashlib.sha256(self.secret.encode("utf-8")).hexdigest()
        return (tuple(self.targets), self.port, digest, self.max_skew, self.first_only)

    def _probe(self):
        nonce = secrets.token_hex(16)
        ts = int(time.time())
        probe = {"service": SERVICE_NAME, "probe": 1, "nonce": nonce, "ts": ts}
        probe["sig"] = sign(self.secret, probe_canonical(nonce, ts))
        payload = json.dumps(probe, ensure_ascii=False).encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(self.timeout)
            for target in self.targets:
                try:
                    sock.sendto(payload, (target, self.port))
                except OSError:
                    continue
            found = {}
            while True:
                try:
                    data, address = sock.recvfrom(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                service = self._verify(data, nonce)
                if service is None:
                    continue
                # The packet source is authoritative; the advertised host may be 0.0.0.0.
                service.host = address[0]
                found[(service.host, service.port)] = service
                if self.first_only:
                    break
            return list(found.values())
        finally:
            sock.close()

    def _verify(self, data, nonce):
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("service") != SERVICE_NAME:
            return None
        if payload.get("nonce") != nonce:
            return None
        ts = payload.get("ts")
        if not isinstance(ts, (int, float)) or abs(time.time() - ts) > self.max_skew:
            return None
        host = str(payload.get("host") or "")
        port = payload.get("http_port")
        account_type = str(payload.get("account_type") or "")
        if not isinstance(port, int) or port <= 0:
            return None
        expected = sign(self.secret, response_canonical(host, port, account_type, nonce, int(ts)))
        provided = str(payload.get("sig") or "")
        if not provided or not hmac.compare_digest(expected, provided):
            return None
        return DiscoveredService(
            host="",
            port=port,
            account_type=account_type,
            version=int(payload.get("version") or 0),
            advertised_host=host,
            raw=payload,
        )
