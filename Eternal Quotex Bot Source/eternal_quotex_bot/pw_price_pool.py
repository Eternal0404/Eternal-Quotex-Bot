"""
Playwright-based parallel browser price aggregator for Quotex.

Opens 4 parallel browser contexts (tabs), splits all pairs into 4 groups,
and uses JavaScript commands to activate pairs. Each context feeds prices
into a shared GlobalPriceBoard.

This is a FALLBACK mechanism - used when WebSocket pool fails or user selects
"Playwright (Parallel)" as the data source.
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
from typing import Any, Callable, Optional

from eternal_quotex_bot.backend.live import (
    PREFERRED_LIVE_SYMBOLS,
    _normalize_symbol,
    _safe_float,
)

# Configuration
NUM_CONTEXTS = 4
ACTIVATION_INTERVAL = 2.0  # seconds between pair switches
STALE_THRESHOLD = 3.0  # seconds before pair is considered stale


class PlaywrightPriceBoard:
    """Thread-safe global price board shared across all browser contexts."""
    
    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def update(self, symbol: str, price: float, timestamp: float = None, **kwargs):
        with self._lock:
            self._data[symbol] = {
                "price": price,
                "timestamp": timestamp or time.time(),
                **kwargs,
            }
    
    def get_price(self, symbol: str) -> float:
        with self._lock:
            entry = self._data.get(symbol, {})
            return float(entry.get("price", 0.0))
    
    def get_all_prices(self) -> dict[str, float]:
        with self._lock:
            return {sym: entry["price"] for sym, entry in self._data.items()}
    
    def get_stale_pairs(self, threshold: float = STALE_THRESHOLD) -> list[str]:
        with self._lock:
            now = time.time()
            stale = []
            for sym, entry in self._data.items():
                if now - entry.get("timestamp", 0) > threshold:
                    stale.append(sym)
            return stale
    
    def is_updated(self, symbol: str) -> bool:
        with self._lock:
            entry = self._data.get(symbol, {})
            return entry.get("price", 0) > 0
    
    def __repr__(self):
        with self._lock:
            return f"PlaywrightPriceBoard({len(self._data)} pairs)"


# Global singleton
GLOBAL_PRICE_BOARD = PlaywrightPriceBoard()


def _split_pairs_into_groups(symbols: list[str], num_groups: int = NUM_CONTEXTS) -> list[list[str]]:
    """Split symbols into num_groups roughly equal groups."""
    groups = [[] for _ in range(num_groups)]
    for i, sym in enumerate(symbols):
        groups[i % num_groups].append(sym)
    return groups


async def playwright_context_worker(
    context_id: int,
    assigned_symbols: list[str],
    page,  # Playwright page object
    price_board: PlaywrightPriceBoard,
    browser,  # Playwright browser object
    login_url: str = "https://market-qx.trade/en/demo-trade",
    stop_event: asyncio.Event = None,
) -> None:
    """Individual browser context worker that cycles through its assigned pairs."""
    import re
    
    current_symbol = None
    stale_count = {sym: 0 for sym in assigned_symbols}
    
    # Navigate to trading page
    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)  # Wait for page to load
    except Exception as e:
        print(f"Context {context_id}: Failed to load page: {e}")
        return
    
    # Listen for network responses to capture price data
    async def handle_response(response):
        try:
            url = response.url
            if "price" in url.lower() or "candle" in url.lower() or "tick" in url.lower():
                try:
                    data = await response.json()
                    # Parse price data from response
                    if isinstance(data, dict):
                        price = _safe_float(data.get("price") or data.get("close") or data.get("value"), 0.0)
                        symbol = _normalize_symbol(data.get("asset") or data.get("symbol", ""))
                        if symbol and price > 0:
                            price_board.update(symbol, price, **data)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                price = _safe_float(item.get("price") or item.get("close"), 0.0)
                                symbol = _normalize_symbol(item.get("asset") or item.get("symbol", ""))
                                if symbol and price > 0:
                                    price_board.update(symbol, price, **item)
                except Exception:
                    pass
        except Exception:
            pass
    
    page.on("response", handle_response)
    
    # Also listen for WebSocket messages if possible
    try:
        cdp_session = await page.context.new_cdp_session(page)
        await cdp_session.send("Network.enable")
        
        async def handle_ws_message(message):
            try:
                if message.get("method") == "Network.webSocketFrameReceived":
                    payload = message.get("params", {}).get("response", {}).get("payloadData", "")
                    if payload and isinstance(payload, str):
                        # Try to parse Socket.IO messages
                        if "42" in payload:
                            try:
                                # Extract JSON part
                                json_start = payload.find("[")
                                if json_start >= 0:
                                    data = json.loads(payload[json_start:])
                                    if isinstance(data, list) and len(data) >= 2:
                                        event = data[0]
                                        event_data = data[1]
                                        if event in ("price", "tick", "candle") and isinstance(event_data, dict):
                                            symbol = _normalize_symbol(event_data.get("asset") or event_data.get("symbol", ""))
                                            price = _safe_float(event_data.get("price") or event_data.get("close"), 0.0)
                                            if symbol and price > 0:
                                                price_board.update(symbol, price)
                            except (json.JSONDecodeError, ValueError):
                                pass
            except Exception:
                pass
        
        await cdp_session.on("Network.webSocketFrameReceived", handle_ws_message)
    except Exception:
        pass  # CDP not available, fall back to response listening
    
    # Main activation loop
    while True:
        if stop_event and stop_event.is_set():
            break
        
        for symbol in assigned_symbols:
            if stop_event and stop_event.is_set():
                break
            
            # Check if this pair is stale - if so, stay on it
            is_stale = not price_board.is_updated(symbol) or \
                      (time.time() - price_board._data.get(symbol, {}).get("timestamp", 0)) > STALE_THRESHOLD
            
            if is_stale:
                stale_count[symbol] = stale_count.get(symbol, 0) + 1
                # Stay on this pair until we get a price
                for retry in range(5):  # Try up to 5 times
                    try:
                        # Use JavaScript to activate the pair
                        normalized = _normalize_symbol(symbol)
                        # Try different symbol formats
                        for fmt in [normalized, symbol, normalized.replace("_otc", ""), symbol.replace("_otc", "")]:
                            try:
                                await page.evaluate(f"""
                                    (() => {{
                                        try {{
                                            if (window.app && window.app.chart) {{
                                                window.app.chart.setAsset('{fmt}');
                                                return true;
                                            }}
                                            return false;
                                        }} catch(e) {{
                                            return false;
                                        }}
                                    }})()
                                """)
                                await page.wait_for_timeout(500)
                                
                                # Also try to read the current price from the DOM
                                price_text = await page.evaluate("""
                                    (() => {
                                        try {
                                            const priceEl = document.querySelector('[data-testid="current-price"], .price-value, .asset-price, .current-price');
                                            return priceEl ? priceEl.textContent : null;
                                        } catch(e) {
                                            return null;
                                        }
                                    })()
                                """)
                                if price_text:
                                    # Extract price from text
                                    price_match = re.search(r'[\d,]+\.?\d*', str(price_text))
                                    if price_match:
                                        price = float(price_match.group().replace(',', ''))
                                        if price > 0:
                                            price_board.update(symbol, price)
                                            stale_count[symbol] = 0
                                            break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    
                    await page.wait_for_timeout(500)
                
                if stale_count.get(symbol, 0) > 3:
                    print(f"Context {context_id}: {symbol} still stale after {stale_count[symbol]} attempts")
            else:
                # Normal activation
                stale_count[symbol] = 0
                try:
                    normalized = _normalize_symbol(symbol)
                    await page.evaluate(f"""
                        (() => {{
                            try {{
                                if (window.app && window.app.chart) {{
                                    window.app.chart.setAsset('{normalized}');
                                }}
                            }} catch(e) {{}}
                        }})()
                    """)
                except Exception:
                    pass
            
            current_symbol = symbol
            await page.wait_for_timeout(ACTIVATION_INTERVAL * 1000)


class QuotexPlaywrightPool:
    """Playwright-based parallel browser price aggregator."""
    
    def __init__(self, browser, login_url: str = "https://market-qx.trade/en/demo-trade"):
        self.browser = browser
        self.login_url = login_url
        self.price_board = GLOBAL_PRICE_BOARD
        self.contexts = []
        self.pages = []
        self.workers = []
        self._running = False
        self._stop_event = None
    
    async def start(self) -> None:
        """Start the Playwright parallel browser pool."""
        if self._running:
            return
        
        self._running = True
        self._stop_event = asyncio.Event()
        
        symbols = PREFERRED_LIVE_SYMBOLS[:]
        groups = _split_pairs_into_groups(symbols, NUM_CONTEXTS)
        
        print(f"Starting Playwright pool: {NUM_CONTEXTS} contexts, {len(symbols)} pairs")
        print(f"Groups: {[len(g) for g in groups]}")
        
        self.workers = []
        for i, group in enumerate(groups):
            if not group:
                continue
            
            try:
                # Create new browser context (isolated but shares cookies)
                context = await self.browser.new_context()
                page = await context.new_page()
                self.contexts.append(context)
                self.pages.append(page)
                
                task = asyncio.create_task(
                    playwright_context_worker(
                        context_id=i,
                        assigned_symbols=group,
                        page=page,
                        price_board=self.price_board,
                        browser=self.browser,
                        login_url=self.login_url,
                        stop_event=self._stop_event,
                    )
                )
                self.workers.append(task)
            except Exception as e:
                print(f"Failed to create context {i}: {e}")
        
        print(f"Playwright pool started: {len(self.workers)} workers")
    
    async def stop(self) -> None:
        """Stop the Playwright pool."""
        if not self._running:
            return
        
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        
        # Cancel all workers
        for task in self.workers:
            task.cancel()
        
        # Close all contexts
        for context in self.contexts:
            try:
                await context.close()
            except Exception:
                pass
        
        self.workers = []
        self.contexts = []
        self.pages = []
        print("Playwright pool stopped")
    
    def get_price(self, symbol: str) -> float:
        return self.price_board.get_price(symbol)
    
    def get_all_prices(self) -> dict[str, float]:
        return self.price_board.get_all_prices()
    
    def is_running(self) -> bool:
        return self._running
