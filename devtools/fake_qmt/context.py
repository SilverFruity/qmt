"""Fake ContextInfo: the QMT strategy-side API the server actually calls."""

from __future__ import annotations

import datetime
import itertools


class FakeContextInfo:
    def __init__(self, store):
        self.store = store
        self.accid = store.account_id
        self.account_type = store.account_type
        self.dividend_type = "front_ratio"
        self.period = "1d"
        self.barpos = 0
        self._sub_seq = itertools.count(1)
        self._tick_seq = itertools.count(1)
        self._prices = {}
        self.subscriptions = {}
        self.timers = []

    # -- account / timer ----------------------------------------------
    def set_account(self, account_id, account_type="STOCK"):
        self.accid = account_id
        self.account_type = account_type
        return True

    def run_time(self, func_name, period, start_time="", market=""):
        self.timers.append({
            "func": func_name,
            "period": period,
            "start": start_time,
            "market": market,
        })
        return True

    # -- quote subscription -------------------------------------------
    def subscribe_quote(self, stock_code, period="tick", dividend_type="none", callback=None, *args, **kwargs):
        sub_id = next(self._sub_seq)
        self.subscriptions[sub_id] = {
            "stock_code": stock_code,
            "period": period,
            "dividend_type": dividend_type,
            "callback": callback,
        }
        return sub_id

    def unsubscribe_quote(self, sub_id):
        return self.subscriptions.pop(sub_id, None) is not None

    def emit_quotes(self):
        for subscription in list(self.subscriptions.values()):
            callback = subscription.get("callback")
            if callback is None:
                continue
            try:
                callback(self.build_quote(subscription["stock_code"]))
            except Exception:
                continue

    def _base_price(self, symbol):
        if symbol not in self._prices:
            seed = sum(ord(char) for char in symbol)
            self._prices[symbol] = round(5 + (seed % 400) / 10.0, 2)
        return self._prices[symbol]

    def build_quote(self, symbol):
        sequence = next(self._tick_seq)
        base = self._base_price(symbol)
        last = round(base + ((sequence % 20) - 10) / 100.0, 2)
        volume = 1000 * (sequence % 50 + 1)
        return {
            "stock_code": symbol,
            "lastPrice": last,
            "lastClose": base,
            "open": base,
            "high": round(last + 0.05, 2),
            "low": round(last - 0.05, 2),
            "volume": volume,
            "amount": round(last * volume, 2),
            "askPrice": [round(last + 0.01, 2)] * 5,
            "bidPrice": [round(last - 0.01, 2)] * 5,
        }

    # -- market data ---------------------------------------------------
    def _bar_count(self, count):
        if isinstance(count, int) and count > 0:
            return min(count, 240)
        return 60

    def _symbol_bars(self, symbol, fields, period, count):
        base = self._base_price(symbol)
        start = datetime.date(2024, 1, 1)
        data = {field: {} for field in fields}
        for index in range(count):
            if period in ("1d", "1w", "1mon"):
                key = (start + datetime.timedelta(days=index)).strftime("%Y%m%d")
            else:
                key = (start + datetime.timedelta(days=index)).strftime("%Y%m%d") + "0930%02d" % (index % 60)
            close = round(base + ((index % 30) - 15) / 100.0, 2)
            open_price = round(close - 0.02, 2)
            high = round(max(open_price, close) + 0.03, 2)
            low = round(min(open_price, close) - 0.03, 2)
            volume = 10000 + index * 100
            values = {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": round(close * volume, 2),
            }
            for field in fields:
                if field in values:
                    data[field][key] = values[field]
        return data

    def get_market_data(self, fields, stock_code=None, period="1d", dividend_type="none",
                        count=-1, start_time=None, end_time=None, **kwargs):
        if isinstance(stock_code, str):
            symbols = [stock_code]
        else:
            symbols = list(stock_code or [])
        if not symbols:
            symbols = ["000300.SH"]
        bars = self._bar_count(count)
        result = {}
        for symbol in symbols:
            result[symbol] = self._symbol_bars(symbol, fields, period, bars)
        if len(symbols) == 1:
            return result[symbols[0]]
        return result

    def get_divid_factors(self, symbol):
        return {"20240102": 1.0, "20240612": 1.05}

    def get_instrumentdetail(self, symbol):
        return self.get_instrument_detail(symbol)

    def get_instrument_detail(self, symbol):
        base = self._base_price(symbol)
        return {
            "symbol": symbol,
            "InstrumentName": "Fake %s" % symbol,
            "UpStopPrice": round(base * 1.1, 2),
            "DownStopPrice": round(base * 0.9, 2),
            "InstrumentStatus": 0,
            "IsTrading": 1,
            "TotalVolumn": 1000000000.0,
            "FloatVolumn": 800000000.0,
            "OpenDate": "20000101",
            "ExpireDate": "20301231",
            "PreClose": base,
        }

    def get_turnover_rate(self, symbols, start="", end=""):
        if isinstance(symbols, str):
            symbols = [symbols]
        return {
            symbol: {"20240102": 1.23, "20240103": 1.31}
            for symbol in symbols
        }

    def get_total_share(self, symbol):
        return float(1000000000 + sum(ord(char) for char in symbol) * 1000)

    def get_trading_dates(self, symbol, start="", end="", count=1, period="1d"):
        total = max(1, int(count or 1))
        start_date = datetime.date(2024, 1, 2)
        return [
            (start_date + datetime.timedelta(days=index)).strftime("%Y%m%d")
            for index in range(total)
        ]

    def get_stock_list_in_sector(self, name, *args, **kwargs):
        return ["600000.SH", "000001.SZ", "600519.SH"]

    def get_weight_in_index(self, index_code, symbol):
        return round((sum(ord(char) for char in symbol) % 100) / 100.0, 4)

    def get_option_list(self, underlying, date, option_type="", *args, **kwargs):
        return [
            {"symbol": "10000001.SH"},
            {"symbol": "10000002.SH"},
        ]

    def get_option_detail_data(self, symbol):
        return {
            "OptExercisePrice": 3.5,
            "ExpireDate": "20240626",
            "PreClose": 0.0520,
            "SettlementPrice": 0.0500,
            "PriceTick": 0.0001,
            "VolumeMultiple": 10000,
            "OptUndlCode": "510050",
            "OptUndlMarket": "SH",
        }

    def get_option_iv(self, symbol):
        return 0.2135

    def get_longhubang(self, symbols, start_time, end_time):
        return [{
            "reason": "fake",
            "close": 10.5,
            "spreadRate": 0.05,
            "TurnoverVolune": 123456,
            "Turnover_Amount": 1234567.0,
            "buyTraderBooth": [{"traderName": "fake-buy"}],
            "sellTraderBooth": [{"traderName": "fake-sell"}],
        }]
