"""In-memory broker state backing the FakeQMT harness."""

from __future__ import annotations

import itertools
import threading

CANCELABLE_STATUSES = (50, 55)


class FakeBrokerStore:
    """Accounts, positions, orders and deals held in memory.

    Shapes follow the field names QMT exposes (m_strOrderSysID, m_nOrderID,
    m_dOpenPrice, ...) so the real server.py record builders exercise the same
    code paths as on Windows.
    """

    def __init__(self, account_id="FAKE0001", account_type="STOCK", cash=1000000.0):
        self.lock = threading.RLock()
        self.account_id = account_id
        self.account_type = account_type
        self.cash = float(cash)
        self._order_seq = itertools.count(1)
        self._sys_seq = itertools.count(1)
        self._trade_seq = itertools.count(1)
        self.accounts = [{
            "account_id": account_id,
            "account_type": account_type,
            "m_dAvailable": self.cash,
            "m_dStockValue": 0.0,
            "m_dTotalAsset": self.cash,
        }]
        self.positions = {}
        self.orders = {}
        self.deals = {}
        self._seed()

    def _seed(self):
        with self.lock:
            self._add_position("600000.SH", 1000, 9.80)
            self._add_position("000001.SZ", 2000, 11.20)
            self._add_deal("600000.SH", "BUY", 9.80, 1000)
            self._add_deal("600000.SH", "SELL", 10.60, 500)

    def _add_position(self, symbol, volume, open_price):
        self.positions[symbol] = {
            "stock_code": symbol,
            "symbol": symbol,
            "volume": int(volume),
            "can_use_volume": int(volume),
            "open_price": float(open_price),
            "market_value": round(volume * open_price, 2),
            "m_dOpenPrice": float(open_price),
        }

    def _add_deal(self, symbol, side, price, volume):
        trade_id = "DEAL%d" % next(self._trade_seq)
        order_sys_id = "SYS-SEED-%d" % next(self._sys_seq)
        self.deals[trade_id] = {
            "symbol": symbol,
            "side": side,
            "price": float(price),
            "volume": int(volume),
            "trade_date": "20240102",
            "trade_time": "093500",
            "trade_id": trade_id,
            "order_sys_id": order_sys_id,
            "remark": "fake-seed",
            "commission": 5.0,
        }

    def get_trade_detail_data(self, account_id, account_type, datatype):
        with self.lock:
            kind = str(datatype or "").strip().upper()
            if kind == "ACCOUNT":
                return [dict(item) for item in self.accounts]
            if kind == "ORDER":
                return [dict(item) for item in self.orders.values()]
            if kind == "DEAL":
                return [dict(item) for item in self.deals.values()]
            if kind == "POSITION":
                return [dict(item) for item in self.positions.values()]
            return []

    def place_order(self, symbol, side, price, volume, remark=""):
        with self.lock:
            order_id = next(self._order_seq)
            order_sys_id = "SYS%d" % next(self._sys_seq)
            order = {
                "symbol": symbol,
                "side": side,
                "price": float(price),
                "volume": int(volume),
                "traded_volume": 0,
                "order_id": order_id,
                "order_sys_id": order_sys_id,
                "remark": remark or "",
                "status": 50,
                "insert_date": "20240102",
                "insert_time": "100000",
            }
            self.orders[order_sys_id] = order
            return dict(order)

    def cancel_order(self, order_id):
        with self.lock:
            order = self._find_order(order_id)
            if order is None or order["status"] not in CANCELABLE_STATUSES:
                return False
            order["status"] = 54
            return True

    def can_cancel(self, order_id):
        with self.lock:
            order = self._find_order(order_id)
            return bool(order is not None and order["status"] in CANCELABLE_STATUSES)

    def _find_order(self, order_id):
        text = str(order_id or "").strip()
        if text in self.orders:
            return self.orders[text]
        for order in self.orders.values():
            if str(order.get("order_id")) == text or str(order.get("order_sys_id")) == text:
                return order
        return None
