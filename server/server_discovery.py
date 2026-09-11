# -*- coding: utf-8 -*-
"""HMAC-authenticated UDP discovery protocol for the QMT server.

Active probing only: the client broadcasts a signed probe, the server verifies
it and answers unicast. Only a holder of the shared secret can produce a valid
probe (so an unauthenticated scanner gets no answer) or a valid response (so a
rogue host cannot lure a client into sending its bearer token elsewhere).
"""

import hashlib
import hmac

SERVICE_NAME = 'qmt'
PROTOCOL_VERSION = 1
DEFAULT_MAX_SKEW_SECONDS = 300
DISCOVERY_KDF_LABEL = b'qmt-discovery-v1'


def derive_secret(token):
    """Derive the discovery secret from the API token (domain separated).

    Lets an operator provision only auth_token: both sides compute
    HMAC-SHA256(auth_token, 'qmt-discovery-v1'), so discovery is still
    HMAC-authenticated without a second shared secret.
    """
    if not token:
        return None
    return hmac.new(str(token).encode('utf-8'), DISCOVERY_KDF_LABEL, hashlib.sha256).hexdigest()


def sign(secret, canonical):
    return hmac.new(secret.encode('utf-8'), canonical.encode('utf-8'), hashlib.sha256).hexdigest()


def probe_canonical(nonce, ts):
    return 'qmt|probe|%s|%s' % (nonce, ts)


def response_canonical(host, http_port, account_type, nonce, ts):
    return 'qmt|response|%s|%s|%s|%s|%s' % (host, http_port, account_type, nonce, ts)


def verify_probe(payload, secret, now, max_skew=DEFAULT_MAX_SKEW_SECONDS):
    """Return {'nonce', 'ts'} for a valid probe, otherwise None."""
    if not isinstance(payload, dict) or payload.get('service') != SERVICE_NAME:
        return None
    if not payload.get('probe'):
        return None
    nonce = str(payload.get('nonce') or '').strip()
    ts = payload.get('ts')
    if not nonce or not isinstance(ts, (int, float)):
        return None
    if abs(now - ts) > max_skew:
        return None
    expected = sign(secret, probe_canonical(nonce, int(ts)))
    provided = str(payload.get('sig') or '')
    if not provided or not hmac.compare_digest(expected, provided):
        return None
    return {'nonce': nonce, 'ts': int(ts)}


def build_response(host, http_port, account_type, nonce, now, secret):
    ts = int(now)
    payload = {
        'service': SERVICE_NAME,
        'version': PROTOCOL_VERSION,
        'host': host or '',
        'http_port': int(http_port),
        'account_type': account_type or '',
        'nonce': nonce,
        'ts': ts,
    }
    payload['sig'] = sign(
        secret,
        response_canonical(payload['host'], payload['http_port'], payload['account_type'], nonce, ts),
    )
    return payload
