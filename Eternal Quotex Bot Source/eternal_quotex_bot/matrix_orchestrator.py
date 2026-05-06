"""
MatrixOrchestrator: Async Playwright backend for Multi-Session Matrix.

Manages multiple Quotex browser sessions in parallel, activates assigned pairs
via JavaScript, scrapes live prices, and feeds them into a shared GlobalPriceBoard.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from eternal_quotex_bot.backend.live import (
    PREFERRED_LIVE_SYMBOLS,
    _normalize_symbol,
    _safe_float,
)

# Target pairs to monitor
TARGET_PAIRS = PREFERRED_LIVE_SYMBOLS[:]

# Session storage directory
SESSION_DIR = Path(__file__).parent.parent.parent / "browser_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# Quotex URLs
QUOTEX_LOGIN_URL = "https://qxbroker.com/en/sign-in"
QUOTEX_TRADE_URL = "https://market-qx.trade/en/demo-trade"


@dataclass
class PriceEntry:
    price: float = 0.0
    timestamp: float = 0.0
    direction: str = ""
    source: str = ""  # which worker provided this price


class GlobalPriceBoard:
    """Thread-safe shared price dictionary for all workers."""
    
    def __init__(self):
        self._data: dict[str, PriceEntry] = {}
        self._lock = asyncio.Lock()
    
    async def update(self, symbol: str, price: float, direction: str = "", source: str = ""):
        async with self._lock:
            self._data[symbol] = PriceEntry(
                price=price,
                timestamp=time.time(),
                direction=direction,
                source=source,
            )
    
    async def get_price(self, symbol: str) -> float:
        async with self._lock:
            entry = self._data.get(symbol)
            return entry.price if entry else 0.0
    
    async def get_all_prices(self) -> dict[str, float]:
        async with self._lock:
            return {sym: entry.price for sym, entry in self._data.items() if entry.price > 0}
    
    async def get_stale_pairs(self, threshold: float = 5.0) -> list[str]:
        async with self._lock:
            now = time.time()
            return [
                sym for sym, entry in self._data.items()
                if entry.price > 0 and (now - entry.timestamp) > threshold
            ]
    
    async def is_updated(self, symbol: str, threshold: float = 3.0) -> bool:
        async with self._lock:
            entry = self._data.get(symbol)
            if not entry or entry.price <= 0:
                return False
            return (time.time() - entry.timestamp) <= threshold
    
    async def get_entry(self, symbol: str) -> dict:
        async with self._lock:
            entry = self._data.get(symbol)
            if entry:
                return {
                    "price": entry.price,
                    "timestamp": entry.timestamp,
                    "direction": entry.direction,
                    "source": entry.source,
                }
            return {}


# Global singleton
GLOBAL_PRICE_BOARD = GlobalPriceBoard()


@dataclass
class WorkerContext:
    email: str
    password: str
    browser_context = None
    page = None
    assigned_pairs: list = field(default_factory=list)
    is_running: bool = False
    session_file: Path = None
    pin_callback: Optional[Callable[[str], str]] = None
    
    def __post_init__(self):
        safe_email = self.email.replace("@", "_").replace(".", "_")
        self.session_file = SESSION_DIR / f"session_{safe_email}.json"


class MatrixOrchestrator:
    """Manages multiple Quotex browser sessions in parallel."""
    
    def __init__(self, workers: list[dict], log_callback=None):
        """
        Args:
            workers: List of dicts with 'email' and 'password' keys
            log_callback: Optional callback for logging
        """
        self.workers = [
            WorkerContext(email=w["email"], password=w["password"])
            for w in workers
        ]
        self.playwright = None
        self.browser = None
        self.tasks = []
        self._log = log_callback or (lambda level, msg: None)
        self._stop_event = asyncio.Event()
        self.price_board = GLOBAL_PRICE_BOARD
    
    async def initialize(self):
        """Initialize Playwright and browser using system Chrome installation."""
        try:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            
            # Find system Chrome installation
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            ]
            
            chrome_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    chrome_path = path
                    break
            
            if not chrome_path:
                # Try to find any Chrome installation
                search_paths = glob.glob(r"C:\Program Files\Google\Chrome\Application\*\chrome.exe")
                search_paths.extend(glob.glob(r"C:\Program Files (x86)\Google\Chrome\Application\*\chrome.exe"))
                if search_paths:
                    chrome_path = search_paths[0]
            
            launch_args = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }
            
            if chrome_path:
                launch_args["executable_path"] = chrome_path
                self._log("info", f"Using system Chrome: {chrome_path}")
            else:
                self._log("warn", "System Chrome not found, using Playwright bundled browser")
            
            self.browser = await self.playwright.chromium.launch(**launch_args)
            self._log("info", f"Matrix browser launched: {len(self.workers)} workers ready")
        except Exception as e:
            self._log("error", f"Failed to launch Matrix browser: {e}")
            raise
    
    async def login_worker(self, worker: WorkerContext, pin_callback: Callable[[str], str]) -> bool:
        """Login a single worker, handling PIN if required."""
        try:
            # Check for cached session
            if worker.session_file.exists():
                self._log("info", f"Loading cached session for {worker.email}")
                worker.browser_context = await self.browser.new_context(
                    storage_state=str(worker.session_file)
                )
                worker.page = await worker.browser_context.new_page()
                
                # Navigate to trade page to verify session is valid
                await worker.page.goto(QUOTEX_TRADE_URL, wait_until="domcontentloaded", timeout=30000)
                await worker.page.wait_for_timeout(3000)
                
                # Check if we're actually logged in (not redirected to login)
                current_url = worker.page.url
                if "sign-in" in current_url.lower():
                    self._log("warn", f"Cached session expired for {worker.email}, re-login needed")
                    await worker.browser_context.close()
                    worker.browser_context = None
                    worker.page = None
                    # Fall through to fresh login
                else:
                    self._log("info", f"Cached session valid for {worker.email}")
                    return True
            
            # Fresh login required
            if worker.browser_context is None:
                worker.browser_context = await self.browser.new_context()
                worker.page = await worker.browser_context.new_page()
            
            self._log("info", f"Logging in {worker.email}...")
            await worker.page.goto(QUOTEX_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            
            # Enter email and password
            await worker.page.locator('input[name="email"], input[type="email"]').fill(worker.email)
            await worker.page.locator('input[name="password"], input[type="password"]').fill(worker.password)
            
            # Click login button
            await worker.page.locator('button[type="submit"], .login-button').click()
            
            # Wait for PIN screen or successful login
            try:
                # Wait up to 30 seconds for PIN input to appear
                await worker.page.wait_for_selector('input[name="code"], input[name="pin"], .pin-input', timeout=30000)
                
                # Trigger PIN interceptor
                self._log("info", f"PIN required for {worker.email}")
                pin = pin_callback(worker.email)
                if not pin:
                    self._log("error", f"No PIN provided for {worker.email}")
                    return False
                
                # Fill PIN and submit
                pin_selector = 'input[name="code"], input[name="pin"], .pin-input'
                await worker.page.locator(pin_selector).fill(pin)
                
                # Submit PIN (try multiple possible selectors)
                submit_selectors = [
                    'button[type="submit"]',
                    '.verify-button',
                    '.pin-submit',
                    'button:has-text("Verify")',
                    'button:has-text("Confirm")',
                ]
                submitted = False
                for selector in submit_selectors:
                    try:
                        btn = worker.page.locator(selector)
                        if await btn.count() > 0:
                            await btn.click()
                            submitted = True
                            break
                    except Exception:
                        continue
                
                if not submitted:
                    # Try pressing Enter
                    await worker.page.keyboard.press("Enter")
                
                # Wait for successful navigation
                await worker.page.wait_for_url("**/trade**", timeout=30000)
                
            except Exception as e:
                # Check if we're already on the trade page (maybe no PIN was needed)
                current_url = worker.page.url
                if "trade" in current_url.lower():
                    self._log("info", f"Already logged in for {worker.email}")
                else:
                    self._log("error", f"PIN/login failed for {worker.email}: {e}")
                    return False
            
            # Save session
            await worker.browser_context.storage_state(path=str(worker.session_file))
            self._log("info", f"Session saved for {worker.email}")
            return True
            
        except Exception as e:
            self._log("error", f"Worker {worker.email} login failed: {e}")
            return False
    
    def allocate_pairs(self):
        """Divide pairs evenly among active workers."""
        active_workers = [w for w in self.workers if w.page is not None]
        if not active_workers:
            return
        
        pairs_per_worker = len(TARGET_PAIRS) // len(active_workers)
        remainder = len(TARGET_PAIRS) % len(active_workers)
        
        start_idx = 0
        for i, worker in enumerate(active_workers):
            count = pairs_per_worker + (1 if i < remainder else 0)
            worker.assigned_pairs = TARGET_PAIRS[start_idx:start_idx + count]
            start_idx += count
            self._log("info", f"Worker {worker.email}: {len(worker.assigned_pairs)} pairs")
    
    async def worker_loop(self, worker: WorkerContext):
        """Main loop for a single worker - activates pairs and scrapes prices."""
        worker.is_running = True
        self._log("info", f"Worker {worker.email} started with {len(worker.assigned_pairs)} pairs")
        
        while not self._stop_event.is_set():
            try:
                for pair in worker.assigned_pairs:
                    if self._stop_event.is_set():
                        break
                    
                    try:
                        # Activate pair via JavaScript
                        await worker.page.evaluate(f"window.app.chart.setAsset('{pair}')")
                        await worker.page.wait_for_timeout(1500)
                        
                        # Try to scrape price from DOM
                        price = await self._scrape_price(worker.page, pair)
                        if price > 0:
                            await self.price_board.update(pair, price, source=worker.email)
                        else:
                            # Try WebSocket interception as fallback
                            price = await self._intercept_websocket_price(worker.page, pair)
                            if price > 0:
                                await self.price_board.update(pair, price, source=worker.email)
                        
                        # If pair is stale, stay on it longer
                        if not await self.price_board.is_updated(pair, threshold=5.0):
                            self._log("warn", f"Pair {pair} stale, retrying...")
                            await worker.page.evaluate(f"window.app.chart.setPeriod(300)")
                            await worker.page.wait_for_timeout(1000)
                            await worker.page.evaluate(f"window.app.chart.setPeriod(60)")
                            await worker.page.wait_for_timeout(1000)
                            
                            price = await self._scrape_price(worker.page, pair)
                            if price > 0:
                                await self.price_board.update(pair, price, source=worker.email)
                        
                    except Exception as e:
                        self._log("error", f"Worker {worker.email} error on {pair}: {e}")
                        continue
                
                # Short pause between cycles
                await worker.page.wait_for_timeout(500)
                
            except Exception as e:
                self._log("error", f"Worker {worker.email} loop error: {e}")
                await asyncio.sleep(2)
        
        worker.is_running = False
        self._log("info", f"Worker {worker.email} stopped")
    
    async def _scrape_price(self, page, pair: str) -> float:
        """Scrape current price from the DOM."""
        try:
            # Try multiple possible price selectors
            selectors = [
                '.current-price',
                '[data-testid="current-price"]',
                '.price-value',
                '.asset-price',
                '.live-price',
                '#currentPrice',
            ]
            
            for selector in selectors:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0:
                        text = await element.inner_text()
                        # Extract numeric value
                        import re
                        match = re.search(r'[\d,]+\.?\d*', text)
                        if match:
                            price = float(match.group().replace(',', ''))
                            if price > 0:
                                return price
                except Exception:
                    continue
            
            return 0.0
            
        except Exception:
            return 0.0
    
    async def _intercept_websocket_price(self, page, pair: str) -> float:
        """Try to get price from WebSocket interception."""
        try:
            # Listen for network responses that might contain price data
            # This is a fallback if DOM scraping fails
            return 0.0  # Placeholder - would need actual WS interception setup
        except Exception:
            return 0.0
    
    async def start(self, pin_callback: Callable[[str], str]) -> bool:
        """Start the Matrix with all workers."""
        try:
            await self.initialize()
            
            success_count = 0
            for worker in self.workers:
                worker.pin_callback = pin_callback
                if await self.login_worker(worker, pin_callback):
                    success_count += 1
            
            if success_count == 0:
                self._log("error", "No workers logged in successfully")
                return False
            
            self.allocate_pairs()
            
            # Start worker loops
            self.tasks = [
                asyncio.create_task(self.worker_loop(worker))
                for worker in self.workers
                if worker.page is not None
            ]
            
            self._log("info", f"Matrix started with {len(self.tasks)} active workers")
            return True
            
        except Exception as e:
            self._log("error", f"Matrix start failed: {e}")
            return False
    
    async def stop(self):
        """Stop all workers and cleanup."""
        self._stop_event.set()
        
        # Wait for tasks to finish
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks = []
        
        # Close browser contexts
        for worker in self.workers:
            if worker.browser_context:
                try:
                    await worker.browser_context.close()
                except Exception:
                    pass
                worker.browser_context = None
                worker.page = None
        
        # Close browser
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        
        self._log("info", "Matrix stopped")
    
    async def get_all_prices(self) -> dict[str, float]:
        """Get current prices from all workers."""
        return await self.price_board.get_all_prices()
    
    async def get_worker_status(self) -> list[dict]:
        """Get status of all workers."""
        return [
            {
                "email": w.email,
                "running": w.is_running,
                "pairs": len(w.assigned_pairs),
                "session_cached": w.session_file.exists() if w.session_file else False,
            }
            for w in self.workers
        ]


async def optimized_deep_scan(price_board: GlobalPriceBoard, analysis_callback, log_callback=None):
    """
    Optimized Deep Scan that reads from GlobalPriceBoard instead of fetching candles.
    Executes analysis on all 24 pairs concurrently.
    """
    all_prices = await price_board.get_all_prices()
    stale_pairs = await price_board.get_stale_pairs(threshold=5.0)
    
    if not all_prices:
        if log_callback:
            log_callback("warn", "No prices available in GlobalPriceBoard")
        return {"error": "No data available", "scanned": 0}
    
    # Create analysis tasks for all pairs with valid prices
    async def analyze_pair(symbol: str):
        price = all_prices.get(symbol, 0)
        if price <= 0:
            return {"asset": symbol, "status": "no_data", "confidence": 0}
        
        try:
            # Run technical analysis on this pair
            result = await analysis_callback(symbol, price)
            return {
                "asset": symbol,
                "status": result.get("action", "HOLD"),
                "confidence": result.get("confidence", 0),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            return {"asset": symbol, "status": "error", "message": str(e)}
    
    # Execute all analyses concurrently
    tasks = [analyze_pair(symbol) for symbol in TARGET_PAIRS if symbol in all_prices]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    scan_rows = []
    best_asset = None
    best_confidence = 0
    
    for result in results:
        if isinstance(result, Exception):
            scan_rows.append({"status": "error", "message": str(result)})
            continue
        
        scan_rows.append(result)
        conf = result.get("confidence", 0)
        if conf > best_confidence and result.get("status") in ("CALL", "PUT"):
            best_confidence = conf
            best_asset = result
    
    return {
        "scanned": len(scan_rows),
        "rows": scan_rows,
        "best": best_asset,
        "timestamp": time.time(),
    }
