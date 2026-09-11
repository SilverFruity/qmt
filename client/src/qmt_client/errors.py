"""Exception hierarchy raised by :mod:qmt_client."""

from __future__ import annotations


class QMTError(Exception):
    """Base class for every error raised by this package."""


class QMTTransportError(QMTError):
    """The request never produced a usable HTTP response.

    Covers connection refused/reset, timeouts and malformed JSON bodies.
    """

    def __init__(self, message, url=None, original=None):
        super().__init__(message)
        self.url = url
        self.original = original


class QMTHTTPError(QMTError):
    """The server answered with an unexpected HTTP status."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class QMTAuthError(QMTHTTPError):
    """HTTP 401.

    The token is missing or invalid, or the server was started without an
    auth_token configured: the server is fail-closed and rejects everything.
    """


class QMTHostError(QMTHTTPError):
    """HTTP 403 host_not_allowed from the server loopback whitelist."""


class QMTAPIError(QMTError):
    """A JSON body carried an error field.

    The QMT server frequently answers HTTP 200 with a body such as
    {"error": "get_market_data_failed"}; this exception is raised both for
    that case and for non-2xx responses.
    """

    def __init__(self, error, detail=None, payload=None, status_code=200, path=None):
        message = str(error)
        if detail:
            message = "%s: %s" % (error, detail)
        super().__init__(message)
        self.error = error
        self.detail = detail
        self.payload = payload
        self.status_code = status_code
        self.path = path


class QMTOrderRejected(QMTAPIError):
    """The order was refused before (or instead of) being placed.

    The error attribute carries the server-side reason, for example
    invalid_symbol, account_unavailable, volume_limit_exceeded,
    notional_limit_exceeded or order_rate_limited.
    """


class QMTCancelRejected(QMTAPIError):
    """The cancel request was refused before reaching the counter.

    The error attribute carries the server-side reason, for example
    order_id_required, account_unavailable, cancel_unavailable or
    cancel_rate_limited.
    """


class QMTStreamError(QMTError):
    """The websocket stream could not be established or maintained."""


class QMTDiscoveryError(QMTError):
    """Signed LAN discovery returned no usable server."""
