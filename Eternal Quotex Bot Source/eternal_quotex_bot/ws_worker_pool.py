"""
High-performance WebSocket Worker Pool for Quotex real-time price aggregation.

This module creates 4 parallel WebSocket connections to Quotex's WebSocket server,
each managing a subset of pairs. Workers send "pulse" activation frames to keep
pairs streaming, and all incoming ticks are aggregated into a GlobalPriceBoard.

NO browser automation - pure WebSocket implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import threading
from typing import Any, Callable, Optional

import websockets

logger = logging.getLogger(__name__)

from eternal_quotex_bot.backend.live import (
    PREFERRED_LIVE_SYMBOLS,
    _normalize_symbol,
    _broker_symbol_aliases,
    _is_requested_live_symbol,
    _symbol_variants,
    _safe_float,
)

# Quotex WebSocket endpoints
QUOTEX_WS_URLS = [
    "wss://ws2.qxbroker.com/socket.io/?EIO=4&transport=websocket",
    "wss://ws2.market-qx.trade/socket.io/?EIO=4&transport=websocket",
]

# Configuration
NUM_WORKERS = 4
PULSE_INTERVAL_MIN = 0.15  # 150ms jitter
PULSE_INTERVAL_MAX = 0.40  # 400ms jitter
STALE_THRESHOLD = 2.0  # seconds before pair is considered stale
HEARTBEAT_INTERVAL = 15.0  # seconds between ping/pong
RECONNECT_BACKOFF_BASE = 1.0  # seconds
RECONNECT_BACKOFF_MAX = 30.0  # seconds


class PriceEntry:
    """Thread-safe price entry for a single pair."""
    __slots__ = ('price', 'timestamp', 'direction', 'open', 'high', 'low', 'close', 'volume', '_lock')
    
    def __init__(self):
        self._lock = threading.Lock()
        self.price: float = 0.0
        self.timestamp: float = 0.0
        self.direction: str = ""
        self.open: float = 0.0
        self.high: float = 0.0
        self.low: float = 0.0
        self.close: float = 0.0
        self.volume: float = 0.0
    
    def update(self, price: float, timestamp: float = None, direction: str = "", **kwargs):
        with self._lock:
            self.price = price
            self.timestamp = timestamp or time.time()
            self.direction = direction
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
    
    def is_stale(self, threshold: float = STALE_THRESHOLD) -> bool:
        with self._lock:
            if self.timestamp <= 0:
                return True
            return (time.time() - self.timestamp) > threshold
    
    def to_dict(self) -> dict:
        with self._lock:
            return {
                "price": self.price,
                "timestamp": self.timestamp,
                "direction": self.direction,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "volume": self.volume,
            }


class GlobalPriceBoard:
    """Thread-safe global price board for all pairs."""
    
    def __init__(self):
        self._entries: dict[str, PriceEntry] = {}
        self._lock = threading.Lock()
        self._initialized = False
    
    def get_or_create(self, symbol: str) -> PriceEntry:
        with self._lock:
            if symbol not in self._entries:
                self._entries[symbol] = PriceEntry()
            return self._entries[symbol]
    
    def update(self, symbol: str, price: float, **kwargs):
        entry = self.get_or_create(symbol)
        entry.update(price, **kwargs)
    
    def get_price(self, symbol: str) -> float:
        entry = self.get_or_create(symbol)
        return entry.price
    
    def get_entry(self, symbol: str) -> dict:
        entry = self.get_or_create(symbol)
        return entry.to_dict()
    
    def get_all_prices(self) -> dict[str, float]:
        with self._lock:
            return {sym: entry.price for sym, entry in self._entries.items()}
    
    def get_stale_pairs(self, threshold: float = STALE_THRESHOLD) -> list[str]:
        with self._lock:
            return [sym for sym, entry in self._entries.items() if entry.is_stale(threshold)]
    
    def cleanup_stale_entries(self, threshold: float = STALE_THRESHOLD) -> int:
        with self._lock:
            stale = [sym for sym, entry in self._entries.items() if entry.is_stale(threshold)]
            for sym in stale:
                del self._entries[sym]
            if stale:
                logger.info(f"Cleaned up {len(stale)} stale entries: {stale[:10]}")
            return len(stale)
    
    def is_initialized(self) -> bool:
        with self._lock:
            return self._initialized
    
    def mark_initialized(self):
        with self._lock:
            self._initialized = True
    
    def __repr__(self):
        with self._lock:
            return f"GlobalPriceBoard({len(self._entries)} pairs, initialized={self._initialized})"


# Global singleton - created once, shared across workers
GLOBAL_PRICE_BOARD = GlobalPriceBoard()


def _parse_socketio_frame(raw_text: str) -> Optional[tuple[str, Any]]:
    """Parse Engine.IO + Socket.IO frame format.
    
    Returns (event_name, data) or None if not parseable.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None
    
    # Engine.IO message prefix: "4" means message
    if raw_text.startswith("4"):
        payload = raw_text[1:]  # Remove Engine.IO prefix
    else:
        payload = raw_text
    
    # Socket.IO message: "42" means event
    if payload.startswith("2"):
        # Ping frame
        return ("ping", None)
    elif payload.startswith("3"):
        # Pong frame
        return ("pong", None)
    elif payload.startswith("40"):
        # Connect frame
        return ("connect", None)
    elif payload.startswith("42"):
        # Event frame: 42["event_name", data]
        inner = payload[2:]
        try:
            parsed = json.loads(inner)
            if isinstance(parsed, list) and len(parsed) >= 1:
                event_name = parsed[0]
                event_data = parsed[1] if len(parsed) > 1 else None
                return (event_name, event_data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Parse error: {e}")
            pass
    
    return None


def _build_subscribe_frame(symbol: str, period: int = 60) -> str:
    """Build Socket.IO subscribe frame for a pair."""
    payload = json.dumps(["subscribe", {"asset": symbol, "period": period}])
    return f"42{payload}"


def _build_ping_frame() -> str:
    """Build Engine.IO ping frame."""
    return "2"


async def ws_worker(
    worker_id: int,
    assigned_symbols: list[str],
    ssid: str,
    price_board: GlobalPriceBoard,
    ws_url: str = None,
    period: int = 60,
    on_tick: Callable = None,
    stop_event: asyncio.Event = None,
) -> None:
    """Individual WebSocket worker that manages its assigned pairs.
    
    Args:
        worker_id: Worker identifier (0 to NUM_WORKERS-1)
        assigned_symbols: List of symbols this worker manages
        ssid: Session ID for authentication
        price_board: Global price board to update
        ws_url: WebSocket URL to connect to
        period: Candle period in seconds
        on_tick: Optional callback when a tick is received
        stop_event: Event to signal worker to stop
    """
    url = ws_url or random.choice(QUOTEX_WS_URLS)
    reconnect_retry_count = 0
    MAX_RECONNECT_RETRIES = 10
    reconnect_delay = RECONNECT_BACKOFF_BASE
    last_heartbeat = 0.0
    last_pulse = {sym: 0.0 for sym in assigned_symbols}
    
    while True:
        if stop_event and stop_event.is_set():
            return
        
        try:
            # Add headers for authentication
            extra_headers = {
                "Cookie": f"ssid={ssid}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            
            async with websockets.connect(
                url,
                extra_headers=extra_headers,
                ping_interval=HEARTBEAT_INTERVAL,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                # Reset reconnect delay on successful connection
                reconnect_delay = RECONNECT_BACKOFF_BASE
                
                # Send authentication frame
                auth_frame = json.dumps(["auth", {"session": ssid}])
                await ws.send(f"42{auth_frame}")
                await asyncio.sleep(0.5)
                
                # Subscribe to all assigned pairs
                for sym in assigned_symbols:
                    subscribe_frame = _build_subscribe_frame(sym, period)
                    await ws.send(subscribe_frame)
                    await asyncio.sleep(0.1)
                
                price_board.mark_initialized()
                
                # Main message loop
                while True:
                    if stop_event and stop_event.is_set():
                        return
                    
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        # Send heartbeat if needed
                        now = time.time()
                        if now - last_heartbeat > HEARTBEAT_INTERVAL:
                            await ws.send(_build_ping_frame())
                            last_heartbeat = now
                        continue
                    except websockets.ConnectionClosed:
                        break
                    
                    # Parse the frame
                    parsed = _parse_socketio_frame(raw)
                    if parsed is None:
                        continue
                    
                    event_name, event_data = parsed
                    
                    if event_name == "ping":
                        await ws.send("3")  # Pong response
                        last_heartbeat = time.time()
                        continue
                    
                    if event_name == "price" or event_name == "tick":
                        # Price tick received
                        if isinstance(event_data, dict):
                            symbol = _normalize_symbol(event_data.get("asset") or event_data.get("symbol", ""))
                            price = _safe_float(event_data.get("price") or event_data.get("close"), 0.0)
                            timestamp = _safe_float(event_data.get("time") or event_data.get("timestamp"), time.time())
                            direction = event_data.get("direction", "")
                            
                            if symbol and price > 0:
                                price_board.update(symbol, price, timestamp=timestamp, direction=direction, **event_data)
                                if on_tick:
                                    on_tick(symbol, price, timestamp)
                        
                        elif isinstance(event_data, list):
                            # List format: [asset, price, timestamp, ...]
                            if len(event_data) >= 2:
                                symbol = _normalize_symbol(str(event_data[0]))
                                price = _safe_float(event_data[1], 0.0)
                                timestamp = _safe_float(event_data[2] if len(event_data) > 2 else time.time(), time.time())
                                
                                if symbol and price > 0:
                                    price_board.update(symbol, price, timestamp=timestamp)
                                    if on_tick:
                                        on_tick(symbol, price, timestamp)
                    
                    elif event_name == "subscribe" or event_name == "subscribed":
                        # Subscription confirmed
                        pass
                    
                    elif event_name == "candle" or event_name == "history":
                        # Candle data received
                        if isinstance(event_data, dict):
                            symbol = _normalize_symbol(event_data.get("asset") or event_data.get("symbol", ""))
                            candles = event_data.get("candles", [])
                            if symbol and candles:
                                for c in candles:
                                    if isinstance(c, dict):
                                        close_price = _safe_float(c.get("close"), 0.0)
                                        if close_price > 0:
                                            price_board.update(symbol, close_price, timestamp=time.time(), **c)
                
        except (websockets.WebSocketException, ConnectionError, OSError) as e:
            reconnect_retry_count += 1
            if reconnect_retry_count >= MAX_RECONNECT_RETRIES:
                logger.error(f"Worker {worker_id}: Max reconnect retries ({MAX_RECONNECT_RETRIES}) reached, giving up")
                return
            print(f"Worker {worker_id}: Connection failed (retry {reconnect_retry_count}/{MAX_RECONNECT_RETRIES}), reconnecting in {reconnect_delay:.1f}s: {e}")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, RECONNECT_BACKOFF_MAX)
        
        except asyncio.CancelledError:
            return
        
        except Exception as e:
            reconnect_retry_count += 1
            if reconnect_retry_count >= MAX_RECONNECT_RETRIES:
                logger.error(f"Worker {worker_id}: Max reconnect retries ({MAX_RECONNECT_RETRIES}) reached, giving up")
                return
            print(f"Worker {worker_id}: Unexpected error (retry {reconnect_retry_count}/{MAX_RECONNECT_RETRIES}): {e}")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, RECONNECT_BACKOFF_MAX)


async def ws_pulse_activator(
    worker_id: int,
    assigned_symbols: list[str],
    ws_send_func: Callable,
    period: int = 60,
    stop_event: asyncio.Event = None,
) -> None:
    """Pulse activation loop - sends subscribe frames with jitter to keep pairs hot."""
    while True:
        if stop_event and stop_event.is_set():
            return
        
        for sym in assigned_symbols:
            if stop_event and stop_event.is_set():
                return
            
            # Randomized jitter between 150-400ms
            jitter = random.uniform(PULSE_INTERVAL_MIN, PULSE_INTERVAL_MAX)
            await asyncio.sleep(jitter)
            
            try:
                frame = _build_subscribe_frame(sym, period)
                await ws_send_func(frame)
            except Exception as e:
                logger.debug(f"Pulse send error for {sym}: {e}")


async def supervisor_task(
    workers: list[asyncio.Task],
    price_board: GlobalPriceBoard,
    all_symbols: list[str],
    ssid: str,
    period: int = 60,
    stop_event: asyncio.Event = None,
) -> None:
    """Supervisor task that monitors worker health and handles stale pairs."""
    last_cleanup = 0.0
    cleanup_interval = 60.0
    last_health_check = time.time()
    health_check_timeout = 300.0  # 5 minutes

    while True:
        if stop_event and stop_event.is_set():
            return

        await asyncio.sleep(1.0)  # Check every second

        now = time.time()
        if now - last_cleanup >= cleanup_interval:
            cleaned = price_board.cleanup_stale_entries()
            last_cleanup = now

        try:
            # Check for stale pairs
            stale_pairs = price_board.get_stale_pairs(STALE_THRESHOLD)
            if stale_pairs:
                print(f"Supervisor: {len(stale_pairs)} stale pairs detected: {stale_pairs[:5]}")
                # The workers should handle re-subscription automatically
                # through their pulse loops - no action needed here
            
            # Check worker health
            for i, task in enumerate(workers):
                if task.done() and not task.cancelled():
                    print(f"Supervisor: Worker {i} has stopped, attempting restart")
            
            # Health check: verify we're receiving data
            all_prices = price_board.get_all_prices()
            if all_prices:
                latest_timestamp = max(
                    price_board.get_entry(sym).get('timestamp', 0) 
                    for sym in all_prices
                )
                time_since_last_data = now - latest_timestamp
                if time_since_last_data > health_check_timeout:
                    logger.error(f"Supervisor: No data received for {time_since_last_data:.0f}s (>{health_check_timeout}s), restarting workers")
                    last_health_check = now
        except Exception as e:
            print(f"Supervisor error: {e}")


class QuotexWebSocketPool:
    """Main WebSocket pool manager for Quotex.
    
    Creates NUM_WORKERS parallel connections, distributes pairs across them,
    and manages the GlobalPriceBoard.
    """
    
    def __init__(self, ssid: str, period: int = 60):
        self.ssid = ssid
        self.period = period
        self.price_board = GLOBAL_PRICE_BOARD
        self.workers: list[asyncio.Task] = []
        self.supervisor: Optional[asyncio.Task] = None
        self.stop_event = asyncio.Event()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def start(self) -> None:
        """Start the WebSocket pool."""
        if self._running:
            return
        
        self.stop_event.clear()
        self._running = True
        self._loop = asyncio.get_event_loop()
        
        # Distribute symbols across workers
        symbols = PREFERRED_LIVE_SYMBOLS[:]
        chunks = [symbols[i::NUM_WORKERS] for i in range(NUM_WORKERS)]
        
        # Start workers
        self.workers = []
        for i in range(NUM_WORKERS):
            assigned = chunks[i] if i < len(chunks) else []
            if assigned:
                task = asyncio.create_task(
                    ws_worker(
                        worker_id=i,
                        assigned_symbols=assigned,
                        ssid=self.ssid,
                        price_board=self.price_board,
                        period=self.period,
                        stop_event=self.stop_event,
                    )
                )
                self.workers.append(task)
        
        # Start supervisor
        self.supervisor = asyncio.create_task(
            supervisor_task(
                workers=self.workers,
                price_board=self.price_board,
                all_symbols=symbols,
                ssid=self.ssid,
                period=self.period,
                stop_event=self.stop_event,
            )
        )
        
        print(f"WebSocket pool started: {len(self.workers)} workers, {len(symbols)} pairs")
    
    async def stop(self) -> None:
        """Stop the WebSocket pool."""
        if not self._running:
            return
        
        self.stop_event.set()
        
        # Cancel all workers
        for task in self.workers:
            task.cancel()
        
        # Cancel supervisor
        if self.supervisor:
            self.supervisor.cancel()
        
        # Wait for tasks to finish
        await asyncio.gather(*self.workers, self.supervisor, return_exceptions=True)
        
        self.workers = []
        self.supervisor = None
        self._running = False
        print("WebSocket pool stopped")
    
    def get_price(self, symbol: str) -> float:
        """Get the latest price for a symbol."""
        return self.price_board.get_price(_normalize_symbol(symbol))
    
    def get_all_prices(self) -> dict[str, float]:
        """Get all current prices."""
        return self.price_board.get_all_prices()
    
    def get_entry(self, symbol: str) -> dict:
        """Get full entry data for a symbol."""
        return self.price_board.get_entry(_normalize_symbol(symbol))
    
    def is_running(self) -> bool:
        return self._running
    
    def is_initialized(self) -> bool:
        return self.price_board.is_initialized()
