#!/usr/bin/env python3
"""Run the real QMT server.py on macOS/Windows with a FakeQMT backend.

    python3 run_fake_qmt.py --port 18080 --token dev-token
    python3 run_fake_qmt.py --host 0.0.0.0 --port 18080 --token dev-token \
        --allowed-hosts 192.168.1.20:18080

Then point the client at it:

    QMT_AUTH_TOKEN=dev-token QMT_PORT=18080 python3 -c "from qmt_client import QMTClient; print(QMTClient.from_env().health())"
"""

from __future__ import annotations

import argparse
import signal
import time

from fake_qmt.runner import FakeQMTServer


def main():
    parser = argparse.ArgumentParser(description="FakeQMT front-end for the real server.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--token", default="fake-token")
    parser.add_argument("--account-id", default="FAKE0001")
    parser.add_argument("--account-type", default="STOCK")
    parser.add_argument("--server-dir", default=None)
    parser.add_argument("--tick-interval", type=float, default=0.02)
    parser.add_argument("--quote-symbols", default="600000.SH,000001.SZ")
    parser.add_argument("--allowed-hosts", default="",
                        help="allow Host: header values (comma separated) in addition to bind host and loopback")
    parser.add_argument("--discovery", action="store_true",
                        help="enable signed UDP discovery with a secret derived from the token")
    parser.add_argument("--discovery-secret", default="",
                        help="enable signed UDP discovery with this explicit shared secret")
    parser.add_argument("--discovery-port", type=int, default=0,
                        help="discovery UDP port; 0 picks a free port")
    args = parser.parse_args()

    quote_symbols = [item.strip().upper() for item in args.quote_symbols.split(",") if item.strip()]
    allowed_hosts = [item.strip() for item in args.allowed_hosts.split(",") if item.strip()]
    server = FakeQMTServer(
        server_dir=args.server_dir,
        host=args.host,
        port=args.port,
        token=args.token,
        account_id=args.account_id,
        account_type=args.account_type,
        quote_symbols=quote_symbols,
        allowed_hosts=allowed_hosts,
        discovery_secret=args.discovery_secret or None,
        discovery_enabled=args.discovery or None,
        discovery_port=args.discovery_port,
        tick_interval=args.tick_interval,
    )

    stopping = {"flag": False}

    def handle_signal(signum, frame):
        stopping["flag"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    server.start()
    print("FakeQMT server ready at %s (ws %s)" % (server.base_url, server.ws_url))
    print('auth token: %s' % server.token)
    if server.discovery_port:
        source = 'explicit' if server.discovery_secret else 'derived-from-token'
        print('discovery: udp/%s secret=%s' % (server.discovery_port, source))
    print('try: curl -s -H "Authorization: Bearer %s" %s/health' % (server.token, server.base_url))
    try:
        while not stopping["flag"]:
            time.sleep(0.2)
    finally:
        server.stop()
        print("FakeQMT server stopped")


if __name__ == "__main__":
    main()
