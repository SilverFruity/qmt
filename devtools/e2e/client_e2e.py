"""Client half of the cross-endpoint LAN E2E (runs inside a Docker container).

Driven by devtools/e2e/docker_lan_e2e.py; reads its target from QMT_E2E_* env
vars and exits 0 only if every check passes.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request

from qmt_client import QMTClient, QMTDiscovery

SERVER_IP = os.environ.get("QMT_E2E_SERVER_IP", "172.30.0.3")
PORT = int(os.environ.get("QMT_E2E_PORT", "18080"))
DISCOVERY_PORT = int(os.environ.get("QMT_E2E_DISCOVERY_PORT", "18081"))
TOKEN = os.environ.get("QMT_E2E_TOKEN", "lan-token")

results = {}


def check(name, ok):
    results[name] = bool(ok)
    print("%-44s %s" % (name, "PASS" if ok else "FAIL"), flush=True)


client = QMTClient(token=TOKEN, host=SERVER_IP, port=PORT, timeout=8.0)
try:
    health = client.health()
    check("tcp health over the network", health.get("status") == "ok")
    check("account from config", health.get("account_id") == "FAKE0001")
    check("positions", client.positions()["position_count"] >= 1)
    check("place_order", client.place_order("600000.SH", "BUY", 10.5, 100, batch_id="e2e")["status"] == "submitted")
    order_id = QMTClient.order_id_of(client.orders(symbol="600000.SH")["orders"][-1])
    check("can_cancel_order", client.can_cancel_order(order_id)["can_cancel"] is True)
    check("cancel_order", client.cancel_order(order_id)["signaled"] is True)
    check("candles", len(client.candles("600000.SH", count=5)["bars"]) == 5)

    quote = None
    for _ in range(50):
        quote = client.quote("600000.SH")
        if quote.get("has_data"):
            break
        time.sleep(0.1)
    check("quote has_data", bool(quote and quote.get("has_data")))

    messages = client.quote_stream(reconnect=False, ping_interval=0.5).iter_messages()
    box = {}

    def read():
        try:
            box["msg"] = next(messages)
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(6)
    check("websocket quote_snapshot", isinstance(box.get("msg"), dict) and box["msg"].get("type") == "quote_snapshot")
    messages.close()

    try:
        with urllib.request.urlopen("http://%s:%d/openapi.json" % (SERVER_IP, PORT), timeout=5) as response:
            check("openapi.json public", response.getcode() == 200)
    except urllib.error.HTTPError as exc:
        check("openapi.json public", exc.code == 200)
    try:
        urllib.request.urlopen("http://%s:%d/health" % (SERVER_IP, PORT), timeout=5)
        check("401 without token", False)
    except urllib.error.HTTPError as exc:
        check("401 without token", exc.code == 401)
finally:
    client.close()

for target in (SERVER_IP, ".".join(SERVER_IP.split(".")[:3]) + ".255", "255.255.255.255"):
    discovery = QMTDiscovery(token=TOKEN, port=DISCOVERY_PORT, broadcast=target, timeout=2.0, cache_ttl=0)
    found = discovery.discover()
    check("discovery via %s" % target, any(item.host == SERVER_IP for item in found))

passed = sum(1 for value in results.values() if value)
print("ALL_PASS = %s (%d/%d)" % (all(results.values()), passed, len(results)))
raise SystemExit(0 if all(results.values()) else 1)
