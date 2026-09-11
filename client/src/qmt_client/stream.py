"""WebSocket quote stream for the QMT server.

The server drops any client that has been idle for CLIENT_TIMEOUT_SECONDS
(5 seconds) and never sends protocol pings itself, so the client has to send
traffic to stay connected. This module sends a small heartbeat frame whenever
recv() times out, and reconnects with exponential backoff when the socket
drops (server restart, auth change, network blip).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Iterator, Optional

import websocket

from .errors import QMTStreamError

LOG = logging.getLogger(__name__)

# Must stay comfortably below the server CLIENT_TIMEOUT_SECONDS (5s).
DEFAULT_PING_INTERVAL = 2.0
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 30.0
DEFAULT_HEARTBEAT = '{"type": "heartbeat"}'


class QuoteStream:
    """Subscribe to the server /ws quote_snapshot push channel.

    Two usage styles are supported:

    * iterator:  for message in stream.iter_messages(): ...
    * callback:  stream.start(on_snapshot=handle); ...; stream.stop()

    The callback style runs in a daemon thread and reconnects automatically.
    """

    def __init__(
        self,
        client,
        reconnect=True,
        ping_interval=DEFAULT_PING_INTERVAL,
        connect_timeout=None,
        reconnect_delay=DEFAULT_RECONNECT_DELAY,
        max_reconnect_delay=DEFAULT_MAX_RECONNECT_DELAY,
        max_reconnects=None,
        heartbeat=DEFAULT_HEARTBEAT,
        extra_headers=None,
    ):
        self._client = client
        self.reconnect = bool(reconnect)
        self.ping_interval = float(ping_interval)
        self.connect_timeout = float(connect_timeout if connect_timeout is not None else client.timeout)
        self.reconnect_delay = float(reconnect_delay)
        self.max_reconnect_delay = float(max_reconnect_delay)
        self.max_reconnects = max_reconnects
        self.heartbeat = heartbeat
        self.extra_headers = list(extra_headers or [])
        self._ws = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @property
    def url(self):
        return self._client.ws_url

    def _open(self):
        ws = websocket.create_connection(
            self._client.ws_url,
            timeout=self.connect_timeout,
            header=self._client.websocket_headers() + self.extra_headers,
            suppress_origin=True,
        )
        ws.settimeout(self.ping_interval)
        with self._lock:
            self._ws = ws
        return ws

    def _release(self, ws):
        with self._lock:
            if self._ws is ws:
                self._ws = None
        try:
            ws.close()
        except Exception:
            pass

    def iter_messages(self, max_reconnects=None):
        """Yield decoded JSON messages until stopped or reconnects are exhausted."""
        limit = self.max_reconnects if max_reconnects is None else max_reconnects
        reconnects = 0
        delay = self.reconnect_delay
        while not self._stop.is_set():
            try:
                ws = self._open()
            except Exception as exc:
                if not self.reconnect or (limit is not None and reconnects >= limit):
                    raise QMTStreamError("websocket connect failed: %s" % exc) from exc
                reconnects += 1
                LOG.warning("websocket connect failed, retrying in %.1fs: %s", delay, exc)
                self._stop.wait(delay)
                delay = min(delay * 2, self.max_reconnect_delay)
                continue
            delay = self.reconnect_delay
            try:
                while True:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        try:
                            ws.send(self.heartbeat)
                        except Exception:
                            break
                        continue
                    if not raw:
                        break
                    try:
                        yield json.loads(raw)
                    except (TypeError, ValueError):
                        LOG.warning("ignoring non-JSON websocket frame: %r", raw)
            except websocket.WebSocketException as exc:
                LOG.debug("websocket closed: %s", exc)
            finally:
                self._release(ws)
            if not self.reconnect or self._stop.is_set():
                return
            if limit is not None and reconnects >= limit:
                return
            reconnects += 1
            self._stop.wait(delay)
            delay = min(delay * 2, self.max_reconnect_delay)

    def iter_quotes(self, max_reconnects=None):
        """Yield only quote_snapshot messages."""
        for message in self.iter_messages(max_reconnects=max_reconnects):
            if isinstance(message, dict) and message.get("type") == "quote_snapshot":
                yield message

    def start(self, on_message=None, on_snapshot=None, on_error=None, on_close=None):
        """Run the stream in a background daemon thread; returns self."""
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            kwargs={
                "on_message": on_message,
                "on_snapshot": on_snapshot,
                "on_error": on_error,
                "on_close": on_close,
            },
            name="qmt-quote-stream",
            daemon=True,
        )
        self._thread.start()
        return self

    def _run(self, on_message, on_snapshot, on_error, on_close):
        try:
            for message in self.iter_messages():
                if self._stop.is_set():
                    break
                if on_message is not None:
                    on_message(message)
                if on_snapshot is not None and isinstance(message, dict) and message.get("type") == "quote_snapshot":
                    on_snapshot(message)
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            else:
                LOG.exception("quote stream failed: %s", exc)
        finally:
            if on_close is not None:
                on_close()

    def stop(self, timeout=5.0):
        """Signal the background thread to stop and wait for it."""
        self._stop.set()
        with self._lock:
            ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        return None
