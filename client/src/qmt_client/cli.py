"""qmt-discover: find QMT servers on the LAN via signed UDP probing.

    qmt-discover --token $QMT_AUTH_TOKEN
    qmt-discover --secret $QMT_DISCOVERY_SECRET --broadcast 192.168.1.255 --json
    qmt-discover --token ... --broadcast auto

The discovery secret may be given explicitly or derived from the token, so a
single auth_token can drive both discovery and API access. Discovery only works
when the server has discovery enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import QMTClient
from .discovery import (
    DEFAULT_BROADCAST,
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_MAX_SKEW_SECONDS,
    QMTDiscovery,
)
from .errors import QMTError

EXIT_OK = 0
EXIT_NONE = 1
EXIT_USAGE = 2


def build_parser():
    parser = argparse.ArgumentParser(
        prog="qmt-discover",
        description="Discover QMT servers on the LAN with a signed UDP probe.",
    )
    parser.add_argument("--secret", default=None,
                        help="discovery shared secret; if omitted it is derived from --token (or QMT_DISCOVERY_SECRET is read first)")
    parser.add_argument("--token", default=None,
                        help="auth token, used to derive the discovery secret and to verify candidates (default: QMT_AUTH_TOKEN)")
    parser.add_argument("--discovery-port", type=int, default=None,
                        help="UDP discovery port (default: QMT_DISCOVERY_PORT or %d)" % DEFAULT_DISCOVERY_PORT)
    parser.add_argument("--broadcast", default=None,
                        help="broadcast address(es), comma separated; 'auto' expands to /24 broadcasts of local addresses (default: %s)" % DEFAULT_BROADCAST)
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="seconds to wait for replies (default: 2)")
    parser.add_argument("--max-skew", type=float, default=None,
                        help="accepted clock skew in seconds (default: %d)" % DEFAULT_MAX_SKEW_SECONDS)
    parser.add_argument("--cache-ttl", type=float, default=0.0,
                        help="reuse a discovery result for this many seconds (default: 0, always probe)")
    parser.add_argument("--first", action="store_true", dest="first_only",
                        help="return as soon as the first server answers")
    parser.add_argument("--http-timeout", type=float, default=5.0,
                        help="HTTP timeout for verification (default: 5)")
    parser.add_argument("--no-verify", action="store_true",
                        help="only list replies, do not call /health")
    parser.add_argument("--account-type", default=None,
                        help="only keep replies advertising this account type, e.g. STOCK")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="print machine-readable JSON")
    return parser


def _verify(candidate, token, timeout):
    record = {
        "host": candidate.host,
        "port": candidate.port,
        "version": candidate.version,
        "account_type": candidate.account_type,
        "advertised_host": candidate.advertised_host,
        "verified": False,
        "account_id": None,
        "status": None,
        "error": None,
    }
    if not token:
        record["error"] = "no token (pass --token or set QMT_AUTH_TOKEN)"
        return record
    client = QMTClient(token=token, host=candidate.host, port=candidate.port, timeout=timeout)
    try:
        health = client.health()
        record["verified"] = True
        record["account_id"] = health.get("account_id")
        record["status"] = health.get("status")
    except QMTError as exc:
        record["error"] = str(exc)
    finally:
        client.close()
    return record


def _print_table(records):
    if not records:
        print("no QMT server answered")
        print("check: server discovery enabled, --broadcast address, UDP firewall")
        return
    print("found %d QMT server(s):" % len(records))
    print("  %-16s %-6s %-4s %-8s %-9s %s" % ("HOST", "PORT", "VER", "ACCOUNT", "VERIFIED", "DETAIL"))
    for record in records:
        detail = record["account_id"] or record["error"] or "-"
        print("  %-16s %-6s %-4s %-8s %-9s %s" % (
            record["host"], record["port"], record["version"], record["account_type"],
            "yes" if record["verified"] else "no", detail,
        ))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    token = args.token if args.token is not None else os.environ.get("QMT_AUTH_TOKEN")
    secret = args.secret if args.secret is not None else os.environ.get("QMT_DISCOVERY_SECRET")
    if not secret and not token:
        parser.error("pass --secret or --token (or set QMT_DISCOVERY_SECRET / QMT_AUTH_TOKEN)")
    port = args.discovery_port
    if port is None:
        port = int(os.environ.get("QMT_DISCOVERY_PORT") or DEFAULT_DISCOVERY_PORT)

    discovery = QMTDiscovery(
        secret=secret,
        token=token,
        port=port,
        broadcast=args.broadcast or DEFAULT_BROADCAST,
        timeout=args.timeout,
        max_skew=args.max_skew if args.max_skew is not None else DEFAULT_MAX_SKEW_SECONDS,
        cache_ttl=args.cache_ttl,
        first_only=args.first_only,
    )
    candidates = discovery.discover()
    if args.account_type:
        wanted = args.account_type.strip().upper()
        candidates = [item for item in candidates if (item.account_type or "").upper() == wanted]

    if args.no_verify:
        records = [{
            "host": item.host,
            "port": item.port,
            "version": item.version,
            "account_type": item.account_type,
            "advertised_host": item.advertised_host,
            "verified": False,
            "account_id": None,
            "status": None,
            "error": None,
        } for item in candidates]
    else:
        records = [_verify(item, token, args.http_timeout) for item in candidates]

    if args.as_json:
        print(json.dumps({"count": len(records), "servers": records}, ensure_ascii=False, indent=2))
    else:
        _print_table(records)

    if not records:
        return EXIT_NONE
    if not args.no_verify and not any(record["verified"] for record in records):
        return EXIT_NONE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
