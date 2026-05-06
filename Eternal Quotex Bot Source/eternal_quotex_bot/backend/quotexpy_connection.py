"""
QuotexPy Connection Module for Eternal Quotex Bot.

Integrates quotexpy library as an alternative data source for
receiving real-time price data from 15-25+ pairs simultaneously.

Features:
- Single WebSocket connection for all pairs (efficient)
- Sub-100ms polling for real-time updates
- Thread-safe data access for UI
- Supports headless mode
- Automatic session management (bypasses Cloudflare)

Usage:
    from eternal_quotex_bot.backend.quotexpy_connection import QuotexPyConnection
    
    conn = QuotexPyConnection()
    await conn.connect(email, password)
    await conn.subscribe_pairs(PREFERRED_LIVE_SYMBOLS)
    
    # Poll prices in main loop
    prices = conn.get_all_prices()
    
    await conn.close()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# 25 pairs for comprehensive coverage
PREFERRED_PAIRS = [
    "USDBDT_otc", "NZDCAD_otc", "USDEGP_otc", "NZDUSD_otc",
    "USDMXN_otc", "AUDCHF_otc", "USDCOP_otc", "USDINR_otc",
    "USDPKR_otc", "EURNZD_otc", "USDDZD_otc", "USDZAR_otc",
    "USDARS_otc", "CADCHF_otc", "AUDNZD_otc", "USDIDR_otc",
    "EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc", "USDJPY_otc",
    "EURJPY_otc", "GBPJPY_otc", "USDCAD_otc", "USDCHF_otc",
    "EURGBP_otc",
]


@dataclass
class PriceData:
    """Price data for a single pair."""
    symbol: str
    price: float = 0.0
    timestamp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change_pct: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "change_pct": self.change_pct,
        }


class QuotexPyConnection:
    """
    QuotexPy-based connection for real-time multi-pair price data.
    
    Uses quotexpy library which:
    - Uses Playwright browser automation to get session token
    - Bypasses Cloudflare protection
    - Connects to single WebSocket for all pairs
    - Provides real-time price updates via `realtime_price` dict
    
    Architecture:
    - Single WebSocket connection
    - All pair subscriptions share that connection
    - Background polling task fills `self._prices` dict
    - Thread-safe access via lock
    """
    
    def __init__(
        self,
        headless: bool = True,
        debug: bool = False,
        pin_callback: Optional[Callable[[], str]] = None,
    ):
        self.headless = headless
        self.debug = debug
        self.pin_callback = pin_callback
        
        self._client = None
        self._connected = False
        self._running = False
        self._subscribed_pairs: list[str] = []
        
        # Thread-safe price storage
        self._prices: dict[str, PriceData] = {}
        self._lock = threading.RLock()
        
        # Internal tasks
        self._poll_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # For PIN handling
        self._pending_pin: Optional[str] = None
        
    @property
    def is_connected(self) -> bool:
        return self._connected and self._running
    
    async def connect(
        self,
        email: str,
        password: str,
        ssid: Optional[str] = None,
    ) -> bool:
        """
        Connect to Quotex using quotexpy.
        
        Args:
            email: Quotex account email
            password: Quotex account password
            ssid: Optional pre-obtained session ID
            
        Returns:
            True if connected successfully
        """
        if self._connected:
            logger.warning("Already connected")
            return True
            
        try:
            # Import quotexpy
            try:
                from quotexpy import Quotex
                from quotexpy.utils.account_type import AccountType
            except ImportError:
                logger.error("quotexpy not installed. Run: pip install quotexpy>=1.40.7")
                return False
            
            # Create quotexpy client
            self._client = Quotex(
                email=email,
                password=password,
                headless=self.headless,
                on_pin_code=self._get_pin_code,
            )
            
            if self.debug:
                self._client.trace_ws = True
            
            logger.info("Connecting to Quotex via quotexpy...")
            
            # Connect via WebSocket
            connected = await self._client.connect()
            
            if not connected:
                logger.error("WebSocket connection failed")
                return False
            
            # Authenticate
            logger.info("Authenticating...")
            self._client.api.send_ssid(max_attemps=30)
            
            # Wait for auth
            auth_ok = await self._wait_for_auth()
            if not auth_ok:
                logger.error("Authentication failed")
                return False
            
            # Switch to practice account
            try:
                self._client.change_account(AccountType.PRACTICE)
            except Exception as e:
                logger.warning(f"Could not switch to practice account: {e}")
            
            self._connected = True
            self._running = True
            
            # Get instruments list
            await self._load_instruments()
            
            logger.info("Successfully connected to Quotex via quotexpy")
            
            # Start polling task
            self._loop = asyncio.get_event_loop()
            self._poll_task = self._loop.create_task(self._poll_prices())
            
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self._connected = False
            return False
    
    async def _get_pin_code(self) -> str:
        """Handle PIN code request."""
        logger.warning("PIN code required from Quotex")
        
        # Check pending PIN
        if self._pending_pin:
            pin = self._pending_pin
            self._pending_pin = None
            return pin
        
        # Use callback
        if self.pin_callback:
            return self.pin_callback()
        
        # Fallback: wait up to 60 seconds
        for _ in range(60):
            await asyncio.sleep(1)
            if self._pending_pin:
                pin = self._pending_pin
                self._pending_pin = None
                return pin
        
        return ""
    
    def submit_pin(self, pin: str):
        """Submit PIN code (for GUI integration)."""
        self._pending_pin = pin
    
    async def _wait_for_auth(self, timeout: float = 30.0) -> bool:
        """Wait for authentication to complete."""
        start = time.time()
        while time.time() - start < timeout:
            if self._client and self._client.api.account_balance:
                return True
            await asyncio.sleep(0.1)
        return False
    
    async def _load_instruments(self, timeout: float = 30.0) -> bool:
        """Load available instruments."""
        start = time.time()
        while time.time() - start < timeout:
            if self._client and self._client.api.instruments:
                return True
            await asyncio.sleep(0.1)
        return False
    
    async def subscribe_pairs(self, pairs: list[str]) -> bool:
        """
        Subscribe to multiple pairs for real-time data.
        
        Args:
            pairs: List of pair symbols
            
        Returns:
            True if all subscriptions succeeded
        """
        if not self._connected or not self._client:
            logger.error("Not connected")
            return False
            
        if not pairs:
            return True
            
        try:
            # Normalize pairs
            normalized = []
            for pair in pairs:
                pair = pair.strip().upper()
                if "_otc" not in pair:
                    pair = f"{pair}_otc"
                normalized.append(pair)
            
            # Initialize price storage for each pair
            with self._lock:
                for pair in normalized:
                    if pair not in self._prices:
                        self._prices[pair] = PriceData(symbol=pair)
            
            # Subscribe to all pairs via quotexpy
            # Key: quotexpy uses single WebSocket, efficient for many pairs
            for pair in normalized:
                try:
                    self._client.start_candles_stream(pair, 0)
                except Exception as e:
                    logger.warning(f"Error subscribing to {pair}: {e}")
            
            self._subscribed_pairs = normalized
            logger.info(f"Subscribed to {len(normalized)} pairs")
            
            # Brief delay for subscriptions to take effect
            await asyncio.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return False
    
    async def _poll_prices(self):
        """
        Background task: poll prices from quotexpy at 10Hz.
        
        quotexpy stores prices in `api.realtime_price[asset]` as:
        [{"time": timestamp, "price": price}, ...]
        """
        while self._running and self._connected:
            try:
                await asyncio.sleep(0.1)  # 10Hz polling
                
                if not self._client or not self._client.api:
                    continue
                
                # Get real-time data from quotexpy
                realtime = self._client.api.realtime_price
                
                if not realtime:
                    continue
                
                # Update prices for each pair
                with self._lock:
                    for pair in self._subscribed_pairs:
                        try:
                            ticks = realtime.get(pair, [])
                            
                            if ticks and len(ticks) > 0:
                                latest = ticks[-1]
                                price_val = latest.get("price", 0.0)
                                
                                if pair in self._prices and price_val > 0:
                                    self._prices[pair].price = price_val
                                    self._prices[pair].timestamp = latest.get("time", time.time())
                                    
                                    # Calculate OHLC from last 20 ticks
                                    if len(ticks) >= 2:
                                        prices = [t.get("price", 0.0) for t in ticks[-20:] if t.get("price")]
                                        if prices:
                                            self._prices[pair].open = prices[0]
                                            self._prices[pair].high = max(prices)
                                            self._prices[pair].low = min(prices)
                                            
                                            # Calculate change %
                                            if prices[0] > 0:
                                                self._prices[pair].change_pct = (
                                                    (price_val - prices[0]) / prices[0]
                                                ) * 100
                                            
                        except Exception:
                            pass
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.debug:
                    logger.error(f"Poll error: {e}")
                await asyncio.sleep(1)
                
        logger.info("Price polling stopped")
    
    def get_all_prices(self) -> dict[str, dict]:
        """
        Get all current prices (thread-safe).
        
        Returns:
            Dict of {symbol: {price, timestamp, open, high, low, change_pct}}
        """
        with self._lock:
            return {
                pair: data.to_dict()
                for pair, data in self._prices.items()
                if data.price > 0
            }
    
    def get_price(self, pair: str) -> Optional[dict]:
        """Get price for specific pair."""
        with self._lock:
            if pair in self._prices and self._prices[pair].price > 0:
                return self._prices[pair].to_dict()
        return None
    
    def get_pairs_with_data(self) -> list[str]:
        """Get list of pairs that have valid price data."""
        with self._lock:
            return [p for p, d in self._prices.items() if d.price > 0]
    
    def get_instruments(self) -> list[str]:
        """Get available instruments from Quotex."""
        if self._client and self._client.api and self._client.api.instruments:
            return [i[2].replace("\n", "") for i in self._client.api.instruments]
        return []
    
    async def get_candles(
        self,
        pair: str,
        period: int = 60,
        count: int = 100,
    ) -> list[dict]:
        """
        Get historical candles for a pair.
        
        Args:
            pair: Pair symbol
            period: Candle period in seconds (60=1m, 300=5m, etc.)
            count: Number of candles
            
        Returns:
            List of candle dicts
        """
        if not self._connected or not self._client:
            return []
            
        try:
            from quotexpy.utils.candles_period import CandlesPeriod
            
            period_map = {
                60: CandlesPeriod.ONE_MINUTE,
                300: CandlesPeriod.FIVE_MINUTES,
                900: CandlesPeriod.FIFTEEN_MINUTES,
                1800: CandlesPeriod.THIRTY_MINUTES,
                3600: CandlesPeriod.ONE_HOUR,
            }
            
            candles_period = period_map.get(period, CandlesPeriod.ONE_MINUTE)
            
            candles = await self._client.get_candle_v2(pair, candles_period)
            return candles or []
            
        except Exception as e:
            logger.error(f"Error getting candles for {pair}: {e}")
            return []
    
    async def close(self):
        """Close connection and cleanup."""
        logger.info("Closing QuotexPy connection...")
        
        self._running = False
        self._connected = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        if self._client:
            self._client.close()
            
        logger.info("QuotexPy connection closed")
    
    def stop(self):
        """Synchronous stop."""
        self._running = False
        self._connected = False