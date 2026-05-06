"""
Live Quotex Backend - Reconstructed with Data Extraction Fixes.

This module handles browser-based login and market data extraction for Quotex.
Supports both Selenium and Playwright engines.
Uses CDMConnection as primary backend when available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import pickle
import platform
import random
import re
import secrets
import shutil
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..models import AssetInfo, Candle, ConnectionProfile, TradeTicket

try:
    from .cdm import CDMConnection as _CDMConnection
except ImportError:
    _CDMConnection = None


PREFERRED_LIVE_SYMBOLS = [
    "USDBDT_otc", "NZDCAD_otc", "USDEGP_otc", "NZDUSD_otc",
    "USDMXN_otc", "AUDCHF_otc", "USDCOP_otc", "USDINR_otc",
    "USDPKR_otc", "EURNZD_otc", "USDDZD_otc", "USDZAR_otc",
    "USDARS_otc", "CADCHF_otc", "AUDNZD_otc", "USDIDR_otc",
    "EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc", "USDJPY_otc",
    "EURJPY_otc", "GBPJPY_otc", "USDCAD_otc", "USDCHF_otc",
]


def _detect_chrome_version_main() -> int:
    """Detect installed Chrome major version."""
    try:
        if platform.system() == "Windows":
            import winreg
            locations = [
                (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome"),
            ]
            for root, key_path in locations:
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        version, _ = winreg.QueryValueEx(key, "version")
                        return int(str(version).split(".")[0])
                except OSError:
                    continue
    except Exception:
        pass
    return 147


CHROME_VERSION = _detect_chrome_version_main()


def _parse_browser_major_from_driver_error(message: str) -> int | None:
    match = re.search(r"Current browser version is\s+(\d+)", str(message or ""), re.I)
    if match:
        return int(match.group(1))
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        if isinstance(value, str):
            return float(value.replace(",", "").replace(" ", ""))
        return default
    except (ValueError, TypeError):
        return default


def _canonical_requested_symbol(asset: str) -> str:
    if not asset:
        return ""
    asset = asset.strip().upper()
    if "_otc" not in asset:
        asset = f"{asset}_otc"
    return asset


def _countdown_from_market_timestamp(ts: float, period_seconds: int) -> int:
    now = time.time()
    diff = now - ts
    elapsed = diff % period_seconds
    return int(period_seconds - elapsed)


def _tick_row(row: dict) -> tuple[float, float] | None:
    """Extract timestamp and price from a tick row."""
    try:
        ts = _as_float(row.get("time", row.get("timestamp", time.time())))
        price = _as_float(row.get("price") or row.get("close") or row.get("value") or 0.0)
        if price > 0:
            return ts, price
        return None
    except Exception:
        return None


def _ticks_to_candle_dicts(rows: list[dict], period: int, count: int) -> list[dict]:
    """Convert tick history to candle format."""
    grouped: dict[int, list[float]] = {}
    for row in rows:
        tick = _tick_row(row)
        if not tick:
            continue
        ts, price = tick
        bucket = int(ts // period) * period
        grouped.setdefault(bucket, []).append(price)
    
    candles = []
    for bucket in sorted(grouped)[-count:]:
        prices = grouped[bucket]
        candles.append({
            "time": bucket,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": len(prices),
        })
    return candles


def _asset_from_raw(raw: Any, default_payout: float = 85.0) -> AssetInfo | None:
    """Convert raw dict to AssetInfo."""
    try:
        if isinstance(raw, AssetInfo):
            return raw
        if not isinstance(raw, dict):
            return None
        
        symbol = str(raw.get("symbol") or raw.get("asset") or "").strip()
        if not symbol:
            return None
        
        return AssetInfo(
            symbol=_canonical_requested_symbol(symbol),
            display_name=symbol.split("_")[0],
            category=raw.get("category", "Currency"),
            payout=_as_float(raw.get("payout", default_payout)),
            last_price=_as_float(raw.get("lastPrice") or raw.get("price") or raw.get("currentPrice")),
            is_open=raw.get("is_open", raw.get("isOpen", True)),
            feed_status=raw.get("feed_status", "live"),
        )
    except Exception:
        return None


def _extract_browser_market_snapshot(browser: Any, preferred_symbol: str = "") -> dict[str, Any]:
    """Extract market data from browser DOM - Direct Scraping Method."""
    preferred = _canonical_requested_symbol(preferred_symbol)

    def run_rescue_snapshot() -> dict[str, Any]:
        try:
            dom_data = browser.execute_script("""
                const root = document.querySelector('.chart-layout') || document.querySelector('.app-container') || document.body;
                const priceEl = root.querySelector('.current-price-value, [data-testid="current-price"], .price-value, .asset-price-value');
                let currentPrice = 0;
                if (priceEl) currentPrice = parseFloat(priceEl.innerText.replace(/[^0-9.]/g, '')) || 0;
                const symbolEl = root.querySelector('.current-asset-name, .asset-name-title, .active-asset-name');
                let currentSymbol = arguments[0] || '';
                if (symbolEl) currentSymbol = symbolEl.innerText.trim();
                const rows = root.querySelectorAll('.asset-row, .pair-row, .instrument-row, tbody tr');
                const assets = [];
                rows.forEach(row => {
                    try {
                        let sym = row.dataset?.symbol || row.getAttribute('data-symbol') || '';
                        if (!sym) {
                            const text = row.innerText;
                            const match = text.match(/^([A-Z]+(?:[A-Z0-9_]+)\\s+\\d)/);
                            if (match) sym = match[1].trim();
                        }
                        const priceTxt = row.querySelector('.price, .last-price, .ask')?.innerText || '';
                        const price = parseFloat(priceTxt.replace(/[^0-9.]/g, '')) || 0;
                        if (sym && sym.length > 2 && price > 0) assets.push({symbol: sym, price: price, payout: 85});
                    } catch(e) {}
                });
                return { currentSymbol: currentSymbol, lastPrice: currentPrice, assets: assets };
            """, preferred)
            
            if dom_data and isinstance(dom_data, dict):
                valid = []
                for a in dom_data.get("assets", []):
                    s = str(a.get("symbol", "")).strip()
                    p = float(a.get("price", 0))
                    if s and p > 0:
                        valid.append({
                            "symbol": s.upper(),
                            "payout": float(a.get("payout", 85)),
                            "isOpen": a.get("open", True),
                            "lastPrice": p
                        })
                if valid:
                    return {
                        "currentSymbol": str(dom_data.get("currentSymbol", preferred)),
                        "lastPrice": float(dom_data.get("lastPrice", 0)),
                        "assets": valid
                    }
        except Exception:
            pass
        return {}

    return run_rescue_snapshot()


def _session_cache_file() -> Path:
    """Get session cache file path."""
    app_data = os.environ.get("APPDATA") or os.path.expanduser("~/.eternal_quotex")
    return Path(app_data) / "eternal_quotex" / "session_cache.json"


def _save_session_cache(payload: dict) -> None:
    """Save session to cache."""
    try:
        target = _session_cache_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 10 * 1024 * 1024:
            target.unlink(missing_ok=True)
        target.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _cleanup_stale_chrome_profiles() -> None:
    """Clean up stale Chrome profile folders."""
    try:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp"
        if not base.exists():
            return
        for d in base.iterdir():
            if d.is_dir() and d.name.startswith("scoped_dir") and "Chrome" in d.name:
                try:
                    shutil.rmtree(d)
                except Exception:
                    pass
    except Exception:
        pass


class LiveQuotexBackend:
    """High-stability Quotex backend for live browser authentication and trading."""

    def __init__(self, log_callback=None, pin_callback=None) -> None:
        import threading
        self.client: Any = None
        self.browser: Any = None
        self._playwright_bridge: Any = None
        self.profile: ConnectionProfile | None = None
        self.assets: dict[str, AssetInfo] = {}
        self._quotexpy_available = False
        self._last_known_prices: dict[str, float] = {}
        self._last_reported_prices: dict[str, float] = {}
        self._last_price_update: dict[str, float] = {}
        self._frame_tick_history: dict[str, list[dict]] = {}
        self._frame_history_by_asset: dict[str, Any] = {}
        self._observed_wire_symbols: dict[str, str] = {}
        self._browser_socket_mirror_records: list[dict] = []
        self._seen_mirror_seq: set[tuple] = set()
        self._max_tick_history_per_symbol = 500
        self._max_mirror_records = 1000
        self._max_mirror_seq = 5000
        self._request_flags: dict[str, bool] = {}
        self.current_asset: str = ""
        self.current_period: int = 60
        self._log_callback = log_callback
        self._pin_callback = pin_callback
        self._pin_event = threading.Event()
        self._pin_code = ""
        self.connected = False
        self.name = "Live Quotex"

    def _check_quotexpy_available(self) -> bool:
        """Check if quotexpy can be imported."""
        try:
            from quotexpy import Quotex
            return True
        except ImportError:
            return False

    def _log(self, level: str, msg: str) -> None:
        if self._log_callback:
            self._log_callback(level, msg)
        else:
            logging.getLogger(__name__).log(getattr(logging, level.upper(), logging.INFO), msg)

    def _evict_if_needed(self, cache: dict, max_size: int = 500) -> None:
        while len(cache) > max_size:
            oldest_key = next(iter(cache))
            del cache[oldest_key]

    def _evict_list_cache(self, cache: dict[str, list], max_per_symbol: int = 500) -> None:
        for symbol, tick_list in cache.items():
            if len(tick_list) > max_per_symbol:
                cache[symbol] = tick_list[-max_per_symbol:]

    def _cleanup_mirror_seq_set(self) -> None:
        max_size = getattr(self, '_max_mirror_seq', 5000)
        if len(self._seen_mirror_seq) > max_size:
            # Remove oldest half when exceeding limit
            items = list(self._seen_mirror_seq)
            keep_count = max_size // 2
            self._seen_mirror_seq = set(items[-keep_count:])

    async def _wait_for_pin(self) -> str:
        """Wait for user PIN input. Async to not block Playwright event loop."""
        if not self._pin_callback:
            self._log("warn", "No PIN callback registered.")
            return ""
        
        self._pin_event.clear()
        self._pin_code = ""
        self._log("info", "2FA PIN Required.")
        
        self._pin_callback()
        
        # Run blocking wait on thread pool so Playwright stays responsive
        loop = asyncio.get_running_loop()
        got_pin = await loop.run_in_executor(None, self._pin_event.wait, 120.0)
        
        if got_pin:
            self._log("info", "PIN code received.")
            return self._pin_code
        else:
            self._log("warn", "PIN request timed out.")
            return ""

    def provide_pin_code(self, code: str) -> None:
        """Called by controller when user submits PIN."""
        self._pin_code = code
        self._pin_event.set()

    async def connect(self, profile: ConnectionProfile) -> Any:
        """Connect to Quotex — Playwright for auth, raw WebSocket for 25-pair prices."""
        self.profile = profile

        self._log("info", f"Connecting via Playwright bridge (visible={'no' if profile.headless else 'yes'})...")

        # Playwright always works (real browser bypasses Cloudflare)
        result = await self._connect_via_playwright(profile)
        if result is not None:
            return result

        # If Playwright somehow failed, try pyquotex as last resort
        self._log("warn", "Playwright failed, trying pyquotex...")
        return await self._connect_via_pyquotex(profile)

    async def _connect_via_pyquotex(self, profile: ConnectionProfile) -> Any:
        """Connect using pyquotex library."""
        try:
            from pyquotex.stable_api import Quotex
            from .playwright_bridge import _get_quotex_host
        except ImportError:
            return None
            
        self._log("info", "Connecting via pyquotex library...")
        
        def pin_callback() -> str:
            self._pin_event.clear()
            self._log("info", "2FA PIN Required. Please enter the code.")
            if self._pin_callback:
                self._pin_callback()
            if self._pin_event.wait(timeout=120):
                return self._pin_code
            return ""
        
        try:
            host = _get_quotex_host() or "market-qx.trade"
            self.client = Quotex(
                profile.email,
                profile.password,
                host=host,
                lang="en",
                on_otp_callback=pin_callback,
            )
            connected, reason = await asyncio.wait_for(self.client.connect(), timeout=60)
            if connected:
                self.connected = True
                self.client.set_account_mode(profile.account_mode.upper())
                balance = await self._fetch_balance_value()
                self._log("info", f"pyquotex connected! Balance: {balance}")
                await self._start_all_asset_streams()
                return self._snapshot(balance)
            else:
                self._log("warn", f"pyquotex connection failed: {reason}")
                return None
        except Exception as exc:
            self._log("warn", f"pyquotex error: {exc}")
            return None

    async def _connect_via_playwright(self, profile: ConnectionProfile) -> Any:
        """Connect using Playwright bridge for auth, then raw WebSocket for 25 pairs."""
        try:
            from .playwright_bridge import PlaywrightQuotexBridge
        except ImportError:
            raise RuntimeError("Playwright bridge not available.")

        self._log("info", "Connecting via Playwright bridge...")
        bridge = PlaywrightQuotexBridge(log_callback=self._log)

        session = await bridge.connect(
            email=profile.email,
            password=profile.password,
            email_pin=str(profile.email_pin or ""),
            headless=profile.headless,
            timeout=120.0,
            pin_callback=self._wait_for_pin,
        )

        if not session.token:
            raise RuntimeError("Playwright login succeeded but no token extracted.")

        # Save session to cache
        try:
            target = _session_cache_file()
            payload = {}
            if target.exists():
                try:
                    with target.open("r") as handle:
                        import json as _json
                        payload = _json.load(handle)
                except Exception:
                    payload = {}
            payload[profile.email] = [{
                "cookies": session.cookies,
                "ssid": session.token,
                "user_agent": session.user_agent,
                "settings": {},
            }]
            _save_session_cache(payload)
        except Exception as e:
            self._log("warn", f"Could not save session: {e}")

        self._playwright_bridge = bridge
        self.connected = True

        # Use Playwright bridge's WebSocket (browser WS already bypasses Cloudflare)
        # Raw WebSocket gets 403 - skip it entirely
        self._log("info", "Connected! Prices flow via Playwright browser's WebSocket.")

        balance = await self._fetch_balance_value()
        self._log("info", f"Playwright session connected. Balance: {balance}")

        await self._start_all_asset_streams()

        return self._snapshot(balance)

    def get_ws_prices(self) -> dict[str, dict]:
        """Get prices from Playwright bridge's tick history (thread-safe)."""
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            result = {}
            try:
                tick_history = self._playwright_bridge._tick_history
                for symbol, ticks in tick_history.items():
                    if ticks and len(ticks) > 0:
                        last = ticks[-1]
                        result[symbol] = {
                            "price": last.get("price", 0.0),
                            "time": last.get("time", 0),
                        }
            except Exception:
                pass
            return result
        # Fallback to WS prices if bridge not available
        if hasattr(self, '_ws_prices'):
            with self._ws_lock if hasattr(self, '_ws_lock') else threading.Lock():
                return dict(self._ws_prices)
        return {}

    async def _await_authorized(self, api: Any, timeout_seconds: float, account_type: int = 1) -> bool:
        """Wait for WebSocket authorization."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                if hasattr(api, "check_session") and api.check_session():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def _fetch_balance_value(self) -> float:
        """Fetch account balance."""
        # Try pyquotex client first
        try:
            if hasattr(self, 'client') and self.client:
                bal = await self.client.get_balance()
                if bal and isinstance(bal, (int, float)):
                    return float(bal)
        except Exception as e:
            self._log("debug", f"Balance fetch error: {e}")
        # Try Playwright bridge
        try:
            if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
                bal = await self._playwright_bridge.get_balance()
                if bal and bal > 0:
                    return bal
        except Exception:
            pass
        return 0.0

    async def _start_all_asset_streams(self) -> None:
        """Start streaming assets for real-time prices."""
        # Raw WebSocket already handled in _start_raw_websocket above
        
        # pyquotex client
        if hasattr(self, 'client') and self.client:
            stream_pairs = [
                "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
                "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD"
            ]
            self._log("info", f"Starting streams for {len(stream_pairs)} assets...")
            for pair in stream_pairs:
                try:
                    await self.client.start_candles_stream(f"{pair}_otc", 60)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    self._log("debug", f"Stream error for {pair}: {e}")
            self._log("info", f"pyquotex active streams: {len(stream_pairs)} assets")
            return
        
        # Fallback: Try Playwright bridge
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            self._log("info", "Using Playwright for prices - raw WebSocket handles 25 pairs")

    def _snapshot(self, balance: float) -> dict:
        """Return connection snapshot."""
        return {
            "balance": balance,
            "account": self.profile.account_mode if self.profile else "demo",
            "connected": self.connected,
        }

    async def get_instruments(self) -> list[dict[str, Any]]:
        """Get available trading instruments."""
        # Try quotexpy client first
        if hasattr(self, 'client') and self.client:
            try:
                snapshot = self._fallback_market_snapshot(self.current_asset)
                return list(snapshot.get("assets") or [])
            except Exception:
                pass
        
        # Try Playwright bridge
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            bridge = self._playwright_bridge
            # First try bridge's dedicated method
            try:
                assets = await bridge.get_instruments()
                if assets:
                    return assets
            except Exception:
                pass
            # Fall back to tick history
            assets = []
            for symbol, history in bridge._tick_history.items():
                if isinstance(history, list) and history:
                    last_price = history[-1].get("price", 0)
                    if last_price and last_price > 0:
                        assets.append({
                            "symbol": symbol,
                            "payout": 85,
                            "isOpen": True,
                            "lastPrice": last_price
                        })
            if assets:
                return assets
            
            # NEW: Try DOM scraping to get live prices directly from page
            try:
                dom_prices = await bridge.get_current_prices()
                if dom_prices:
                    for symbol, price in dom_prices.items():
                        if price and price > 0:
                            assets.append({
                                "symbol": symbol,
                                "payout": 85,
                                "isOpen": True,
                                "lastPrice": price
                            })
            except Exception:
                pass
            
            if assets:
                return assets
        
        # Fallback to DOM
        snapshot = self._fallback_market_snapshot(self.current_asset)
        return list(snapshot.get("assets") or [])

    async def get_candles(self, asset: str, offset: int = 120, period: int = 60) -> list[dict[str, Any]]:
        """Get candle data for asset."""
        symbol = _canonical_requested_symbol(asset)
        
        # Try quotexpy client
        if hasattr(self, 'client') and self.client:
            self._refresh_browser_socket_mirror()
            history = self._frame_tick_history.get(symbol, [])
            candles = _ticks_to_candle_dicts(history, int(period or 60), int(offset or 120))
            if candles:
                return candles
            snapshot = self._fallback_market_snapshot(symbol)
            return list(snapshot.get("candles") or [])
        
        # Try Playwright bridge
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            bridge = self._playwright_bridge
            history = bridge._tick_history.get(symbol, [])
            if history:
                candles = _ticks_to_candle_dicts(history, int(period or 60), int(offset or 120))
                if candles:
                    return candles
        
        return []

    def _fallback_market_snapshot(self, symbol: str) -> dict[str, Any]:
        """Extract market data from browser."""
        # Try Selenium browser
        if hasattr(self, 'browser') and self.browser:
            try:
                snapshot = _extract_browser_market_snapshot(self.browser, symbol)
                if snapshot:
                    return self._process_snapshot(snapshot, symbol)
            except Exception as e:
                self._log("warn", f"Selenium extraction failed: {e}")
        
        # Try Playwright Bridge DOM scraping
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            bridge = self._playwright_bridge
            try:
                # Access via bridge._session.page
                session = getattr(bridge, '_session', None)
                if session and hasattr(session, 'page'):
                    page = session.page
                    if page:
                        page_result = page.evaluate("""
                            () => {
                                const root = document.querySelector('.chart-layout') || document.body;
                                const priceEl = root.querySelector('.current-price-value');
                                let currentPrice = 0;
                                if (priceEl) currentPrice = parseFloat(priceEl.innerText.replace(/[^0-9.]/g, '')) || 0;
                                const symbolEl = root.querySelector('.current-asset-name');
                                let currentSymbol = arguments[0] || '';
                                if (symbolEl) currentSymbol = symbolEl.innerText.trim();
                                const rows = root.querySelectorAll('.asset-row, tbody tr');
                                const assets = [];
                                rows.forEach(row => {
                                    try {
                                        let sym = row.dataset?.symbol || '';
                                        if (!sym) {
                                            const text = row.innerText;
                                            const match = text.match(/^([A-Z]+(?:[A-Z0-9_]+)/);
                                            if (match) sym = match[1].trim();
                                        }
                                        const priceTxt = row.querySelector('.price, .last-price')?.innerText || '';
                                        const price = parseFloat(priceTxt.replace(/[^0-9.]/g, '')) || 0;
                                        if (sym && price > 0) assets.push({symbol: sym, price: price, payout: 85});
                                    } catch(e) {}
                                });
                                return { currentSymbol: currentSymbol, lastPrice: currentPrice, assets: assets };
                            }
                        """, symbol)
                        if page_result and isinstance(page_result, dict):
                            return self._process_snapshot_from_dict(page_result, symbol)
            except Exception as e:
                self._log("warn", f"Playwright DOM extraction failed: {e}")
        
        return {"currentSymbol": symbol, "lastPrice": 0, "assets": [], "candles": []}

    def _process_snapshot(self, snapshot: dict, symbol: str) -> dict[str, Any]:
        """Process raw snapshot data."""
        symbol = _canonical_requested_symbol(snapshot.get("currentSymbol") or symbol)
        price = _as_float(snapshot.get("lastPrice"))
        
        if price > 0:
            now = int(time.time())
            self._frame_tick_history.setdefault(symbol, []).append({"time": now, "price": price})
            self._evict_list_cache(self._frame_tick_history, self._max_tick_history_per_symbol)
        
        assets = []
        for item in snapshot.get("assets", []):
            s = str(item.get("symbol", "")).strip().upper()
            p = _as_float(item.get("price", 0))
            if s and p > 0:
                assets.append({
                    "symbol": s,
                    "payout": float(item.get("payout", 85)),
                    "isOpen": item.get("isOpen", True),
                    "lastPrice": p
                })
        
        candles = []
        if price > 0:
            now = int(time.time())
            candles = [
                {"time": now - self.current_period, "open": price, "high": price, "low": price, "close": price, "volume": 0},
                {"time": now, "open": price, "high": price, "low": price, "close": price, "volume": 0},
            ]
        
        return {
            "requestedSymbol": symbol,
            "currentSymbol": symbol,
            "lastPrice": price,
            "assets": assets,
            "candles": candles
        }

    def _process_snapshot_from_dict(self, snapshot: dict, symbol: str) -> dict[str, Any]:
        """Process raw dictionary from Playwright."""
        symbol = _canonical_requested_symbol(snapshot.get("currentSymbol") or symbol)
        price = _as_float(snapshot.get("lastPrice"))
        
        if price > 0:
            now = int(time.time())
            self._frame_tick_history.setdefault(symbol, []).append({"time": now, "price": price})
            self._evict_list_cache(self._frame_tick_history, self._max_tick_history_per_symbol)
        
        assets = []
        for item in snapshot.get("assets", []):
            s = str(item.get("symbol", "")).strip().upper()
            p = _as_float(item.get("price", 0))
            if s and p > 0:
                assets.append({
                    "symbol": s,
                    "payout": float(item.get("payout", 85)),
                    "isOpen": True,
                    "lastPrice": p
                })
        
        candles = []
        if price > 0:
            now = int(time.time())
            candles = [
                {"time": now - self.current_period, "open": price, "high": price, "low": price, "close": price, "volume": 0},
                {"time": now, "open": price, "high": price, "low": price, "close": price, "volume": 0},
            ]
        
        return {
            "requestedSymbol": symbol,
            "currentSymbol": symbol,
            "lastPrice": price,
            "assets": assets,
            "candles": candles
        }

    def _refresh_browser_socket_mirror(self) -> None:
        """Refresh browser socket mirror data."""
        if not self.browser:
            return
        try:
            mirror = self.browser.execute_script(
                "const mirror = window.__eternalSocketMirror; return mirror ? Object.values(mirror) : [];"
            )
            if not mirror:
                return
            for record in mirror or []:
                if not isinstance(record, dict):
                    continue
                socket_id = str(record.get("id", "mirror"))
                incoming_sample = []
                outgoing_sample = []
                for field, outgoing in (("incoming", False), ("outgoing", True)):
                    for raw in record.get(field, []) or []:
                        seq = raw.get("seq") if isinstance(raw, dict) else None
                        if seq is not None:
                            key = (f"{socket_id}:{field}", int(seq))
                            if key in self._seen_mirror_seq:
                                continue
                            self._seen_mirror_seq.add(key)
                        sample_value = raw.get("data") if isinstance(raw, dict) else raw
                        if field == "incoming" and len(incoming_sample) < 5:
                            incoming_sample.append(str(sample_value))
                        if field == "outgoing" and len(outgoing_sample) < 5:
                            outgoing_sample.append(str(sample_value))
                self._browser_socket_mirror_records.append({
                    "id": socket_id,
                    "url": str(record.get("url", "")),
                    "open": bool(record.get("open", False)),
                    "incomingSample": "\n".join(incoming_sample),
                    "outgoingSample": "\n".join(outgoing_sample),
                    "updatedAt": record.get("updatedAt", 0),
                })
            max_records = getattr(self, '_max_mirror_records', 1000)
            if len(self._browser_socket_mirror_records) > max_records:
                self._browser_socket_mirror_records = self._browser_socket_mirror_records[-max_records:]
            self._cleanup_mirror_seq_set()
        except Exception:
            pass

    async def fetch_balance(self) -> float:
        """Fetch current balance."""
        return await self._fetch_balance_value()

    async def set_active_asset(self, symbol: str, period: int = 60) -> None:
        """Set active trading asset."""
        self.current_asset = _canonical_requested_symbol(symbol)
        self.current_period = int(period or 60)

    async def buy(self, amount: float, asset: str, duration: int) -> dict:
        """Place a BUY trade."""
        return await self._execute_trade("call", amount, asset, duration)

    async def sell(self, amount: float, asset: str, duration: int) -> dict:
        """Place a SELL trade."""
        return await self._execute_trade("put", amount, asset, duration)

    async def _execute_trade(self, action: str, amount: float, asset: str, duration: int) -> dict:
        """Execute trade via WebSocket or Playwright bridge."""
        symbol = _canonical_requested_symbol(asset)
        self.current_asset = symbol

        MIN_DURATION = 30
        MAX_DURATION = 900
        if duration < MIN_DURATION or duration > MAX_DURATION:
            raise ValueError(f"Duration must be {MIN_DURATION}-{MAX_DURATION}s")

        current_balance = await self._fetch_balance_value()
        if amount > current_balance * 0.95 and current_balance > 0:
            raise ValueError("Trade amount exceeds available balance")

        # Try quotexpy client first
        if hasattr(self, 'client') and self.client:
            try:
                if action == "call":
                    result = await self.client.buy(amount, symbol, duration)
                else:
                    result = await self.client.buy(amount, symbol, duration, sell=True)
                if result:
                    return {"ok": True, "result": result}
            except Exception as e:
                self._log("warn", f"quotexpy trade failed: {e}")
        
        # Fallback: Try Playwright bridge trade execution
        if hasattr(self, '_playwright_bridge') and self._playwright_bridge:
            try:
                result = await self._playwright_bridge.place_trade(symbol, action, amount, duration)
                if result.get("ok"):
                    return result
            except Exception as e:
                self._log("warn", f"Playwright bridge trade failed: {e}")
        
        return {"ok": False, "error": "Trade execution failed"}

    async def fetch_assets(self) -> list[AssetInfo]:
        """Fetch available assets - implements TradingBackend interface."""
        instruments = await self.get_instruments()
        assets = []
        for item in instruments:
            asset = _asset_from_raw(item)
            if asset:
                assets.append(asset)
        return assets

    async def fetch_candles(self, asset: str, period_seconds: int = 60, count: int = 80) -> list[Candle]:
        """Fetch candle data - implements TradingBackend interface."""
        candles_data = await self.get_candles(asset, count, period_seconds)
        candles = []
        for c in candles_data:
            candles.append(Candle(
                time=int(c.get("time", 0)),
                open=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
                volume=int(c.get("volume", 0)),
            ))
        return candles

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        """Place a trade - implements TradingBackend interface."""
        result = await self._execute_trade(action, amount, asset, duration)
        ticket = TradeTicket(
            id=str(secrets.token_hex(8)),
            asset=asset,
            action=action,
            amount=amount,
            duration=duration,
            opened_at=time.time(),
            expiry_time=time.time() + duration,
            result=None,
            accepted=result.get("ok", False),
        )
        return ticket

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        """Check trade result - implements TradingBackend interface."""
        return ticket

    async def disconnect(self) -> None:
        """Disconnect backend - implements TradingBackend interface."""
        self.connected = False
        if self._playwright_bridge:
            await self._playwright_bridge.close()
        self._log("info", "Backend disconnected.")

    def diagnostics_snapshot(self, symbol: str = "") -> dict[str, Any]:
        """Get diagnostics."""
        self._refresh_browser_socket_mirror()
        data = {
            "connected": self.connected,
            "has_client": bool(self.client),
            "has_bridge": bool(self._playwright_bridge),
            "has_browser": bool(self.browser),
            "mirror_count": len(self._browser_socket_mirror_records),
            "tick_history_keys": list(self._frame_tick_history.keys()),
        }
        if symbol:
            data["symbol_ticks"] = len(self._frame_tick_history.get(_canonical_requested_symbol(symbol), []))
        return data


def default_live_assets() -> list[str]:
    """Return the default list of Quotex OTC asset symbols."""
    return list(PREFERRED_LIVE_SYMBOLS)


# Functions needed by ws_worker_pool.py
def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to standard format."""
    return _canonical_requested_symbol(symbol)


def _broker_symbol_aliases() -> dict:
    """Return broker symbol aliases."""
    return {}


def _is_requested_live_symbol(symbol: str) -> bool:
    """Check if symbol is a valid live/OTC symbol."""
    return symbol.endswith("_otc") or symbol.upper() in PREFERRED_LIVE_SYMBOLS


def _symbol_variants(symbol: str) -> list:
    """Get symbol variants (OTC, regular, etc)."""
    base = symbol.replace("_otc", "").upper()
    return [f"{base}_otc", base]


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    return _as_float(value, default)