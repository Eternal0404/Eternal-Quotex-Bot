"""Eternal Quotex Bot Backend."""

from .base import TradingBackend
from .live import LiveQuotexBackend, default_live_assets
from .playwright_bridge import PlaywrightQuotexBridge, PlaywrightSession
from .external import default_exness_assets, default_iq_option_assets
from .mock import MockQuotexBackend, default_mock_assets
from .cdm import CDMConnection, CDMBrowser, CDMSession, PriceTick

try:
    from .quotexpy_connection import QuotexPyConnection, PriceData, PREFERRED_PAIRS
except ImportError:
    QuotexPyConnection = None
    PriceData = None
    PREFERRED_PAIRS = []

__all__ = [
    "TradingBackend",
    "LiveQuotexBackend",
    "default_live_assets",
    "PlaywrightQuotexBridge", 
    "PlaywrightSession",
    "default_exness_assets",
    "default_iq_option_assets",
    "MockQuotexBackend",
    "default_mock_assets",
    "CDMConnection",
    "CDMBrowser",
    "CDMSession",
    "PriceTick",
    "QuotexPyConnection",
    "PriceData",
    "PREFERRED_PAIRS",
]