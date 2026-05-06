from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from eternal_quotex_bot.backend.base import TradingBackend
from eternal_quotex_bot.models import AccountSnapshot, AssetInfo, Candle, ConnectionProfile, TradeTicket


DEFAULT_EXNESS_SYMBOLS = (
    ("EURUSD", "forex", "EUR/USD"),
    ("GBPUSD", "forex", "GBP/USD"),
    ("USDJPY", "forex", "USD/JPY"),
    ("USDCHF", "forex", "USD/CHF"),
    ("USDCAD", "forex", "USD/CAD"),
    ("AUDUSD", "forex", "AUD/USD"),
    ("NZDUSD", "forex", "NZD/USD"),
    ("EURGBP", "forex", "EUR/GBP"),
    ("EURJPY", "forex", "EUR/JPY"),
    ("GBPJPY", "forex", "GBP/JPY"),
    ("EURCHF", "forex", "EUR/CHF"),
    ("AUDJPY", "forex", "AUD/JPY"),
    ("EURAUD", "forex", "EUR/AUD"),
    ("GBPCHF", "forex", "GBP/CHF"),
    ("CADJPY", "forex", "CAD/JPY"),
    ("AUDCAD", "forex", "AUD/CAD"),
    ("AUDCHF", "forex", "AUD/CHF"),
    ("AUDNZD", "forex", "AUD/NZD"),
    ("CADCHF", "forex", "CAD/CHF"),
    ("CHFJPY", "forex", "CHF/JPY"),
    ("EURNZD", "forex", "EUR/NZD"),
    ("EURCAD", "forex", "EUR/CAD"),
    ("GBPAUD", "forex", "GBP/AUD"),
    ("GBPCAD", "forex", "GBP/CAD"),
    ("GBPNZD", "forex", "GBP/NZD"),
    ("NZDJPY", "forex", "NZD/JPY"),
    ("NZDCAD", "forex", "NZD/CAD"),
    ("NZDCHF", "forex", "NZD/CHF"),
    ("AUDSGD", "forex", "AUD/SGD"),
    ("EURSGD", "forex", "EUR/SGD"),
    ("GBPSGD", "forex", "GBP/SGD"),
    ("USDSGD", "forex", "USD/SGD"),
    ("USDNOK", "forex", "USD/NOK"),
    ("USDSEK", "forex", "USD/SEK"),
    ("USDTRY", "forex", "USD/TRY"),
    ("EURTRY", "forex", "EUR/TRY"),
    ("EURPLN", "forex", "EUR/PLN"),
    ("USDPLN", "forex", "USD/PLN"),
    ("USDMXN", "forex", "USD/MXN"),
    ("USDCNH", "forex", "USD/CNH"),
    ("USDHKD", "forex", "USD/HKD"),
)

EXNESS_CATEGORY_ORDER = {"forex": 0, "other": 1}
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
TWELVE_DATA_DEFAULT_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

DEFAULT_POCKET_SYMBOLS = (
    "USDBDT_otc",
    "USDINR_otc",
    "USDPKR_otc",
    "USDZAR_otc",
    "USDARS_otc",
    "USDIDR_otc",
    "USDDZD_otc",
    "USDMXN_otc",
    "USDBRL_otc",
    "USDJPY_otc",
    "EURCHF_otc",
    "NZDUSD_otc",
)


def default_pocket_option_assets(limit: int = 12) -> list[AssetInfo]:
    return [
        AssetInfo(
            symbol=symbol,
            payout=0.0,
            is_open=False,
            category="pocket_option",
            last_price=0.0,
        )
        for symbol in DEFAULT_POCKET_SYMBOLS[:limit]
    ]


def default_iq_option_assets(limit: int = 12) -> list[AssetInfo]:
    return [
        replace(asset, category="iq_option")
        for asset in default_pocket_option_assets(limit)
    ]


def default_exness_assets(limit: int | None = None) -> list[AssetInfo]:
    if limit is None:
        limit = len(DEFAULT_EXNESS_SYMBOLS)
    return [
        AssetInfo(
            symbol=symbol,
            payout=0.0,
            is_open=True,
            category=category,
            display_name=display_name,
            last_price=0.0,
        )
        for symbol, category, display_name in DEFAULT_EXNESS_SYMBOLS[:limit]
    ]


def _normalize_otc_symbol(value: str) -> str:
    text = str(value or "").strip().upper().replace("/", "")
    if not text:
        return ""
    if text.endswith("(OTC)"):
        text = text[:-5].strip()
    text = text.replace(" ", "")
    if text.endswith("_OTC"):
        return text[:-4] + "_otc"
    if text.endswith("OTC") and len(text) > 3:
        return text[:-3] + "_otc"
    if len(text) == 6 and text.isalpha():
        return text
    return text.replace("-", "_")


def _display_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip()
    if normalized.lower().endswith("_otc"):
        base = normalized[:-4]
        suffix = " (OTC)"
    else:
        base = normalized
        suffix = ""
    if len(base) == 6 and base.isalpha():
        return f"{base[:3]}/{base[3:]}{suffix}"
    return normalized


def _extract_tick_price(tick: Any) -> float:
    if tick is None:
        return 0.0
    for field in ("last", "bid", "ask"):
        try:
            value = float(getattr(tick, field, 0.0) or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _normalize_forex_symbol(value: str) -> str:
    text = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if len(text) == 6 and text.isalpha():
        return text
    return text


def _format_twelve_symbol(symbol: str) -> str:
    normalized = _normalize_forex_symbol(symbol)
    if len(normalized) == 6 and normalized.isalpha():
        return f"{normalized[:3]}/{normalized[3:]}"
    return str(symbol or "").strip().upper()


def _twelve_interval(period_seconds: int) -> str:
    if period_seconds <= 60:
        return "1min"
    if period_seconds <= 300:
        return "5min"
    if period_seconds <= 900:
        return "15min"
    if period_seconds <= 1800:
        return "30min"
    if period_seconds <= 3600:
        return "1h"
    return "4h"


def _parse_twelve_timestamp(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return int(time.time())
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for fmt in formats:
        with suppress(ValueError):
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
    return int(time.time())


def _twelve_api_get(endpoint: str, params: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    query = dict(params)
    query["apikey"] = api_key or TWELVE_DATA_DEFAULT_KEY
    request = Request(
        f"{TWELVE_DATA_BASE_URL}/{endpoint}?{urlencode(query)}",
        headers={
            "Authorization": f"apikey {api_key or TWELVE_DATA_DEFAULT_KEY}",
            "Accept": "application/json",
            "User-Agent": "EternalQuotexBot/1.0",
        },
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and str(payload.get("status") or "").lower() == "error":
        message = str(payload.get("message") or payload).strip()
        if "demo" in message.lower() and "api key" in message.lower():
            raise RuntimeError("Forex Market feed key required. Enter your saved feed key in Live > Forex Market, then connect again.")
        raise RuntimeError(message)
    return payload if isinstance(payload, dict) else {}


def _classify_exness_symbol(name: str, path_text: str, description: str) -> str:
    upper_name = str(name or "").strip().upper()
    lower_path = str(path_text or "").strip().lower()
    lower_description = str(description or "").strip().lower()
    combined = " ".join(part for part in (lower_path, lower_description, upper_name.lower()) if part)

    if any(token in combined for token in ("crypto", "bitcoin", "ethereum", "litecoin", "dogecoin", "solana", "cardano")):
        return "crypto"
    if upper_name.startswith(("BTC", "ETH", "LTC", "XRP", "DOGE", "SOL", "ADA", "BNB")):
        return "crypto"
    if any(token in combined for token in ("metal", "metals", "gold", "silver", "palladium", "platinum")):
        return "metals"
    if upper_name.startswith(("XAU", "XAG", "XPD", "XPT")):
        return "metals"
    if any(token in combined for token in ("index", "indices", "cash", "us30", "ustec", "us500", "uk100", "ger40", "jp225", "hsi", "nasdaq", "dow")):
        return "indices"
    if any(token in combined for token in ("energy", "energies", "oil", "brent", "wtioil", "natgas", "gas")):
        return "energies"
    if any(token in combined for token in ("commodity", "commodities", "coffee", "cotton", "cocoa", "sugar", "corn", "wheat")):
        return "commodities"
    if any(token in combined for token in ("stock", "stocks", "share", "shares", "equities")):
        return "stocks"
    if re.fullmatch(r"[A-Z]{6}[A-Z0-9._-]*", upper_name):
        return "forex"
    if re.fullmatch(r"[A-Z]{1,6}[A-Z0-9._-]*", upper_name):
        return "stocks"
    return "other"


def _format_exness_display_name(name: str, description: str, category: str) -> str:
    upper_name = str(name or "").strip().upper()
    clean_name = upper_name.lstrip("#")

    if category in {"forex", "crypto", "metals"}:
        match = re.search(r"([A-Z]{6})", clean_name)
        if match:
            pair = match.group(1)
            return f"{pair[:3]}/{pair[3:]}"
    if category == "stocks":
        match = re.match(r"([A-Z]{1,6})", clean_name)
        if match:
            return match.group(1)
    if description:
        trimmed = str(description).strip()
        if len(trimmed) <= 32:
            return trimmed
    return upper_name


def _is_probable_mt5_terminal_path(path: Path) -> bool:
    lower_path = str(path or "").strip().lower()
    if not lower_path:
        return False
    if "mt4" in lower_path:
        return False
    filename = Path(lower_path).name
    if filename == "terminal64.exe":
        return True
    if filename not in {"terminal.exe", "metatrader.exe", "metatrader64.exe"}:
        return False
    return any(token in lower_path for token in ("mt5", "metatrader 5", "metatrader5", "exness mt5", "exness metatrader 5"))


def _discover_mt5_terminal_candidates(server_hint: str = "") -> list[Path]:
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        raw = os.environ.get(env_name, "")
        if raw:
            candidate = Path(raw)
            if candidate.exists():
                roots.append(candidate)

    direct_dirs = (
        "MetaTrader 5",
        "Exness MetaTrader 5",
        "Exness MT5",
        "MetaTrader5",
        "Programs\\MetaTrader 5",
        "Programs\\Exness MetaTrader 5",
    )
    candidates: list[Path] = []
    seen: set[str] = set()

    def add_candidate(path: Path) -> None:
        key = str(path).lower()
        if path.exists() and key not in seen and _is_probable_mt5_terminal_path(path):
            seen.add(key)
            candidates.append(path)

    for root in roots:
        for directory in direct_dirs:
            folder = root / directory
            add_candidate(folder / "terminal64.exe")
            add_candidate(folder / "terminal.exe")
        with suppress(Exception):
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                label = child.name.lower()
                if "mt4" in label:
                    continue
                if not any(token in label for token in ("meta", "mt5", "exness")):
                    continue
                add_candidate(child / "terminal64.exe")
                add_candidate(child / "terminal.exe")

    hint_tokens = [token for token in re.split(r"[^a-z0-9]+", str(server_hint or "").lower()) if token]
    if hint_tokens:
        candidates.sort(
            key=lambda path: (
                0 if any(token in str(path).lower() for token in hint_tokens) else 1,
                0 if "exness" in str(path).lower() else 1,
                len(str(path)),
            )
        )
    return candidates


def _hide_mt5_windows(path_hint: str = "") -> None:
    with suppress(Exception):
        import ctypes
        import psutil

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SW_HIDE = 0
        path_hint_norm = str(path_hint or "").lower()
        candidates: set[int] = set()

        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                exe = str(proc.info.get("exe") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name not in {"terminal64.exe", "terminal.exe", "metatrader64.exe", "metatrader.exe"} and "terminal" not in name:
                continue
            if path_hint_norm and exe and path_hint_norm not in exe:
                continue
            candidates.add(int(proc.info["pid"]))

        if not candidates:
            return

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value or 0) in candidates:
                user32.ShowWindow(hwnd, SW_HIDE)
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
    return None


def _normalize_mt5_volume(raw_volume: float, symbol_info: Any) -> float:
    volume_min = float(getattr(symbol_info, "volume_min", 0.01) or 0.01)
    volume_max = float(getattr(symbol_info, "volume_max", 100.0) or 100.0)
    volume_step = float(getattr(symbol_info, "volume_step", 0.01) or 0.01)
    bounded = min(max(float(raw_volume), volume_min), volume_max)
    steps = round((bounded - volume_min) / volume_step)
    normalized = volume_min + steps * volume_step
    return round(max(volume_min, min(normalized, volume_max)), 2)


def _exness_sort_key(asset: AssetInfo) -> tuple[int, str]:
    return (EXNESS_CATEGORY_ORDER.get(asset.category, 99), asset.display_name or asset.symbol)


def _build_tick_candles(ticks: list[tuple[float, float]], period_seconds: int, count: int = 80) -> list[Candle]:
    if not ticks:
        return []
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts, price in ticks:
        bucket = int(ts // period_seconds) * period_seconds
        buckets[bucket].append(float(price))
    candles: list[Candle] = []
    for bucket in sorted(buckets):
        prices = buckets[bucket]
        candles.append(
            Candle(
                timestamp=int(bucket),
                open=float(prices[0]),
                high=max(prices),
                low=min(prices),
                close=float(prices[-1]),
                volume=float(len(prices)),
            )
        )
    return candles[-count:]


def _validated_mt5_login(raw_value: str) -> int:
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError("Exness login is required.")
    if not text.isdigit():
        raise ValueError("Exness login must be the numeric MT5 account login, not an email or username.")
    return int(text)


def _frame_targets(page: Any) -> list[Any]:
    if page is None:
        return []
    targets: list[Any] = []
    main_frame = getattr(page, "main_frame", None)
    if main_frame is not None:
        targets.append(main_frame)
    for frame in getattr(page, "frames", []):
        if frame is not None and frame not in targets:
            targets.append(frame)
    return targets or [page]


async def _count_locator(target: Any, selector: str) -> int:
    try:
        return await target.locator(selector).count()
    except Exception:
        return 0


async def _click_first_matching(targets: list[Any], selectors: tuple[str, ...], *, timeout: int = 2_500) -> bool:
    for target in targets:
        for selector in selectors:
            try:
                locator = target.locator(selector).first
                if await locator.count():
                    await locator.click(timeout=timeout)
                    return True
            except Exception:
                continue
    return False


async def _fill_first_matching(targets: list[Any], selectors: tuple[str, ...], value: str) -> bool:
    for target in targets:
        for selector in selectors:
            try:
                locator = target.locator(selector).first
                if await locator.count():
                    await locator.fill(value)
                    return True
            except Exception:
                continue
    return False


class TwelveDataForexBackend(TradingBackend):
    name = "Forex Market"

    def __init__(self) -> None:
        self.profile = ConnectionProfile()
        self.connected = False
        self.last_balance = 0.0
        self.assets_cache: dict[str, AssetInfo] = {}
        self.selected_asset = "EURUSD"
        self._catalog_symbols: list[str] = []
        self._catalog_cursor = 0
        self._api_key = TWELVE_DATA_DEFAULT_KEY
        self._cache_timestamp: float = 0.0

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        self.profile = replace(profile)
        self._api_key = str(self.profile.exness_server or TWELVE_DATA_DEFAULT_KEY).strip() or TWELVE_DATA_DEFAULT_KEY
        self.selected_asset = _normalize_forex_symbol(profile.selected_asset or "EURUSD") or "EURUSD"
        await asyncio.to_thread(self._connect_sync)
        self.connected = True
        self.last_balance = 0.0
        return AccountSnapshot(balance=0.0, mode="DATA", backend_name=self.name)

    def _connect_sync(self) -> None:
        if not self._api_key or self._api_key.lower() == "demo":
            raise ValueError("Forex Market feed key required. Open Live > Forex Market, paste your feed key, and connect again.")
        self._fetch_probe_candles(self.selected_asset or "EURUSD")

    def _fetch_probe_candles(self, symbol: str) -> None:
        payload = _twelve_api_get(
            "time_series",
            {
                "symbol": _format_twelve_symbol(symbol),
                "interval": "1min",
                "outputsize": 2,
                "order": "asc",
                "timezone": "UTC",
            },
            api_key=self._api_key,
        )
        values = payload.get("values") or []
        if not isinstance(values, list) or not values:
            raise RuntimeError("Forex Market did not return live candle data.")

    async def disconnect(self) -> None:
        self.assets_cache.clear()
        self._catalog_symbols = []
        self._catalog_cursor = 0
        self._cache_timestamp = 0.0
        self.connected = False

    async def fetch_assets(self) -> list[AssetInfo]:
        return await asyncio.to_thread(self._fetch_assets_sync)

    def _fetch_assets_sync(self) -> list[AssetInfo]:
        cache_age = time.time() - self._cache_timestamp
        if not self.assets_cache or cache_age > 300:
            assets = default_exness_assets(limit=len(DEFAULT_EXNESS_SYMBOLS))
            assets.sort(key=_exness_sort_key)
            self.assets_cache = {asset.symbol: asset for asset in assets}
            self._catalog_symbols = [asset.symbol for asset in assets]
            self._catalog_cursor = 0
            self._cache_timestamp = time.time()
        self._refresh_quotes()
        return sorted(self.assets_cache.values(), key=_exness_sort_key)

    def _refresh_quotes(self) -> None:
        if not self._catalog_symbols:
            self._catalog_symbols = list(self.assets_cache)
        if not self._catalog_symbols:
            return
        symbols = [self.selected_asset] if self.selected_asset else []
        chunk_size = 8
        start = self._catalog_cursor % len(self._catalog_symbols)
        sample = self._catalog_symbols[start : start + chunk_size]
        if len(sample) < chunk_size:
            sample += self._catalog_symbols[: chunk_size - len(sample)]
        self._catalog_cursor = (start + chunk_size) % max(1, len(self._catalog_symbols))
        for symbol in dict.fromkeys(symbols + sample):
            if not symbol:
                continue
            price = self._fetch_last_price(symbol)
            asset = self.assets_cache.get(symbol)
            if asset is None:
                continue
            if price > 0:
                asset.last_price = price
                asset.feed_status = "live"
                asset.is_open = True

    def _fetch_last_price(self, symbol: str) -> float:
        payload = _twelve_api_get(
            "time_series",
            {
                "symbol": _format_twelve_symbol(symbol),
                "interval": "1min",
                "outputsize": 1,
                "order": "desc",
                "timezone": "UTC",
            },
            api_key=self._api_key,
        )
        values = payload.get("values") or []
        if not isinstance(values, list) or not values:
            return 0.0
        row = values[0] or {}
        for key in ("close", "open", "high", "low"):
            with suppress(Exception):
                value = float(row.get(key) or 0.0)
                if value > 0:
                    return value
        return 0.0

    async def fetch_balance(self) -> float:
        return 0.0

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        return await asyncio.to_thread(self._fetch_candles_sync, asset, period_seconds, count)

    def _fetch_candles_sync(self, asset: str, period_seconds: int, count: int) -> list[Candle]:
        symbol = self._resolve_symbol_name(asset)
        payload = _twelve_api_get(
            "time_series",
            {
                "symbol": _format_twelve_symbol(symbol),
                "interval": _twelve_interval(period_seconds),
                "outputsize": max(30, min(int(count), 5000)),
                "order": "asc",
                "timezone": "UTC",
            },
            api_key=self._api_key,
        )
        values = payload.get("values") or []
        if not isinstance(values, list) or not values:
            raise RuntimeError(f"Forex Market did not return candle data for {_format_twelve_symbol(symbol)}.")
        candles = [
            Candle(
                timestamp=_parse_twelve_timestamp(row.get("datetime", "")),
                open=float(row.get("open") or 0.0),
                high=float(row.get("high") or 0.0),
                low=float(row.get("low") or 0.0),
                close=float(row.get("close") or 0.0),
                volume=float(row.get("volume") or 0.0),
            )
            for row in values
            if row.get("open") is not None and row.get("close") is not None
        ]
        if not candles:
            raise RuntimeError(f"Forex Market returned an empty candle set for {_format_twelve_symbol(symbol)}.")
        asset_info = self.assets_cache.get(symbol)
        if asset_info is not None:
            asset_info.last_price = candles[-1].close
            asset_info.feed_status = "live"
            asset_info.is_open = True
        return candles[-count:]

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        raise RuntimeError("Forex Market is a data-only provider. Manual trade submission is not available.")

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        return ticket

    def set_selected_asset(self, asset: str, period_seconds: int | None = None) -> None:
        normalized = self._resolve_symbol_name(asset)
        if normalized:
            self.selected_asset = normalized
            self.profile.selected_asset = normalized

    def _resolve_symbol_name(self, asset: str) -> str:
        normalized = _normalize_forex_symbol(asset)
        if normalized:
            return normalized
        return _normalize_forex_symbol(self.selected_asset or self.profile.selected_asset or "EURUSD") or "EURUSD"


class ExnessMt5Backend(TradingBackend):
    name = "Exness / MT5"

    def __init__(self) -> None:
        self.profile = ConnectionProfile()
        self.connected = False
        self.last_balance = 0.0
        self.assets_cache: dict[str, AssetInfo] = {}
        self.selected_asset = ""
        self._mt5 = None
        self._mt5_lock = threading.RLock()
        self._terminal_path = ""
        self._catalog_symbols: list[str] = []
        self._catalog_cursor = 0
        self._cache_timestamp: float = 0.0

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        self.profile = replace(profile)
        self.selected_asset = str(profile.selected_asset or "").replace("_otc", "")
        login = self.profile.exness_login.strip()
        password = self.profile.exness_password
        if not (login and password):
            raise ValueError("Exness login and password are required.")
        _validated_mt5_login(login)
        snapshot = await asyncio.to_thread(self._connect_sync)
        self.connected = True
        self.last_balance = snapshot.balance
        return snapshot

    def _connect_sync(self) -> AccountSnapshot:
        with self._mt5_lock:
            mt5 = self._ensure_mt5_session(force_reconnect=True)
            account = mt5.account_info()
            if account is None:
                raise RuntimeError(f"MetaTrader5 account_info failed: {mt5.last_error()}")
            return AccountSnapshot(
                balance=float(getattr(account, "balance", 0.0) or 0.0),
                mode=self.profile.account_mode.upper(),
                backend_name=self.name,
            )

    async def disconnect(self) -> None:
        await asyncio.to_thread(self._disconnect_sync)
        self.assets_cache.clear()
        self._catalog_symbols = []
        self._catalog_cursor = 0
        self.connected = False

    def _disconnect_sync(self) -> None:
        with self._mt5_lock:
            if self._mt5 is not None:
                with suppress(Exception):
                    self._mt5.shutdown()
            self._mt5 = None

    def _ensure_mt5_session(self, *, force_reconnect: bool = False):
        import MetaTrader5 as mt5

        if force_reconnect and self._mt5 is not None:
            with suppress(Exception):
                self._mt5.shutdown()
            self._mt5 = None

        if self._mt5 is not None:
            with suppress(Exception):
                if self._mt5.terminal_info() is not None:
                    return self._mt5
            with suppress(Exception):
                self._mt5.shutdown()
            self._mt5 = None

        login = _validated_mt5_login(self.profile.exness_login)
        password = str(self.profile.exness_password or "")
        server = str(self.profile.exness_server or "").strip()
        attempts: list[str] = []
        init_attempts: list[tuple[str, dict[str, Any]]] = []
        for candidate in _discover_mt5_terminal_candidates(server):
            init_attempts.append((str(candidate), {"path": str(candidate)}))
        init_attempts.append(("default", {}))

        for label, init_kwargs in init_attempts:
            if not mt5.initialize(**init_kwargs):
                attempts.append(f"{label} initialize -> {mt5.last_error()}")
                with suppress(Exception):
                    mt5.shutdown()
                continue

            self._terminal_path = str(init_kwargs.get("path", ""))
            try:
                login_kwargs: dict[str, Any] = {"login": login}
                if password:
                    login_kwargs["password"] = password
                if server:
                    login_kwargs["server"] = server
                if not mt5.login(**login_kwargs):
                    attempts.append(f"{label} login -> {mt5.last_error()}")
                    with suppress(Exception):
                        mt5.shutdown()
                    continue

                account = mt5.account_info()
                if account is None:
                    attempts.append(f"{label} account -> {mt5.last_error()}")
                    with suppress(Exception):
                        mt5.shutdown()
                    continue

                try:
                    account_server = str(getattr(account, "server", "") or "").strip()
                    if account_server:
                        self.profile.exness_server = account_server
                except Exception:
                    pass

                _hide_mt5_windows(self._terminal_path)
                self._mt5 = mt5
                return mt5
            except Exception as error:
                attempts.append(f"{label} login -> {error}")
                with suppress(Exception):
                    mt5.shutdown()

        summary = " | ".join(attempts[:8]) or str(mt5.last_error())
        raise RuntimeError(f"MetaTrader5 initialize/login failed: {summary}")

    async def fetch_assets(self) -> list[AssetInfo]:
        assets = await asyncio.to_thread(self._fetch_assets_sync)
        self.assets_cache = {asset.symbol: asset for asset in assets}
        return assets

    def _fetch_assets_sync(self) -> list[AssetInfo]:
        with self._mt5_lock:
            mt5 = self._ensure_mt5_session()
            cache_age = time.time() - self._cache_timestamp
            if not self.assets_cache or cache_age > 300:
                assets = self._bootstrap_asset_catalog(mt5)
                self._cache_timestamp = time.time()
                return assets
            self._refresh_asset_prices(mt5)
            return sorted(self.assets_cache.values(), key=_exness_sort_key)

    def _bootstrap_asset_catalog(self, mt5: Any) -> list[AssetInfo]:
        symbols = list(mt5.symbols_get() or [])
        assets: list[AssetInfo] = []
        for info in symbols:
            name = str(getattr(info, "name", "") or "").strip()
            if not name:
                continue
            with suppress(Exception):
                mt5.symbol_select(name, True)
            path_text = str(getattr(info, "path", "") or "")
            description = str(getattr(info, "description", "") or "")
            category = _classify_exness_symbol(name, path_text, description)
            tick = mt5.symbol_info_tick(name)
            last_price = _extract_tick_price(tick)
            trade_mode = int(getattr(info, "trade_mode", 0) or 0)
            visible = bool(getattr(info, "visible", False))
            assets.append(
                AssetInfo(
                    symbol=name,
                    payout=0.0,
                    is_open=bool(last_price > 0 or visible or trade_mode != 0),
                    category=category,
                    display_name=_format_exness_display_name(name, description, category),
                    last_price=last_price,
                    feed_status="live" if last_price > 0 else "warming",
                )
            )
        if not assets:
            return default_exness_assets()
        assets.sort(key=_exness_sort_key)
        self.assets_cache = {asset.symbol: asset for asset in assets}
        self._catalog_symbols = [asset.symbol for asset in assets]
        self._catalog_cursor = 0
        return assets

    def _refresh_asset_prices(self, mt5: Any) -> None:
        if not self._catalog_symbols:
            self._catalog_symbols = list(self.assets_cache)
        if not self._catalog_symbols:
            return
        chunk_size = 80
        start = self._catalog_cursor % len(self._catalog_symbols)
        end = start + min(chunk_size, len(self._catalog_symbols))
        symbols = self._catalog_symbols[start:end]
        if end > len(self._catalog_symbols):
            symbols += self._catalog_symbols[: end - len(self._catalog_symbols)]
        self._catalog_cursor = (start + chunk_size) % max(1, len(self._catalog_symbols))
        selected = self._resolve_symbol_name(self.selected_asset)
        if selected and selected not in symbols:
            symbols.append(selected)
        for symbol in dict.fromkeys(symbols):
            asset = self.assets_cache.get(symbol)
            if asset is None:
                continue
            tick = mt5.symbol_info_tick(symbol)
            last_price = _extract_tick_price(tick)
            if last_price > 0:
                asset.last_price = last_price
                asset.feed_status = "live"
                asset.is_open = True
            elif asset.last_price <= 0:
                asset.feed_status = "warming"

    async def fetch_balance(self) -> float:
        balance = await asyncio.to_thread(self._fetch_balance_sync)
        self.last_balance = balance
        return balance

    def _fetch_balance_sync(self) -> float:
        with self._mt5_lock:
            mt5 = self._ensure_mt5_session()
            account = mt5.account_info()
            if account is None:
                raise RuntimeError(f"MetaTrader5 account_info failed: {mt5.last_error()}")
            return float(getattr(account, "balance", 0.0) or 0.0)

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        return await asyncio.to_thread(self._fetch_candles_sync, asset, period_seconds, count)

    def _fetch_candles_sync(self, asset: str, period_seconds: int, count: int) -> list[Candle]:
        with self._mt5_lock:
            mt5 = self._ensure_mt5_session()
            symbol = self._resolve_symbol_name(asset)
            mt5.symbol_select(symbol, True)
            timeframe = self._timeframe_value(mt5, period_seconds)
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None:
                raise RuntimeError(f"MetaTrader5 copy_rates_from_pos failed: {mt5.last_error()}")
            candles = [
                Candle(
                    timestamp=int(rate["time"]),
                    open=float(rate["open"]),
                    high=float(rate["high"]),
                    low=float(rate["low"]),
                    close=float(rate["close"]),
                    volume=float(rate["tick_volume"]),
                )
                for rate in rates
            ]
            if candles:
                self.assets_cache[symbol] = AssetInfo(
                    symbol=symbol,
                    payout=0.0,
                    is_open=True,
                    category=self.assets_cache.get(symbol).category if symbol in self.assets_cache else "forex",
                    display_name=self.assets_cache.get(symbol).display_name if symbol in self.assets_cache else _format_exness_display_name(symbol, "", "forex"),
                    last_price=float(candles[-1].close),
                    feed_status="live",
                )
            return candles

    def _timeframe_value(self, mt5: Any, period_seconds: int) -> int:
        if period_seconds <= 60:
            return int(getattr(mt5, "TIMEFRAME_M1"))
        if period_seconds <= 120 and hasattr(mt5, "TIMEFRAME_M2"):
            return int(getattr(mt5, "TIMEFRAME_M2"))
        if period_seconds <= 300:
            return int(getattr(mt5, "TIMEFRAME_M5"))
        if period_seconds <= 900:
            return int(getattr(mt5, "TIMEFRAME_M15"))
        return int(getattr(mt5, "TIMEFRAME_M30", getattr(mt5, "TIMEFRAME_M15")))

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        return await asyncio.to_thread(self._place_trade_sync, asset, action, amount, duration)

    def _place_trade_sync(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        with self._mt5_lock:
            mt5 = self._ensure_mt5_session()
            symbol = self._resolve_symbol_name(asset)
            mt5.symbol_select(symbol, True)
            symbol_info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if symbol_info is None or tick is None:
                raise RuntimeError(f"MetaTrader5 could not fetch symbol info for {symbol}.")
            direction = action.upper()
            order_type = mt5.ORDER_TYPE_BUY if direction == "CALL" else mt5.ORDER_TYPE_SELL
            price = float(getattr(tick, "ask", 0.0) if order_type == mt5.ORDER_TYPE_BUY else getattr(tick, "bid", 0.0))
            point = float(getattr(symbol_info, "point", 0.0001) or 0.0001)
            stop_distance = max(point * 150, price * 0.0015)
            stop_loss = price - stop_distance if direction == "CALL" else price + stop_distance
            take_profit = price + stop_distance * 1.5 if direction == "CALL" else price - stop_distance * 1.5
            risk_amount = max(1.0, float(self.last_balance or 0.0) * 0.01)
            tick_size = float(getattr(symbol_info, "trade_tick_size", 0.0) or point or 0.0001)
            tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0)
            if tick_value > 0 and tick_size > 0:
                cash_risk_per_lot = max((abs(price - stop_loss) / tick_size) * tick_value, 0.01)
            else:
                cash_risk_per_lot = max(abs(price - stop_loss) / max(point, 0.0001), 0.01)
            raw_lot = risk_amount / cash_risk_per_lot
            lot_size = _normalize_mt5_volume(raw_lot, symbol_info)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot_size),
                "type": order_type,
                "price": price,
                "sl": float(stop_loss),
                "tp": float(take_profit),
                "deviation": 20,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": getattr(mt5, "ORDER_FILLING_IOC", getattr(mt5, "ORDER_FILLING_RETURN", 0)),
                "comment": "Eternal Apex Engine",
            }
            result = mt5.order_send(request)
            if result is None:
                raise RuntimeError(f"MetaTrader5 order_send failed: {mt5.last_error()}")
            retcode = int(getattr(result, "retcode", 0) or 0)
            accepted = retcode in {
                int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
                int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
            }
            if not accepted:
                raise RuntimeError(f"MetaTrader5 rejected the order with retcode {retcode}.")
            return TradeTicket(
                id=str(getattr(result, "order", "") or getattr(result, "deal", "") or uuid.uuid4().hex[:10]),
                asset=symbol,
                action=direction,
                amount=float(amount),
                duration=int(duration),
                opened_at=time.time(),
                expiry_time=time.time() + duration,
                estimated_payout=0.0,
                is_demo=self.profile.account_mode.upper() != "REAL",
                accepted=True,
                raw={
                    "provider": self.name,
                    "backend_slug": "exness",
                    "entry_price": price,
                    "lot_size": lot_size,
                    "retcode": retcode,
                },
            )

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        await asyncio.sleep(min(max(int(ticket.duration or 60), 1), 8))
        candles = await self.fetch_candles(ticket.asset, 60, count=4)
        result_price = float(candles[-1].close) if candles else float(ticket.raw.get("entry_price", 0.0) or 0.0)
        entry_price = float(ticket.raw.get("entry_price", 0.0) or 0.0)
        ticket.result = result_price >= entry_price if ticket.action.upper() == "CALL" else result_price <= entry_price
        ticket.profit = 0.0
        ticket.raw["result_price"] = result_price
        return ticket

    def set_selected_asset(self, asset: str, period_seconds: int | None = None) -> None:
        normalized = self._resolve_symbol_name(asset)
        if normalized:
            self.selected_asset = normalized
            self.profile.selected_asset = normalized

    def _resolve_symbol_name(self, asset: str) -> str:
        requested = str(asset or "").strip().replace("_otc", "")
        if not requested:
            return str(self.selected_asset or self.profile.selected_asset or "EURUSD").replace("_otc", "")
        if requested in self.assets_cache:
            return requested
        upper = requested.upper()
        for symbol, info in self.assets_cache.items():
            if symbol.upper() == upper:
                return symbol
            if info.display_name and info.display_name.upper() == upper:
                return symbol
        return requested


class PocketOptionPlaywrightBackend(TradingBackend):
    name = "Pocket Option"
    MAX_TICK_HISTORY_PER_SYMBOL = 900

    def __init__(self) -> None:
        self.profile = ConnectionProfile()
        self.connected = False
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.selected_asset = ""
        self.assets_cache: dict[str, AssetInfo] = {}
        self.tick_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.balance = 0.0

    def _evict_tick_history(self) -> None:
        max_size = self.MAX_TICK_HISTORY_PER_SYMBOL
        for symbol, ticks in self.tick_history.items():
            if len(ticks) > max_size:
                self.tick_history[symbol] = ticks[-max_size:]

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        self.profile = replace(profile)
        if not (self.profile.pocket_option_email.strip() and self.profile.pocket_option_password):
            raise ValueError("Pocket Option email and password are required.")
        from playwright.async_api import async_playwright
        from eternal_quotex_bot.broker_adapters import _stealth_context

        self.playwright = await async_playwright().start()
        self.browser, self.context = await _stealth_context(self.playwright.chromium, headless=bool(self.profile.headless))
        self.page = await self.context.new_page()
        await self.page.goto(self.profile.pocket_option_url or "https://pocketoption.com", wait_until="domcontentloaded", timeout=90_000)
        await self._attempt_login()
        await self._ensure_terminal_ready()
        self.selected_asset = _normalize_otc_symbol(self.profile.selected_asset) or DEFAULT_POCKET_SYMBOLS[0]
        await self._sample_price(self.selected_asset, samples=8)
        if not self.tick_history.get(self.selected_asset):
            current_price = await self._extract_price()
            if current_price <= 0:
                raise RuntimeError("Pocket Option reached the browser page, but the trading terminal did not expose a live price feed.")
            self.tick_history[self.selected_asset].append((time.time(), current_price))
            self._evict_tick_history()
        self.balance = await self._scrape_balance()
        self.connected = True
        return AccountSnapshot(balance=self.balance, mode=self.profile.account_mode.upper(), backend_name=self.name)

    async def disconnect(self) -> None:
        self.connected = False
        with suppress(Exception):
            if self.context is not None:
                await self.context.close()
        with suppress(Exception):
            if self.browser is not None:
                await self.browser.close()
        with suppress(Exception):
            if self.playwright is not None:
                await self.playwright.stop()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def fetch_assets(self) -> list[AssetInfo]:
        assets = await self._scrape_assets()
        if not assets:
            assets = default_pocket_option_assets()
        self.assets_cache = {asset.symbol: asset for asset in assets}
        return assets

    async def fetch_balance(self) -> float:
        self.balance = await self._scrape_balance()
        return self.balance

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        symbol = _normalize_otc_symbol(asset) or self.selected_asset or DEFAULT_POCKET_SYMBOLS[0]
        await self._select_asset(symbol)
        await self._sample_price(symbol, samples=10)
        candles = _build_tick_candles(self.tick_history.get(symbol, []), max(60, int(period_seconds or 60)), count=count)
        if not candles:
            raise RuntimeError(f"Pocket Option did not return a price feed for {symbol}.")
        last_price = float(candles[-1].close)
        existing = self.assets_cache.get(symbol)
        self.assets_cache[symbol] = AssetInfo(
            symbol=symbol,
            payout=float(existing.payout if existing is not None else 0.0),
            is_open=True,
            category="pocket_option",
            last_price=last_price,
            feed_status="live",
        )
        return candles

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        symbol = _normalize_otc_symbol(asset) or self.selected_asset or DEFAULT_POCKET_SYMBOLS[0]
        await self._select_asset(symbol)
        entry_price = await self._extract_price()
        button_ok = await self._click_trade_button(action)
        if not button_ok:
            raise RuntimeError("Pocket Option trade submission failed. The Higher/Lower button was not confirmed.")
        return TradeTicket(
            id=uuid.uuid4().hex[:10],
            asset=symbol,
            action=action.upper(),
            amount=float(amount),
            duration=int(duration),
            opened_at=time.time(),
            expiry_time=time.time() + duration,
            estimated_payout=0.0,
            is_demo=self.profile.account_mode.upper() != "REAL",
            accepted=True,
            raw={
                "provider": self.name,
                "backend_slug": "pocket_option",
                "entry_price": float(entry_price or 0.0),
            },
        )

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        await asyncio.sleep(min(max(int(ticket.duration or 60), 1), 8))
        await self._sample_price(ticket.asset, samples=6)
        candles = _build_tick_candles(self.tick_history.get(ticket.asset, []), 60, count=4)
        result_price = float(candles[-1].close) if candles else float(ticket.raw.get("entry_price", 0.0) or 0.0)
        entry_price = float(ticket.raw.get("entry_price", 0.0) or 0.0)
        ticket.result = result_price >= entry_price if ticket.action.upper() == "CALL" else result_price <= entry_price
        ticket.profit = 0.0
        ticket.raw["result_price"] = result_price
        return ticket

    def set_selected_asset(self, asset: str, period_seconds: int | None = None) -> None:
        normalized = _normalize_otc_symbol(asset)
        if normalized:
            self.selected_asset = normalized

    async def _attempt_login(self) -> None:
        if self.page is None:
            return
        targets = _frame_targets(self.page)
        await _click_first_matching(
            targets,
            (
                "text=Log In",
                "text=Login",
                "[role='tab']:has-text('Log In')",
                "[role='tab']:has-text('Login')",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "a:has-text('Log In')",
                "a:has-text('Login')",
            ),
            timeout=2_000,
        )
        await self.page.wait_for_timeout(500)
        targets = _frame_targets(self.page)
        await _fill_first_matching(
            targets,
            (
                "input[type='email']",
                "input[name='email']",
                "input[autocomplete='username']",
            ),
            self.profile.pocket_option_email.strip(),
        )
        await _fill_first_matching(
            targets,
            (
                "input[type='password']",
                "input[name='password']",
                "input[autocomplete='current-password']",
            ),
            self.profile.pocket_option_password,
        )
        await _click_first_matching(
            targets,
            (
                "button:has-text('Sign in')",
                "button:has-text('Log in')",
                "button:has-text('Login')",
                "[type='submit']",
            ),
            timeout=3_000,
        )
        await self.page.wait_for_timeout(1_600)

    def _terminal_urls(self) -> list[str]:
        raw_url = self.profile.pocket_option_url or "https://pocketoption.com"
        parsed = urlsplit(raw_url)
        base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'pocketoption.com'}"
        if self.profile.account_mode.upper() == "REAL":
            return [
                f"{base}/en/cabinet/quick-high-low/",
                f"{base}/cabinet/quick-high-low/",
            ]
        return [
            f"{base}/en/cabinet/demo-quick-high-low/",
            f"{base}/cabinet/demo-quick-high-low/",
            f"{base}/en/cabinet/quick-high-low/",
        ]

    async def _is_terminal_ready(self) -> bool:
        if self.page is None:
            return False
        current_url = str(self.page.url or "").lower()
        if "quick-high-low" in current_url or "/cabinet/" in current_url:
            return True
        targets = _frame_targets(self.page)
        readiness_selectors = (
            "button:has-text('Higher')",
            "button:has-text('Lower')",
            "button:has-text('Up')",
            "button:has-text('Down')",
            "[class*='chart']",
            "canvas",
        )
        for target in targets:
            for selector in readiness_selectors:
                if await _count_locator(target, selector):
                    return True
        return False

    async def _ensure_terminal_ready(self) -> None:
        if self.page is None:
            return
        if await self._is_terminal_ready():
            return
        for selector in (
            "a:has-text('Quick start')",
            "button:has-text('Quick start')",
            "a:has-text('Start trading')",
            "button:has-text('Start trading')",
        ):
            try:
                target = self.page.locator(selector).first
                if await target.count():
                    await target.click(timeout=3_000)
                    await self.page.wait_for_timeout(2_000)
                    if await self._is_terminal_ready():
                        return
            except Exception:
                continue
        for url in self._terminal_urls():
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await self.page.wait_for_timeout(2_000)
                if await self._is_terminal_ready():
                    return
            except Exception:
                continue
        raise RuntimeError("Pocket Option login stayed on the public site and never reached the trading terminal.")

    async def _scrape_balance(self) -> float:
        if self.page is None:
            return 0.0
        script = """
        () => {
          const selectors = ['[data-role*="balance"]', '[class*="balance"]', '[data-test*="balance"]', '.balance'];
          for (const selector of selectors) {
            for (const node of Array.from(document.querySelectorAll(selector))) {
              const text = String(node.textContent || '').replace(/,/g, ' ');
              const match = text.match(/-?\\d+(?:\\.\\d+)?/);
              if (match) return match[0];
            }
          }
          return '0';
        }
        """
        try:
            value = await self.page.evaluate(script)
            return float(str(value or "0").strip())
        except Exception:
            return 0.0

    async def _scrape_assets(self) -> list[AssetInfo]:
        if self.page is None:
            return []
        script = """
        () => {
          const text = document.body ? String(document.body.innerText || '') : '';
          const matches = Array.from(text.matchAll(/[A-Z]{3}\\/[A-Z]{3}\\s*\\(OTC\\)/g)).map((match) => match[0]);
          const unique = [];
          for (const match of matches) {
            const cleaned = match.replace(/\\s+/g, ' ').trim();
            if (!unique.includes(cleaned)) unique.push(cleaned);
            if (unique.length >= 24) break;
          }
          return unique;
        }
        """
        labels = []
        for target in _frame_targets(self.page):
            try:
                payload = await target.evaluate(script)
            except Exception:
                continue
            if isinstance(payload, list) and payload:
                labels.extend(payload)
        assets: list[AssetInfo] = []
        for label in labels or []:
            symbol = _normalize_otc_symbol(label)
            if not symbol:
                continue
            existing = self.assets_cache.get(symbol)
            assets.append(
                AssetInfo(
                    symbol=symbol,
                    payout=float(existing.payout if existing is not None else 0.0),
                    is_open=True,
                    category="pocket_option",
                    last_price=float(existing.last_price if existing is not None else 0.0),
                    feed_status="live" if existing is not None and existing.last_price > 0 else "warming",
                )
            )
        return assets

    async def _select_asset(self, symbol: str) -> None:
        if self.page is None:
            return
        normalized = _normalize_otc_symbol(symbol)
        if not normalized or normalized == self.selected_asset:
            return
        await self._ensure_terminal_ready()
        display = _display_symbol(normalized)
        for target in _frame_targets(self.page):
            for selector in (
                "button:has-text('{label}')",
                "[role='button']:has-text('{label}')",
                "div:has-text('{label}')",
                "span:has-text('{label}')",
            ):
                try:
                    node = target.locator(selector.format(label=display)).first
                    if await node.count():
                        await node.click(timeout=2_000)
                        self.selected_asset = normalized
                        await self.page.wait_for_timeout(800)
                        return
                except Exception:
                    continue
        self.selected_asset = normalized

    async def _extract_price(self) -> float:
        if self.page is None:
            return 0.0
        script = """
        () => {
          const selectors = ['[data-role*="price"]','[data-test*="price"]','[class*="price"]','[class*="quote"]','.current-price','.asset-price'];
          const candidates = [];
          for (const selector of selectors) {
            for (const node of Array.from(document.querySelectorAll(selector))) {
              const text = String(node.textContent || '').replace(/,/g, '');
              const match = text.match(/-?\\d+(?:\\.\\d+)?/);
              if (!match) continue;
              const value = Number(match[0]);
              if (Number.isFinite(value) && value > 0.00001 && value < 1000000) candidates.push(value);
            }
          }
          if (candidates.length) return candidates[candidates.length - 1];
          const bodyText = document.body ? String(document.body.innerText || '').replace(/,/g, '') : '';
          const fallback = bodyText.match(/\\b\\d{1,4}(?:\\.\\d{2,6})\\b/g) || [];
          const values = fallback.map((item) => Number(item)).filter((value) => Number.isFinite(value) && value > 0.00001 && value < 1000000);
          return values.length ? values[values.length - 1] : 0;
        }
        """
        for target in _frame_targets(self.page):
            try:
                value = await target.evaluate(script)
            except Exception:
                continue
            try:
                numeric = float(value or 0.0)
            except Exception:
                numeric = 0.0
            if numeric > 0:
                return numeric
        return 0.0

    async def _sample_price(self, symbol: str, samples: int = 6) -> None:
        if self.page is None:
            return
        await self._ensure_terminal_ready()
        for _ in range(max(1, samples)):
            price = await self._extract_price()
            if price > 0:
                now = time.time()
                ticks = self.tick_history[symbol]
                ticks.append((now, price))
                self.tick_history[symbol] = ticks[-900:]
                existing = self.assets_cache.get(symbol) or AssetInfo(symbol=symbol, payout=0.0, is_open=True, category="pocket_option")
                self.assets_cache[symbol] = replace(
                    existing,
                    last_price=price,
                    feed_status="live",
                    countdown_updated_at=now,
                )
            await self.page.wait_for_timeout(180)

    async def _click_trade_button(self, action: str) -> bool:
        if self.page is None:
            return False
        await self._ensure_terminal_ready()
        label = "Higher" if action.upper() == "CALL" else "Lower"
        alt_label = "Up" if action.upper() == "CALL" else "Down"
        selectors = (
            f"button:has-text('{label}')",
            f"button:has-text('{alt_label}')",
            f"[role='button']:has-text('{label}')",
            f"[role='button']:has-text('{alt_label}')",
        )
        if await _click_first_matching(_frame_targets(self.page), selectors, timeout=2_000):
            return True
        return False


class IQOptionPlaywrightBackend(PocketOptionPlaywrightBackend):
    name = "IQ Option"

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        self.profile = replace(profile)
        if not (self.profile.pocket_option_email.strip() and self.profile.pocket_option_password):
            raise ValueError("IQ Option email and password are required.")
        from playwright.async_api import async_playwright
        from eternal_quotex_bot.broker_adapters import _stealth_context

        self.playwright = await async_playwright().start()
        self.browser, self.context = await _stealth_context(self.playwright.chromium, headless=bool(self.profile.headless))
        self.page = await self.context.new_page()
        await self.page.goto(self.profile.pocket_option_url or "https://iqoption.com/en/login", wait_until="domcontentloaded", timeout=90_000)
        await self._attempt_login()
        await self._ensure_terminal_ready()
        self.selected_asset = _normalize_otc_symbol(self.profile.selected_asset) or DEFAULT_POCKET_SYMBOLS[0]
        await self._sample_price(self.selected_asset, samples=8)
        if not self.tick_history.get(self.selected_asset):
            current_price = await self._extract_price()
            if current_price <= 0:
                raise RuntimeError("IQ Option reached the browser page, but the trading terminal did not expose a live price feed.")
            self.tick_history[self.selected_asset].append((time.time(), current_price))
            self._evict_tick_history()
        self.balance = await self._scrape_balance()
        self.connected = True
        return AccountSnapshot(balance=self.balance, mode=self.profile.account_mode.upper(), backend_name=self.name)

    async def _attempt_login(self) -> None:
        if self.page is None:
            return
        targets = _frame_targets(self.page)
        await _click_first_matching(
            targets,
            (
                "text=Log In",
                "text=Login",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "a:has-text('Log In')",
                "a:has-text('Login')",
            ),
            timeout=2_000,
        )
        await self.page.wait_for_timeout(500)
        targets = _frame_targets(self.page)
        await _fill_first_matching(
            targets,
            (
                "input[type='email']",
                "input[name='email']",
                "input[name='identifier']",
                "input[autocomplete='username']",
            ),
            self.profile.pocket_option_email.strip(),
        )
        await _fill_first_matching(
            targets,
            (
                "input[type='password']",
                "input[name='password']",
                "input[autocomplete='current-password']",
            ),
            self.profile.pocket_option_password,
        )
        await _click_first_matching(
            targets,
            (
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "button:has-text('Sign in')",
                "[type='submit']",
            ),
            timeout=3_000,
        )
        await self.page.wait_for_timeout(1_800)

    def _terminal_urls(self) -> list[str]:
        raw_url = self.profile.pocket_option_url or "https://iqoption.com/en/login"
        parsed = urlsplit(raw_url)
        base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'iqoption.com'}"
        return [
            f"{base}/traderoom",
            f"{base}/en/traderoom",
        ]

    async def _is_terminal_ready(self) -> bool:
        if self.page is None:
            return False
        current_url = str(self.page.url or "").lower()
        if "traderoom" in current_url:
            return True
        targets = _frame_targets(self.page)
        readiness_selectors = (
            "button:has-text('Higher')",
            "button:has-text('Lower')",
            "button:has-text('Buy')",
            "button:has-text('Sell')",
            "[class*='chart']",
            "canvas",
        )
        for target in targets:
            for selector in readiness_selectors:
                if await _count_locator(target, selector):
                    return True
        return False

    async def _ensure_terminal_ready(self) -> None:
        if self.page is None:
            return
        if await self._is_terminal_ready():
            return
        for selector in (
            "a:has-text('Trade now')",
            "button:has-text('Trade now')",
            "a:has-text('Open trading room')",
            "button:has-text('Open trading room')",
            "a:has-text('Start trading')",
            "button:has-text('Start trading')",
        ):
            try:
                target = self.page.locator(selector).first
                if await target.count():
                    await target.click(timeout=3_000)
                    await self.page.wait_for_timeout(2_000)
                    if await self._is_terminal_ready():
                        return
            except Exception:
                continue
        for url in self._terminal_urls():
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await self.page.wait_for_timeout(2_000)
                if await self._is_terminal_ready():
                    return
            except Exception:
                continue
        raise RuntimeError("IQ Option login stayed on the public site and never reached the trading terminal.")

    async def _scrape_assets(self) -> list[AssetInfo]:
        assets = await super()._scrape_assets()
        return [replace(asset, category="iq_option") for asset in assets]

    async def fetch_assets(self) -> list[AssetInfo]:
        assets = await self._scrape_assets()
        if not assets:
            assets = default_iq_option_assets()
        self.assets_cache = {asset.symbol: asset for asset in assets}
        return assets

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        candles = await super().fetch_candles(asset, period_seconds, count=count)
        symbol = _normalize_otc_symbol(asset) or self.selected_asset or DEFAULT_POCKET_SYMBOLS[0]
        existing = self.assets_cache.get(symbol)
        if existing is not None:
            self.assets_cache[symbol] = replace(existing, category="iq_option")
        return candles

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        ticket = await super().place_trade(asset, action, amount, duration)
        ticket.raw["provider"] = self.name
        ticket.raw["backend_slug"] = "iq_option"
        return ticket

    async def _click_trade_button(self, action: str) -> bool:
        if self.page is None:
            return False
        await self._ensure_terminal_ready()
        label = "Higher" if action.upper() == "CALL" else "Lower"
        alt_label = "Buy" if action.upper() == "CALL" else "Sell"
        selectors = (
            f"button:has-text('{label}')",
            f"button:has-text('{alt_label}')",
            f"[role='button']:has-text('{label}')",
            f"[role='button']:has-text('{alt_label}')",
        )
        if await _click_first_matching(_frame_targets(self.page), selectors, timeout=2_000):
            return True
        return False


class MultiBrokerBackend(TradingBackend):
    name = "Multi Broker Feed"

    def __init__(self, backends: dict[str, TradingBackend], *, primary_broker: str) -> None:
        self.backends = dict(backends)
        self.primary_broker = str(primary_broker or "").strip().lower() or next(iter(self.backends), "quotex")
        self.asset_sources: dict[str, list[str]] = defaultdict(list)
        self.ticket_backends: dict[str, str] = {}
        self.profile = ConnectionProfile()
        self.connected = False

    @classmethod
    def from_profile(cls, profile: ConnectionProfile, *, quotex_factory, iq_option_factory, exness_factory):
        enabled = [
            item.strip().lower()
            for item in str(profile.enabled_brokers or "").split(",")
            if item.strip()
        ]
        enabled = [name for name in enabled if name in {"quotex", "iq_option", "exness"}]
        if profile.use_all_brokers or not enabled:
            enabled = enabled or ["quotex", "iq_option", "exness"]
        backends: dict[str, TradingBackend] = {}
        for broker in enabled:
            if broker == "quotex":
                # Pass log_callback if factory accepts it
                try:
                    backends[broker] = quotex_factory(log_callback=lambda level, msg: None)
                except TypeError:
                    backends[broker] = quotex_factory()
            elif broker == "iq_option":
                backends[broker] = iq_option_factory()
            elif broker == "exness":
                backends[broker] = exness_factory()
        if not backends:
            try:
                backends["quotex"] = quotex_factory(log_callback=lambda level, msg: None)
            except TypeError:
                backends["quotex"] = quotex_factory()
        return cls(backends, primary_broker=profile.primary_broker or next(iter(backends)))

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        self.profile = replace(profile)
        snapshots: list[AccountSnapshot] = []
        errors: list[str] = []
        for slug, backend in self.backends.items():
            try:
                snapshots.append(await backend.connect(profile))
            except Exception as error:
                errors.append(f"{slug}: {error}")
        if not snapshots:
            raise RuntimeError("No selected broker could connect. " + " | ".join(errors))
        self.connected = True
        names = ", ".join(snapshot.backend_name for snapshot in snapshots)
        return AccountSnapshot(
            balance=sum(float(snapshot.balance or 0.0) for snapshot in snapshots),
            mode=profile.account_mode.upper(),
            backend_name=f"{self.name}: {names}",
        )

    async def disconnect(self) -> None:
        for backend in self.backends.values():
            with suppress(Exception):
                await backend.disconnect()
        self.connected = False

    async def fetch_assets(self) -> list[AssetInfo]:
        merged: dict[str, AssetInfo] = {}
        self.asset_sources.clear()
        for slug, backend in self.backends.items():
            with suppress(Exception):
                assets = await backend.fetch_assets()
                for asset in assets:
                    current = merged.get(asset.symbol)
                    self.asset_sources[asset.symbol].append(slug)
                    if current is None:
                        merged[asset.symbol] = replace(asset, category=f"multi:{slug}")
                        continue
                    if asset.last_price > 0:
                        current.last_price = asset.last_price
                        current.feed_status = asset.feed_status
                    current.is_open = current.is_open or asset.is_open
                    current.payout = max(current.payout, asset.payout)
                    if asset.countdown_seconds is not None:
                        current.countdown_seconds = asset.countdown_seconds
                        current.countdown_updated_at = asset.countdown_updated_at
                    current.category = "multi:" + ",".join(sorted(set(self.asset_sources[asset.symbol])))
        return sorted(merged.values(), key=lambda asset: asset.symbol)

    async def fetch_balance(self) -> float:
        total = 0.0
        for backend in self.backends.values():
            with suppress(Exception):
                total += float(await backend.fetch_balance() or 0.0)
        return total

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        ordered = [self.primary_broker] + [slug for slug in self.backends if slug != self.primary_broker]
        last_error: Exception | None = None
        for slug in ordered:
            backend = self.backends.get(slug)
            if backend is None:
                continue
            if hasattr(backend, "set_selected_asset"):
                with suppress(Exception):
                    backend.set_selected_asset(asset, period_seconds)
            try:
                candles = await backend.fetch_candles(asset, period_seconds, count=count)
                if candles:
                    return candles
            except Exception as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"No selected broker returned candles for {asset}.")

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        backend_slug = self.primary_broker if self.primary_broker in self.backends else next(iter(self.backends))
        backend = self.backends[backend_slug]
        if hasattr(backend, "set_selected_asset"):
            with suppress(Exception):
                backend.set_selected_asset(asset, self.profile.candle_period)
        ticket = await backend.place_trade(asset, action, amount, duration)
        self.ticket_backends[ticket.id] = backend_slug
        ticket.raw["backend_slug"] = backend_slug
        ticket.raw["provider"] = backend.name
        return ticket

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        backend_slug = self.ticket_backends.get(ticket.id) or str(ticket.raw.get("backend_slug") or self.primary_broker)
        backend = self.backends.get(backend_slug)
        if backend is None:
            raise RuntimeError("The broker used for this ticket is no longer connected.")
        return await backend.check_trade_result(ticket)

    def set_selected_asset(self, asset: str, period_seconds: int | None = None) -> None:
        for backend in self.backends.values():
            if hasattr(backend, "set_selected_asset"):
                with suppress(Exception):
                    backend.set_selected_asset(asset, period_seconds)
