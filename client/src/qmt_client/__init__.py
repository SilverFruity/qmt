"""Python client for the QMT local HTTP/WebSocket trading server."""

from .client import QMTClient
from .config import QMTConfig
from .discovery import DiscoveredService, QMTDiscovery
from .errors import (
    QMTAPIError,
    QMTAuthError,
    QMTCancelRejected,
    QMTDiscoveryError,
    QMTError,
    QMTHTTPError,
    QMTHostError,
    QMTOrderRejected,
    QMTStreamError,
    QMTTransportError,
)
from .stream import QuoteStream

__all__ = [
    "QMTClient",
    "QMTConfig",
    "QuoteStream",
    "QMTDiscovery",
    "DiscoveredService",
    "QMTDiscoveryError",
    "QMTError",
    "QMTHTTPError",
    "QMTAuthError",
    "QMTHostError",
    "QMTAPIError",
    "QMTOrderRejected",
    "QMTCancelRejected",
    "QMTStreamError",
    "QMTTransportError",
]

__version__ = "0.1.0"
