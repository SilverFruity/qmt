"""Synchronous HTTP client for the QMT local trading server.

The server exposes a JSON API over GET on 127.0.0.1:18080. It authenticates
every request with a bearer token, enforces a loopback Host whitelist, and
frequently answers HTTP 200 with {"error": ...} in the body, so this client
normalises both cases into exceptions.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Union

import requests

from .config import (
    DEFAULT_ENV_PREFIX,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    QMTConfig,
)
from .errors import (
    QMTAPIError,
    QMTAuthError,
    QMTCancelRejected,
    QMTDiscoveryError,
    QMTError,
    QMTHostError,
    QMTOrderRejected,
    QMTTransportError,
)
from .stream import QuoteStream

LOG = logging.getLogger(__name__)

BULK_BATCH_SIZE = 300


class QMTClient:
    """Client for the QMT HTTP/WebSocket server.

    Usage::

        client = QMTClient.from_env()
        positions = client.positions()
        for message in client.quote_stream().iter_quotes():
            ...
    """

    def __init__(
        self,
        token,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        timeout=DEFAULT_TIMEOUT,
        base_url=None,
        session=None,
        retries=2,
        backoff_factor=0.2,
        auth_scheme="Bearer",
        user_agent="qmt-client/0.1.0",
        batch_size=BULK_BATCH_SIZE,
    ):
        token = str(token or "").strip()
        if not token:
            raise ValueError(
                "QMT auth token is required; the server is fail-closed and "
                "rejects every request when auth_token is empty"
            )
        self.token = token
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.backoff_factor = max(0.0, float(backoff_factor))
        self.batch_size = max(1, int(batch_size))
        self._auth_scheme = auth_scheme
        self._base_url = (base_url or ("http://%s:%d" % (host, port))).rstrip("/")
        if self._base_url.startswith("https://"):
            self._ws_url = "wss://" + self._base_url[len("https://"):] + "/ws"
        elif self._base_url.startswith("http://"):
            self._ws_url = "ws://" + self._base_url[len("http://"):] + "/ws"
        else:
            raise ValueError("base_url must start with http:// or https://")
        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None
        headers = {"Accept": "application/json", "User-Agent": user_agent}
        if auth_scheme and str(auth_scheme).lower() == "x-qmt-token":
            headers["X-QMT-Token"] = token
        else:
            headers["Authorization"] = "%s %s" % (auth_scheme or "Bearer", token)
        self._headers = headers

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, prefix=DEFAULT_ENV_PREFIX, **overrides):
        config = QMTConfig.from_env(prefix=prefix, **overrides)
        return cls(
            token=config.token,
            host=config.host,
            port=config.port,
            timeout=config.timeout,
        )

    @classmethod
    def from_config(cls, config, **overrides):
        values = {
            "token": config.token,
            "host": config.host,
            "port": config.port,
            "timeout": config.timeout,
        }
        values.update(overrides)
        return cls(**values)

    @classmethod
    def discover(cls, token=None, secret=None, discovery_port=None, broadcast=None,
                 discovery_timeout=2.0, max_skew=None, cache_ttl=None, first_only=False,
                 **client_kwargs):
        """Find a server via signed UDP discovery and return a ready client.

        The shared discovery secret authenticates the reply; discovery refuses to
        run without it, because a rogue responder could otherwise capture the
        token when the client connects. Candidates are verified with an
        authenticated /health call, trying each in arrival order.
        """
        from .discovery import (
            DEFAULT_CACHE_TTL,
            DEFAULT_DISCOVERY_PORT,
            DEFAULT_MAX_SKEW_SECONDS,
            QMTDiscovery,
        )

        if token is None:
            token = os.environ.get(DEFAULT_ENV_PREFIX + "AUTH_TOKEN")
        if not token:
            raise ValueError("QMT auth token is required to verify a discovered server")
        if secret is None:
            secret = os.environ.get(DEFAULT_ENV_PREFIX + "DISCOVERY_SECRET")
        if discovery_port is None:
            discovery_port = os.environ.get(DEFAULT_ENV_PREFIX + "DISCOVERY_PORT")
        if max_skew is None:
            max_skew = DEFAULT_MAX_SKEW_SECONDS
        if cache_ttl is None:
            cache_ttl = DEFAULT_CACHE_TTL
        discovery = QMTDiscovery(
            secret=secret,
            token=token,
            port=int(discovery_port) if discovery_port else DEFAULT_DISCOVERY_PORT,
            broadcast=broadcast,
            timeout=discovery_timeout,
            max_skew=max_skew,
            cache_ttl=cache_ttl,
            first_only=first_only,
        )
        candidates = discovery.discover()
        failures = []
        for candidate in candidates:
            client = cls(token=token, host=candidate.host, port=candidate.port, **client_kwargs)
            try:
                client.health()
                return client
            except QMTError as exc:
                failures.append("%s:%s %s" % (candidate.host, candidate.port, exc))
                client.close()
        raise QMTDiscoveryError(
            "no reachable QMT server (candidates=%s)" % ("; ".join(failures) if failures else "none")
        )

    # ------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------
    @property
    def base_url(self):
        return self._base_url

    @property
    def ws_url(self):
        return self._ws_url

    def websocket_headers(self):
        if self._auth_scheme and str(self._auth_scheme).lower() == "x-qmt-token":
            return ["X-QMT-Token: %s" % self.token]
        return ["Authorization: Bearer %s" % self.token]

    def close(self):
        if self._owns_session:
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    def _get(self, path, params=None, raw=False, retry=None, error_class=QMTAPIError):
        url = self._base_url + path
        clean = self._clean_params(params)
        attempts = self.retries if retry is None else max(0, int(retry))
        last_error = None
        for attempt in range(attempts + 1):
            try:
                response = self._session.get(
                    url, params=clean, headers=self._headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise QMTTransportError(
                    "GET %s failed: %s" % (path, exc), url=url, original=exc
                ) from exc
            return self._handle_response(response, path, raw, error_class)
        raise QMTTransportError("GET %s failed" % path, url=url, original=last_error)

    def _handle_response(self, response, path, raw, error_class):
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        if status == 401:
            raise QMTAuthError(
                "unauthorized: check the QMT auth token (server is fail-closed)",
                status_code=status,
                payload=body,
            )
        if status == 403:
            raise QMTHostError(
                "host_not_allowed: use http://127.0.0.1:18080 or http://localhost:18080",
                status_code=status,
                payload=body,
            )
        if status >= 400:
            error = body.get("error") if isinstance(body, dict) else None
            detail = body.get("detail") if isinstance(body, dict) else None
            raise error_class(
                error or ("http_%d" % status),
                detail=detail,
                payload=body,
                status_code=status,
                path=path,
            )
        if raw:
            return body
        if isinstance(body, dict) and body.get("error"):
            raise error_class(
                body.get("error"),
                detail=body.get("detail"),
                payload=body,
                status_code=status,
                path=path,
            )
        return body

    def _sleep_backoff(self, attempt):
        delay = self.backoff_factor * (2 ** attempt)
        if delay > 0:
            time.sleep(delay + random.uniform(0, delay))

    @staticmethod
    def _clean_params(params):
        clean = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, (list, tuple, set)):
                value = ",".join(str(item) for item in value)
            clean[key] = value
        return clean

    @staticmethod
    def order_id_of(order):
        """Return the cancel_order() id from an orders()/deals() record.

        QMT calls this the 委托号 and stores it on m_strOrderSysID, which the
        server exposes as order_sys_id.
        """
        if isinstance(order, dict):
            return order.get("order_sys_id") or order.get("order_id")
        return getattr(order, "order_sys_id", None) or getattr(order, "order_id", None)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _symbol(symbol):
        text = str(symbol or "").strip().upper()
        if not text:
            raise ValueError("symbol is required")
        if "." not in text:
            raise ValueError("symbol must look like CODE.MARKET, got %r" % (symbol,))
        return text

    @classmethod
    def _symbols(cls, symbols):
        if symbols is None:
            raise ValueError("at least one symbol is required")
        if isinstance(symbols, str):
            symbols = symbols.split(",")
        result = []
        for symbol in symbols:
            if symbol in (None, ""):
                continue
            normalized = cls._symbol(symbol)
            if normalized not in result:
                result.append(normalized)
        if not result:
            raise ValueError("at least one symbol is required")
        return result

    def _chunks(self, symbols):
        for index in range(0, len(symbols), self.batch_size):
            yield symbols[index:index + self.batch_size]

    def _bulk(self, path, symbols, dict_field, extra_params, error_class=QMTAPIError):
        normalized = self._symbols(symbols)
        parts = []
        for chunk in self._chunks(normalized):
            params = dict(extra_params)
            params["symbols"] = chunk
            parts.append(self._get(path, params, error_class=error_class))
        if len(parts) == 1:
            return parts[0]
        return self._merge_bulk(parts, dict_field)

    @staticmethod
    def _merge_bulk(parts, dict_field):
        merged = dict(parts[0])
        bucket = dict(merged.get(dict_field) or {})
        errors = list(merged.get("errors") or [])
        requested = 0
        for part in parts:
            bucket.update(part.get(dict_field) or {})
            for error in part.get("errors") or []:
                if error not in errors:
                    errors.append(error)
            requested += part.get("requested") or 0
        merged[dict_field] = bucket
        merged["errors"] = errors
        merged["requested"] = requested
        merged["returned"] = len(bucket)
        return merged

    # ------------------------------------------------------------------
    # status / account
    # ------------------------------------------------------------------
    def root(self):
        return self._get("/")

    def health(self):
        return self._get("/health")

    def accounts(self):
        return self._get("/accounts")

    def positions(self):
        return self._get("/positions")

    # ------------------------------------------------------------------
    # quotes
    # ------------------------------------------------------------------
    def quotes(self):
        return self._get("/quotes")

    def quote(self, symbol):
        return self._get("/quote", {"symbol": self._symbol(symbol)})

    def subscribe(self, symbol):
        return self._get("/subscribe", {"symbol": self._symbol(symbol)})

    def unsubscribe(self, symbol):
        return self._get("/unsubscribe", {"symbol": self._symbol(symbol)})

    def quote_stream(self, **kwargs):
        return QuoteStream(self, **kwargs)

    # ------------------------------------------------------------------
    # trading
    # ------------------------------------------------------------------
    def orders(self, symbol=None, strategy_name=None, remark=None, limit=200):
        return self._get("/orders", {
            "symbol": self._symbol(symbol) if symbol else None,
            "strategy_name": strategy_name,
            "remark": remark,
            "limit": limit,
        })

    def deals(self, symbol=None, strategy_name=None, remark=None, limit=200):
        return self._get("/deals", {
            "symbol": self._symbol(symbol) if symbol else None,
            "strategy_name": strategy_name,
            "remark": remark,
            "limit": limit,
        })

    def signals(self, symbol=None):
        return self._get("/signals", {"symbol": self._symbol(symbol) if symbol else None})

    def place_order(self, symbol, side, price, volume, price_type=None, remark="", batch_id=None, source="qmt-client"):
        """Submit a stock order. Never retried (the request is not idempotent).

        Raises QMTOrderRejected for validation/guardrail failures. The returned
        payload contains server debug fields (account_before, quote_before,
        debug_before) and may include account details, so do not log it blindly.
        """
        normalized_side = str(side or "").strip().upper()
        if normalized_side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        normalized_price = float(price)
        normalized_volume = int(volume)
        if normalized_price <= 0:
            raise ValueError("price must be positive")
        if normalized_volume <= 0:
            raise ValueError("volume must be positive")
        if not batch_id:
            batch_id = "qmt-client-%s" % uuid.uuid4().hex
        return self._get("/order", {
            "symbol": self._symbol(symbol),
            "side": normalized_side,
            "price": normalized_price,
            "volume": normalized_volume,
            "price_type": price_type,
            "remark": remark,
            "batch_id": batch_id,
            "source": source,
        }, retry=0, error_class=QMTOrderRejected)

    def cancel_order(self, order_id, account_type=None):
        """Cancel one live order. Never retried.

        order_id is the 委托号 reported by orders()/deals() as order_sys_id
        (QMT m_strOrderSysID); order_id_of(record) extracts it for you.
        Raises QMTCancelRejected on validation/guardrail failures.
        """
        normalized = str(order_id or "").strip()
        if not normalized:
            raise ValueError("order_id is required")
        return self._get("/cancel", {
            "order_id": normalized,
            "account_type": account_type,
        }, retry=0, error_class=QMTCancelRejected)

    def can_cancel_order(self, order_id, account_type=None):
        """Ask whether an order can still be cancelled (GET /can-cancel)."""
        normalized = str(order_id or "").strip()
        if not normalized:
            raise ValueError("order_id is required")
        return self._get("/can-cancel", {
            "order_id": normalized,
            "account_type": account_type,
        }, error_class=QMTCancelRejected)

    # ------------------------------------------------------------------
    # candles / instruments / fundamentals
    # ------------------------------------------------------------------
    def candles(self, symbol, period="1d", count=240, start=None, end=None, dividend_type=None):
        return self._get("/candles", {
            "symbol": self._symbol(symbol),
            "period": period,
            "count": count,
            "start": start,
            "end": end,
            "dividend_type": dividend_type,
        })

    def candles_bulk(self, symbols, period="1d", start=None, end=None, dividend_type="none"):
        return self._bulk("/candles-bulk", symbols, "bars_by_symbol", {
            "period": period,
            "start": start,
            "end": end,
            "dividend_type": dividend_type,
        })

    def instrument(self, symbol):
        return self._get("/instrument", {"symbol": self._symbol(symbol)})

    def instrument_bulk(self, symbols):
        return self._bulk("/instrument-bulk", symbols, "detail_by_symbol", {})

    def divid_factors(self, symbols, start=None, end=None):
        return self._bulk("/divid-factors", symbols, "factors_by_symbol", {
            "start": start,
            "end": end,
        })

    def turnover_rate(self, symbols, start=None, end=None):
        return self._bulk("/turnover-rate", symbols, "rates_by_symbol", {
            "start": start,
            "end": end,
        })

    def total_share(self, symbols):
        return self._bulk("/total-share", symbols, "shares_by_symbol", {})

    def trading_dates(self, symbol, start=None, end=None, count=None, period="1d"):
        return self._get("/trading-dates", {
            "symbol": self._symbol(symbol),
            "start": start,
            "end": end,
            "count": count,
            "period": period,
        })

    def sector(self, name, with_weight=False, index_code=None, realtime=None):
        return self._get("/sector", {
            "name": name,
            "with_weight": with_weight,
            "index_code": index_code,
            "realtime": realtime,
        })

    # ------------------------------------------------------------------
    # options / other
    # ------------------------------------------------------------------
    def options(self, underlying, date, type="", available=None, limit=200, sort="strike_asc"):
        return self._get("/options", {
            "underlying": self._symbol(underlying),
            "date": date,
            "type": type,
            "available": available,
            "limit": limit,
            "sort": sort,
        })

    def option_trade_options(self):
        return self._get("/option-trade-options")

    def longhubang(self, symbol, start=None, end=None):
        return self._get("/longhubang", {
            "symbol": self._symbol(symbol),
            "start": start,
            "end": end,
        })

    def debug_trade(self):
        return self._get("/debug/trade")
