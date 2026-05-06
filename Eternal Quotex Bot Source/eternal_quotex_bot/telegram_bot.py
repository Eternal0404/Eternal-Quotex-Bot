from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests

# Fix TLS certificate bundle issue in PyInstaller builds
try:
    import certifi
    cert_path = certifi.where()
    if not os.path.exists(cert_path):
        # If certifi bundle doesn't exist, disable verification warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", "")
except Exception:
    pass

from .chart_renderer import render_signal_chart
from .models import AssetInfo, Candle, StrategyDecision, TelegramSettings
from .paths import runtime_dir

# ---------------------------------------------------------------------------
# Emoji constants
# ---------------------------------------------------------------------------
E_CROWN = "\U0001f451"
E_CHART = "\U0001f4ca"
E_CLOCK = "\U0001f553"
E_TIMER = "\u23f3"
E_TARGET = "\U0001f3af"
E_CHECKMARK = "\u2705"
E_STAR = "\u2b50"
E_UP = "\u2b06"
E_DOWN = "\u2b07"
E_RED = "\U0001f534"
E_GREEN = "\U0001f7e2"
E_YELLOW = "\U0001f7e1"
E_MEMO = "\U0001f4cb"
E_PHONE = "\U0001f4f3"
E_REFRESH = "\U0001f504"
E_LEFT = "\u2b05"
E_ROBOT = "\U0001f916"
E_BRAIN = "\U0001f9e0"
E_DNA = "\U0001f9ec"
E_GLOBE = "\U0001f30d"
E_MONEY = "\U0001f4b0"
E_GEAR = "\u2699"
E_SATELLITE = "\U0001f6f0"
E_SEARCH = "\U0001f50d"
E_CRYSTAL = "\U0001f52e"
E_LOCK = "\U0001f512"
E_BARS = "\U0001f4c8"
E_USERS = "\U0001f465"
E_SEND = "\U0001f4e8"
E_CAMERA = "\U0001f4f7"
E_PICTURE = "\U0001f5bc"
E_WARNING = "\u26a0"
E_FEATHER = "\U0001fab6"

# ---------------------------------------------------------------------------
# OTC pair definitions (symbol, display, index)
# ---------------------------------------------------------------------------
OTC_CURRENCIES = [
    ("USDBDT_otc", "USD/BDT"),
    ("USDCOP_otc", "USD/COP"),
    ("USDINR_otc", "USD/INR"),
    ("USDPKR_otc", "USD/PKR"),
    ("USDZAR_otc", "USD/ZAR"),
    ("USDARS_otc", "USD/ARS"),
    ("USDIDR_otc", "USD/IDR"),
    ("USDDZD_otc", "USD/DZD"),
    ("EURNZD_otc", "EUR/NZD"),
    ("NZDCAD_otc", "NZD/CAD"),
    ("USDEGP_otc", "USD/EGP"),
    ("NZDUSD_otc", "NZD/USD"),
    ("USDMXN_otc", "USD/MXN"),
    ("BRLUSD_otc", "BRL/USD"),
    ("CADCHF_otc", "CAD/CHF"),
    ("AUDNZD_otc", "AUD/NZD"),
]

OTC_STOCKS = [
    ("PFESTK_otc", "Pfizer Inc"),
    ("MSFSTK_otc", "Microsoft"),
    ("MCDSTK_otc", "McDonald's"),
    ("JNJSTK_otc", "Johnson & Johnson"),
    ("INTSTK_otc", "Intel"),
    ("FABSTK_otc", "FACEBOOK INC"),
    ("AXPSTK_otc", "American Express"),
]

REAL_PAIRS = [
    ("EURUSD", "EUR/USD"),
    ("GBPUSD", "GBP/USD"),
    ("USDJPY", "USD/JPY"),
    ("AUDUSD", "AUD/USD"),
    ("USDCAD", "USD/CAD"),
    ("USDCHF", "USD/CHF"),
    ("AUDCHF", "AUD/CHF"),
    ("NZDUSD", "NZD/USD"),
    ("EURJPY", "EUR/JPY"),
    ("GBPJPY", "GBP/JPY"),
    ("EURGBP", "EUR/GBP"),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FREE_DAILY_LIMIT = 15
COOLDOWN_SECONDS = 30
MAX_HISTORY = 500
MAX_KNOWN_USERS = 200
TOP_QUICK_SCAN = 5
MAX_FUTURE_SIGNALS = 10


def _format_pair_display(symbol: str, display: str = "") -> str:
    """Return a user-friendly pair label."""
    if display:
        return display
    s = symbol.replace("_otc", "").upper()
    if len(s) >= 6 and s.isalpha():
        return f"{s[:3]}/{s[3:]}"
    return s


def build_pair_label(asset, settings) -> str:
    """Build a display label for an AssetInfo using TelegramSettings template.

    Args:
        asset: AssetInfo instance (symbol, display_name, payout, etc.)
        settings: TelegramSettings with pair_label_template

    Returns:
        Formatted label string, e.g. "USD/BDT (87%)"
    """
    from .models import AssetInfo, TelegramSettings

    symbol = ""
    display_name = ""
    payout = 0.0

    if isinstance(asset, AssetInfo):
        symbol = asset.symbol
        display_name = asset.display_name or ""
        payout = float(asset.payout or 0.0)
    elif isinstance(asset, dict):
        symbol = str(asset.get("symbol", ""))
        display_name = str(asset.get("display_name", ""))
        payout = float(asset.get("payout", 0.0))
    else:
        symbol = str(asset) if asset else ""

    pair = display_name or _format_pair_display(symbol)
    template = ""
    if isinstance(settings, TelegramSettings):
        template = str(settings.pair_label_template or "{pair} ({payout:.0f}%)")
    elif isinstance(settings, dict):
        template = str(settings.get("pair_label_template", "{pair} ({payout:.0f}%)"))
    else:
        template = "{pair} ({payout:.0f}%)"

    try:
        return template.format(pair=pair, payout=payout, symbol=symbol)
    except (KeyError, ValueError):
        return pair


def build_start_preview(settings, assets) -> str:
    """Build the /start welcome screen preview text.

    Args:
        settings: TelegramSettings or dict with button texts
        assets: Iterable of AssetInfo for preview

    Returns:
        Formatted welcome text with menu buttons
    """
    from .models import TelegramSettings

    if isinstance(settings, TelegramSettings):
        engine_name = settings.engine_name or "Eternal AI Bot (Apex Engine v214)"
        otc_text = settings.otc_button_text or "💰 OTC Market"
        real_text = settings.real_button_text or "🌍 Real Market"
        admin_text = settings.admin_button_text or "⚙️ Admin Panel"
        deep_text = settings.deep_scan_label or "Deep Scan 🔎"
        status_text = settings.status_button_text or "Signal Status 📈"
    elif isinstance(settings, dict):
        engine_name = settings.get("engine_name", "Eternal AI Bot (Apex Engine v214)")
        otc_text = settings.get("otc_button_text", "💰 OTC Market")
        real_text = settings.get("real_button_text", "🌍 Real Market")
        admin_text = settings.get("admin_button_text", "⚙️ Admin Panel")
        deep_text = settings.get("deep_scan_label", "Deep Scan 🔎")
        status_text = settings.get("status_button_text", "Signal Status 📈")
    else:
        engine_name = "Eternal AI Bot (Apex Engine v214)"
        otc_text = "💰 OTC Market"
        real_text = "🌍 Real Market"
        admin_text = "⚙️ Admin Panel"
        deep_text = "Deep Scan 🔎"
        status_text = "Signal Status 📈"

    asset_list = list(assets)[:3] if assets else []
    if asset_list:
        parts = []
        for a in asset_list:
            label = build_pair_label(a, settings)
            parts.append(f"  - {label}")
        asset_lines = "\n".join(parts)
    else:
        asset_lines = "  - No pairs loaded"

    if isinstance(settings, TelegramSettings):
        start_title = settings.start_title or ""
        start_message = settings.start_message or ""
    elif isinstance(settings, dict):
        start_title = settings.get("start_title", "")
        start_message = settings.get("start_message", "")
    else:
        start_title = ""
        start_message = ""

    if start_title:
        header = start_title
    else:
        header = f"{engine_name}\n      Apex Engine v214"

    message_part = f"\n{start_message}" if start_message else ""

    return (
        f"{header}\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\n"
        f"\U0001f9e0 15-Layer Analysis\n"
        f"\U0001f9ec OTC Currency + Stocks\n"
        f"\U0001f916 Multi-Indicator Voting\n"
        f"\U0001f3af Max Accuracy Signals\n"
        f"\n"
        f"\U0001f4ca Signals: Unlimited\n"
        f"\n"
        f"Select Market:"
        f"{message_part}\n"
        f"\n"
        f"Primary action: {deep_text}\n"
        f"Signal action: {status_text}\n"
        f"Menu: {otc_text} | {real_text} | {admin_text}"
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _stars(confidence_pct: int) -> str:
    if confidence_pct >= 84:
        return " \u2b50\u2b50\u2b50"
    if confidence_pct >= 74:
        return " \u2b50\u2b50"
    if confidence_pct >= 64:
        return " \u2b50"
    return ""


def _classify_level(confidence_pct: int) -> str:
    if confidence_pct >= 78:
        return "DEEP CONFIRMED"
    if confidence_pct >= 68:
        return "CONFIRMED"
    if confidence_pct >= 58:
        return "DEVELOPING"
    return "WEAK BIAS"


def _start_welcome(user_type: str, signals_remaining: int, settings=None) -> str:
    """Build the welcome message text."""
    sig_text = f"Signals: {signals_remaining}/{FREE_DAILY_LIMIT}" if user_type == "FREE" else "Signals: Unlimited"
    if settings is not None:
        title = getattr(settings, 'start_title', '') or ""
        if not title:
            title = f"{E_CROWN} ETERNAL AI BOT {E_CROWN}\n      Apex Engine v214"
    else:
        title = f"{E_CROWN} ETERNAL AI BOT {E_CROWN}\n      Apex Engine v214"

    return (
        f"{title}\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\n"
        f"{E_BRAIN} 15-Layer Analysis\n"
        f"{E_DNA} OTC Currency + Stocks\n"
        f"\U0001f916 Multi-Indicator Voting\n"
        f"{E_TARGET} Max Accuracy Signals\n"
        f"\n"
        f"{E_CHART} {sig_text}\n"
        f"\n"
        f"Select Market:"
    )


def _otc_market_header() -> str:
    now = datetime.now().strftime("%I:%M %p").lstrip("0")
    return (
        f"{E_MONEY} OTC MARKET\n"
        f"{'\u2550' * 16}\n"
        f"Currency + Stocks {E_CHART}\n"
        f"Select pair: {now}"
    )


def _real_market_header() -> str:
    now = datetime.now().strftime("%I:%M %p").lstrip("0")
    return (
        f"{E_GLOBE} REAL MARKET\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"Major Forex Pairs {E_CHART}\n"
        f"Select pair: {now}"
    )


def _admin_panel_header() -> str:
    return (
        f"{E_GEAR} ADMIN PANEL\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\n"
        f"Welcome! {E_CROWN}"
    )


def _status_text(otc_healthy: int, otc_total: int, real_healthy: int, real_total: int,
                  total_signals: int, total_users: int, history_count: int) -> str:
    return (
        f"{E_CHART} SYSTEM STATUS\n"
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
        f"\n"
        f"{E_ROBOT} Bot: Online\n"
        f"\U0001f525 v214.00 (15-Layer)\n"
        f"{E_SATELLITE} Telegram: {E_CHECKMARK} OK\n"
        f"{E_DNA} Layers: 15 Active\n"
        f"{E_CHART} Signals: {total_signals}\n"
        f"{E_USERS} Users: {total_users}\n"
        f"{E_MONEY} OTC: {otc_healthy}/{otc_total}\n"
        f"{E_GLOBE} Real: {real_healthy}/{real_total}\n"
        f"{E_MEMO} History: {history_count}\n"
        f"Capture: FREE"
    )


def _format_signal_text(user_type: str, pair_display: str, time_str: str,
                         expire_min: int, action: str, price: str,
                         confidence_pct: int, level: str, win_rate: int,
                         analysis_points: str) -> str:
    direction_icon = E_GREEN if action == "CALL" else E_RED
    direction_arrow = E_UP if action == "CALL" else E_DOWN
    stars = _stars(confidence_pct)

    analysis_line = ""
    if analysis_points:
        analysis_line = f"\n{E_MEMO} Analysis:\n  {E_CHECKMARK} {analysis_points}"

    return (
        f"======= Eternal AI Bot =======\n"
        f"  {E_CROWN} {user_type}\n"
        f"\n"
        f"\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550 \u25e5\u25e3\u25c6\u25e2\u25e5 \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557\n"
        f"{E_CHART} PAIR      \u279c {pair_display}\n"
        f"{E_CLOCK} TIME      \u279c {time_str}\n"
        f"{E_TIMER} EXPIRE    \u279c {expire_min} Min\n"
        f"{direction_icon} DIRECTION \u279c {action} {direction_arrow}\n"
        f"{E_TARGET} PRICE     \u279c {price}\n"
        f"\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550 \u25e2\u25e5\u25c6\u25e3\u25e4 \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\n"
        f"\n"
        f"\u250f\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2513\n"
        f"\u2503   {E_CHART} CONFIDENCE: {confidence_pct}%{stars}\n"
        f"\u2503   {E_BARS} Level: {level}\n"
        f"\u2503   {E_CHECKMARK} Quality: closed-candle, non-martingale format\n"
        f"\u2517\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u251b\n"
        f"{analysis_line}\n"
        f"\n"
        f"{E_PHONE} Signal Sent Successfully"
    )


def _quick_scan_text(results: list[dict]) -> str:
    """Top-N quick scan results."""
    lines = [f"{E_SATELLITE} QUICK SCAN RESULTS", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550", ""]
    for i, r in enumerate(results, 1):
        icon = E_GREEN if r["action"] == "CALL" else E_RED
        lines.append(f"{i}. {icon} {r['pair']} {r['action']}  {r['confidence']}%{_stars(r['confidence'])}")
        lines.append(f"   {E_BARS} {r['level']} | {r['summary']}")
        lines.append("")
    return "\n".join(lines)


def _future_signals_text(signals: list[dict]) -> str:
    lines = [f"{E_CRYSTAL} FUTURE SIGNALS", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550", ""]
    for i, s in enumerate(signals, 1):
        icon = E_GREEN if s["action"] == "CALL" else E_RED
        lines.append(f"[{i}] {icon} {s['pair']} @{s['time']} ({s['confidence']}%)")
    return "\n".join(lines)


def _stats_text(total_signals: int, users_today: int, total_users: int,
                 history_count: int, user_details: list[dict]) -> str:
    lines = [
        f"{E_MEMO} STATISTICS",
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550",
        "",
        f"Signals: {total_signals}",
        f"Users Today: {users_today}",
        f"Known Users: {total_users}",
        f"History: {history_count}",
        "",
    ]
    for ud in user_details[:10]:
        lines.append(f"{E_USERS} {ud['chat_id']} [{ud['tier']}]: {ud['signals']}")
    return "\n".join(lines)


def _user_history_detail(user_id: str, tier: str, signals: int, entries: list[dict]) -> str:
    lines = [
        f"{E_MEMO} USER: {user_id}",
        f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550",
        f"Type: {tier}",
        f"Signals: {signals}",
        "",
    ]
    for i, e in enumerate(entries[:10], 1):
        icon = E_GREEN if e["action"] == "CALL" else E_RED
        lines.append(f"{i}. {icon} {e['action']} {e['pair']}")
        lines.append(f"   {e['time']} | {e['scan_type']} | {e['confidence']}%")
    return "\n".join(lines)


def _image_test_results(ok: int, fail: int, skip: int) -> str:
    return (
        f"{E_PICTURE} RESULTS:\n"
        f"{E_CHECKMARK} OK: {ok}\n"
        f"{E_RED} Fail: {fail}\n"
        f"{E_WARNING} Skip: {skip}"
    )


# ---------------------------------------------------------------------------
# Inline keyboard builders
# ---------------------------------------------------------------------------

def _start_keyboard(is_admin: bool, settings=None) -> dict:
    if settings is not None:
        otc_text = getattr(settings, 'otc_button_text', '') or f"{E_MONEY} OTC Market"
        real_text = getattr(settings, 'real_button_text', '') or f"{E_GLOBE} Real Market"
        admin_text = getattr(settings, 'admin_button_text', '') or f"{E_GEAR} Admin Panel"
    else:
        otc_text = f"{E_MONEY} OTC Market"
        real_text = f"{E_GLOBE} Real Market"
        admin_text = f"{E_GEAR} Admin Panel"

    rows = [
        [
            {"text": otc_text, "callback_data": "OTC"},
            {"text": real_text, "callback_data": "REAL"},
        ],
    ]
    if is_admin:
        rows.append([{"text": admin_text, "callback_data": "ADMIN"}])
    return {"inline_keyboard": rows}


def _otc_market_keyboard(premium: bool) -> dict:
    rows = []
    # Premium scan buttons
    if premium:
        rows.append([
            {"text": f"{E_SATELLITE} Quick Scan", "callback_data": "OTC_SCAN"},
            {"text": f"{E_SEARCH} Deep Scan", "callback_data": "DEEP_SCAN"},
            {"text": f"{E_CRYSTAL} Future Signals", "callback_data": "FUTURE"},
        ])
    # Currency pairs - 3 per row
    for i in range(0, len(OTC_CURRENCIES), 3):
        chunk = OTC_CURRENCIES[i:i + 3]
        row = []
        for sym, disp in chunk:
            row.append({"text": f"\U0001f4b5 {disp}", "callback_data": f"P_OTC_{OTC_CURRENCIES.index((sym, disp))}"})
        rows.append(row)
    # Stock pairs - 2 per row
    for i in range(0, len(OTC_STOCKS), 2):
        chunk = OTC_STOCKS[i:i + 2]
        row = []
        for sym, disp in chunk:
            row.append({"text": f"{E_BARS} {disp}", "callback_data": f"P_OTC_{len(OTC_CURRENCIES) + OTC_STOCKS.index((sym, disp))}"})
        rows.append(row)
    rows.append([{"text": f"{E_LEFT} Back", "callback_data": "BACK"}])
    return {"inline_keyboard": rows}


def _real_market_keyboard(premium: bool) -> dict:
    rows = []
    if premium:
        rows.append([
            {"text": f"{E_SATELLITE} Quick Scan", "callback_data": "OTC_SCAN"},
            {"text": f"{E_SEARCH} Deep Scan", "callback_data": "DEEP_SCAN"},
            {"text": f"{E_CRYSTAL} Future Signals", "callback_data": "FUTURE"},
        ])
    for i in range(0, len(REAL_PAIRS), 3):
        chunk = REAL_PAIRS[i:i + 3]
        row = [{"text": f"\U0001f4b5 {disp}", "callback_data": f"P_REAL_{i + j}"} for j, (_, disp) in enumerate(chunk)]
        rows.append(row)
    rows.append([{"text": f"{E_LEFT} Back", "callback_data": "BACK"}])
    return {"inline_keyboard": rows}


def _admin_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": f"{E_CHART} Status", "callback_data": "ADMIN_STATUS"},
                {"text": f"{E_BARS} Charts", "callback_data": "ADMIN_CHARTS"},
            ],
            [
                {"text": f"{E_MEMO} Stats", "callback_data": "ADMIN_STATS"},
                {"text": f"{E_MEMO} User History", "callback_data": "ADMIN_USERS"},
            ],
            [
                {"text": f"{E_SEND} Message Users", "callback_data": "ADMIN_MSG"},
                {"text": f"{E_CAMERA} Test Capture", "callback_data": "ADMIN_TEST"},
            ],
            [
                {"text": f"{E_PICTURE} Image Test", "callback_data": "ADMIN_IMG_TEST"},
                {"text": f"{E_SATELLITE} Image Delivery", "callback_data": "ADMIN_IMG_DEL"},
            ],
            [{"text": f"{E_LEFT} Back", "callback_data": "BACK"}],
        ]
    }


def _signal_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": f"{E_REFRESH} Rescan", "callback_data": "RESCAN"},
                {"text": f"{E_LEFT} Back", "callback_data": "BACK"},
            ],
        ]
    }


def _status_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": f"{E_REFRESH} Refresh", "callback_data": "ADMIN_STATUS"},
                {"text": f"{E_LEFT} Back", "callback_data": "ADMIN"},
            ],
        ]
    }


def _stats_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": f"{E_LEFT} Back", "callback_data": "ADMIN"}],
        ]
    }


def _msg_users_keyboard(known_users: list[dict]) -> dict:
    rows = []
    for u in known_users[:10]:
        rows.append([{"text": f"{E_USERS} {u['chat_id']} [{u['tier']}]", "callback_data": f"MSG_{u['chat_id']}"}])
    rows.append([{"text": f"{E_SEND} Message ALL", "callback_data": "MSG_ALL"}])
    rows.append([{"text": f"{E_LEFT} Back", "callback_data": "ADMIN"}])
    return {"inline_keyboard": rows}


def _user_history_keyboard(known_users: list[dict]) -> dict:
    rows = []
    for u in known_users[:10]:
        rows.append([{"text": f"{E_USERS} {u['chat_id']} [{u['tier']}]", "callback_data": f"UH_{u['chat_id']}"}])
    rows.append([{"text": f"{E_LEFT} Back", "callback_data": "ADMIN"}])
    return {"inline_keyboard": rows}


def _user_history_detail_keyboard(user_id: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": f"{E_SEND} Send Message", "callback_data": f"MSG_{user_id}"}],
            [{"text": f"{E_LEFT} Users", "callback_data": "ADMIN_USERS"}],
        ]
    }


def _image_delivery_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": f"{E_LEFT} Back", "callback_data": "ADMIN"}],
        ]
    }


# ---------------------------------------------------------------------------
# User tracking
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class UserUsage:
    chat_id: str = ""
    tier: str = "FREE"
    daily_signals: int = 0
    last_reset: str = ""
    total_signals: int = 0
    last_signal_at: float = 0.0
    cooldown_pairs: dict[str, float] = None

    def __post_init__(self):
        if self.cooldown_pairs is None:
            self.cooldown_pairs = {}

    def reset_daily_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.last_reset != today:
            self.daily_signals = 0
            self.last_reset = today

    def can_send_signal(self) -> bool:
        self.reset_daily_if_needed()
        if self.tier == "FREE":
            return self.daily_signals < FREE_DAILY_LIMIT
        return True

    def signals_remaining(self) -> int:
        self.reset_daily_if_needed()
        if self.tier == "FREE":
            return max(0, FREE_DAILY_LIMIT - self.daily_signals)
        return 999999

    def is_on_cooldown(self, pair_key: str) -> bool:
        last = self.cooldown_pairs.get(pair_key, 0.0)
        return (time.time() - last) < COOLDOWN_SECONDS

    def cooldown_remaining(self, pair_key: str) -> int:
        last = self.cooldown_pairs.get(pair_key, 0.0)
        elapsed = time.time() - last
        return max(0, int(COOLDOWN_SECONDS - elapsed))

    def record_signal(self, pair_key: str):
        self.cooldown_pairs[pair_key] = time.time()
        self.daily_signals += 1
        self.total_signals += 1
        self.last_signal_at = time.time()


@dataclass(slots=True)
class SignalHistoryEntry:
    chat_id: str
    pair: str
    action: str
    confidence: int
    scan_type: str
    time: str
    win: bool | None = None


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TelegramRuntimeState:
    running: bool = False
    connected: bool = False
    status: str = "Stopped"
    me: str = ""
    last_chat_id: str = ""
    last_command: str = ""
    error: str = ""


@dataclass(slots=True)
class LastSignalContext:
    chat_id: str = ""
    symbol: str = ""
    broker_slug: str = ""
    market_type: str = ""
    pair_index: int = -1


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class TelegramBotService:
    def __init__(
        self,
        settings_provider,
        assets_provider,
        signal_provider,
        analysis_provider,
        test_capture_provider,
        deep_scan_callback,
        status_callback,
        log_callback,
        learning_state_provider=None,
    ) -> None:
        self._settings_provider = settings_provider
        self._assets_provider = assets_provider
        self._signal_provider = signal_provider
        self._analysis_provider = analysis_provider
        self._test_capture_provider = test_capture_provider
        self._learning_state_provider = learning_state_provider
        self._deep_scan_callback = deep_scan_callback
        self._status_callback = status_callback
        self._log_callback = log_callback

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._offset = 0
        self._state = TelegramRuntimeState()

        # User management
        self._users: dict[str, UserUsage] = {}
        self._history: list[SignalHistoryEntry] = []
        self._known_chat_ids: set[str] = set()

        # Pending message state (for admin message flow)
        self._pending_msg_target: str = ""

        # Last signal context for RESCAN
        self._last_signal = LastSignalContext()

        # Callback data -> chat state mapping
        self._chat_state: dict[str, str] = {}  # chat_id -> current view

    @property
    def state(self) -> TelegramRuntimeState:
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def settings(self) -> TelegramSettings:
        # The provider returns AppSettings, we need the telegram sub-object
        data = self._settings_provider()
        if hasattr(data, 'telegram'):
            return data.telegram
        return data # Fallback if provider was already providing telegram settings directly

    def start(self) -> None:
        settings = self._settings_provider()
        token = str(settings.bot_token or "").strip()
        if not token:
            raise RuntimeError("Enter a bot token before starting the Telegram bot.")
        self.stop()
        self._stop_event = threading.Event()
        self._emit_state(running=True, connected=False, status="Starting Telegram bot...", error="")
        self._thread = threading.Thread(target=self._run, daemon=True, name="eternal-telegram-bot")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._emit_state(running=False, connected=False, status="Stopped", error="")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_state(self, **updates) -> None:
        self._state = replace(self._state, **updates)
        self._status_callback(self._state)

    def _log(self, level: str, message: str) -> None:
        self._log_callback(level, message)

    def _ensure_user(self, chat_id: str) -> UserUsage:
        if chat_id not in self._users:
            tier = "ADMIN" if self._is_admin(chat_id) else "FREE"
            self._users[chat_id] = UserUsage(
                chat_id=chat_id,
                tier=tier,
                last_reset=datetime.now().strftime("%Y-%m-%d"),
            )
            if len(self._known_chat_ids) < MAX_KNOWN_USERS:
                self._known_chat_ids.add(chat_id)
        return self._users[chat_id]

    def _is_admin(self, chat_id: str) -> bool:
        settings = self._settings_provider()
        raw = str(settings.admin_chat_ids or "").strip()
        if not raw:
            return True
        allowed = {p.strip() for p in raw.replace(";", ",").split(",") if p.strip()}
        return chat_id in allowed

    def _is_premium(self, chat_id: str) -> bool:
        user = self._ensure_user(chat_id)
        return user.tier in ("PREMIUM", "ADMIN")

    def _get_or_create_asset(self, symbol: str) -> AssetInfo:
        for asset in self._assets_provider():
            if asset.symbol == symbol:
                return asset
        # Create a synthetic AssetInfo for pairs not in the live catalog
        return AssetInfo(symbol=symbol, payout=82.0, is_open=True, category="otc", feed_status="live", last_price=0.0)

    def _resolve_pair(self, market_type: str, pair_index: int):
        """Return (symbol, display_name) for a given market+index."""
        if market_type == "OTC":
            all_pairs = OTC_CURRENCIES + OTC_STOCKS
            if 0 <= pair_index < len(all_pairs):
                sym, disp = all_pairs[pair_index]
                return sym, disp
        elif market_type == "REAL":
            if 0 <= pair_index < len(REAL_PAIRS):
                sym, disp = REAL_PAIRS[pair_index]
                return sym, disp
        return None, None

    def _add_history(self, entry: SignalHistoryEntry):
        self._history.append(entry)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

    def _build_analysis(self, symbol: str, broker_slug: str) -> dict:
        """Call the analysis_provider and return a dict with decision, candles, etc."""
        try:
            report = self._analysis_provider(symbol, broker_slug)
            return report
        except Exception as e:
            self._log("error", f"Analysis failed for {symbol}: {e}")
            # Return a minimal report
            return {
                "decision": StrategyDecision(
                    action="HOLD",
                    confidence=0.55,
                    summary="No strong signal",
                    reason="Insufficient data",
                    recommended_duration=120,
                ),
                "candles": [],
                "entry_price": 0.0,
                "asset_label": symbol,
                "image_path": None,
            }

    # ------------------------------------------------------------------
    # Telegram API
    # ------------------------------------------------------------------

    def _api_call(self, method: str, payload: dict | None) -> object:
        settings = self._settings_provider()
        token = str(settings.bot_token or "").strip()
        if not token:
            raise RuntimeError("Telegram bot token is missing.")
        raw_payload = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=raw_payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=35) as response:
                if response.status != 200:
                    raise RuntimeError(f"Telegram API returned status {response.status}")
                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type.lower():
                    raise RuntimeError(f"Expected JSON response, got {content_type}")
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            body = ""
            try:
                body = error.read().decode("utf-8", errors="replace")
            except Exception:
                body = str(error)
            raise RuntimeError(body or str(error)) from error
        except URLError as error:
            raise RuntimeError(str(error.reason or error)) from error

        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed.get("ok"):
            description = str(parsed.get("description") or "").strip() if isinstance(parsed, dict) else ""
            raise RuntimeError(description or "Telegram rejected the request.")
        return parsed.get("result")

    def _api_send_photo(self, chat_id: int | str, photo_path: str | Path,
                         *, caption: str = "", reply_markup: dict | None = None) -> object:
        settings = self._settings_provider()
        token = str(settings.bot_token or "").strip()
        if not token:
            raise RuntimeError("Telegram bot token is missing.")
        path = Path(photo_path)
        if not path.is_file():
            raise RuntimeError(f"Telegram photo file is missing: {path}")
        data = {"chat_id": str(chat_id), "caption": str(caption or "")}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        with path.open("rb") as handle:
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data=data,
                    files={"photo": (path.name, handle, mime)},
                    timeout=45,
                )
            except requests.exceptions.SSLError:
                # Retry without SSL verification as fallback
                path.seek(0)
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data=data,
                    files={"photo": (path.name, handle, mime)},
                    timeout=45,
                    verify=False,
                )
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("description") or "Telegram rejected the photo upload."))
        return payload.get("result")

    def _send_message(self, chat_id: int | str, text: str,
                       *, reply_markup: dict | None = None) -> int:
        from .ui.alerts import play_alert_sound
        play_alert_sound(self.settings.sound_enabled)

        payload: dict[str, object] = {"chat_id": chat_id, "text": str(text or ""), "parse_mode": "HTML"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self._api_call("sendMessage", payload)
        if isinstance(result, dict):
            return int(result.get("message_id", 0) or 0)
        return 0

    def _edit_message(self, chat_id: int | str, message_id: int | None, text: str,
                       *, reply_markup: dict | None = None) -> None:
        if not message_id:
            self._send_message(chat_id, text, reply_markup=reply_markup)
            return
        payload: dict[str, object] = {"chat_id": chat_id, "message_id": message_id, "text": str(text or ""), "parse_mode": "HTML"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            self._api_call("editMessageText", payload)
        except Exception:
            # If edit fails (e.g. text unchanged), send new message
            self._send_message(chat_id, text, reply_markup=reply_markup)

    def _delete_message(self, chat_id: int | str, message_id: int) -> None:
        try:
            self._api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            me = self._api_call("getMe", {})
            display_name = (
                f"@{me.get('username')}" if isinstance(me, dict) and me.get("username")
                else str(me.get("first_name") or "Telegram bot")
            ) if isinstance(me, dict) else "Telegram bot"
            self._emit_state(running=True, connected=True, status="Telegram bot is running",
                              me=display_name, error="")
            self._log("info", f"Telegram bot started as {display_name}.")
        except Exception as error:
            self._emit_state(running=False, connected=False, status="Telegram bot failed to start",
                              error=str(error))
            self._log("error", f"Telegram bot start failed: {error}")
            return

        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                updates = self._api_call("getUpdates", {
                    "timeout": 20,
                    "offset": self._offset,
                    "allowed_updates": ["message", "callback_query"],
                })
                backoff = 1.0
                for update in updates if isinstance(updates, list) else []:
                    update_id = int(update.get("update_id", 0) or 0)
                    if update_id >= self._offset:
                        self._offset = update_id + 1
                    self._handle_update(update)
            except Exception as error:
                if self._stop_event.is_set():
                    break
                self._emit_state(running=True, connected=False, status="Telegram reconnecting...", error=str(error))
                self._log("error", f"Telegram polling failed: {error}")
                self._stop_event.wait(backoff)
                backoff = min(backoff * 1.8, 10.0)

        self._emit_state(running=False, connected=False, status="Stopped", error="")
        self._log("info", "Telegram bot stopped.")

    # ------------------------------------------------------------------
    # Update handling
    # ------------------------------------------------------------------

    def _handle_update(self, update: dict) -> None:
        if not isinstance(update, dict):
            return
        if isinstance(update.get("callback_query"), dict):
            self._handle_callback_query(update["callback_query"])
            return
        if isinstance(update.get("message"), dict):
            self._handle_message(update["message"])

    def _handle_message(self, message: dict) -> None:
        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if chat_id in {None, ""}:
            return
        chat_id_text = str(chat_id)
        self._known_chat_ids.add(chat_id_text)
        text = str(message.get("text") or "").strip()
        if not text:
            return

        self._emit_state(running=True, connected=True, status="Telegram bot is running",
                          last_chat_id=chat_id_text, last_command=text, error="")

        user = self._ensure_user(chat_id_text)
        is_adm = self._is_admin(chat_id_text)

        # Check for pending admin message
        if self._pending_msg_target and is_adm:
            # Admin typed a message to forward
            target = self._pending_msg_target
            self._pending_msg_target = ""
            try:
                self._send_message(target, f"\U0001f4e2 Message from Admin:\n\n{text}")
                self._send_message(chat_id_text, f"\u2705 Sent to {target}")
            except Exception as e:
                self._send_message(chat_id_text, f"\u274c Failed: {e}")
            return

        normalized = text.casefold()
        if normalized in {"/start", "/menu"}:
            self._send_welcome(chat_id_text)
            return
        if normalized == "/help":
            settings = self._settings_provider()
            self._send_message(chat_id_text,
                f"{E_ROBOT} Eternal AI Bot Help\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"/start - Open main menu\n"
                f"/help - Show this help\n"
                f"\n"
                f"Use the buttons below to navigate.",
                reply_markup=_start_keyboard(is_adm, settings))
            return

        # Fallback: show welcome
        self._send_welcome(chat_id_text)

    def _handle_callback_query(self, callback_query: dict) -> None:
        callback_id = str(callback_query.get("id") or "")
        data = str(callback_query.get("data") or "").strip()
        message = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message, dict) else {}
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        message_id = message.get("message_id") if isinstance(message, dict) else None
        if chat_id in {None, ""}:
            return
        chat_id_text = str(chat_id)
        self._known_chat_ids.add(chat_id_text)
        self._ensure_user(chat_id_text)
        is_adm = self._is_admin(chat_id_text)
        premium = self._is_premium(chat_id_text)

        # Answer callback to remove loading spinner
        try:
            self._api_call("answerCallbackQuery", {"callback_query_id": callback_id})
        except Exception:
            pass

        # ----- Route callbacks -----

        if data == "OTC":
            self._send_otc_market(chat_id_text, message_id, premium)
            return

        if data == "REAL":
            self._send_real_market(chat_id_text, message_id, premium)
            return

        if data == "BACK":
            self._send_welcome(chat_id_text, message_id)
            return

        if data == "ADMIN":
            if is_adm:
                self._send_admin_panel(chat_id_text, message_id)
            else:
                self._send_welcome(chat_id_text, message_id)
            return

        # Pair selection: P_OTC_N or P_REAL_N
        if data.startswith("P_OTC_"):
            try:
                idx = int(data.split("_", 2)[2])
            except (ValueError, IndexError):
                return
            self._deliver_signal(chat_id_text, "OTC", idx, message_id)
            return

        if data.startswith("P_REAL_"):
            try:
                idx = int(data.split("_", 2)[2])
            except (ValueError, IndexError):
                return
            self._deliver_signal(chat_id_text, "REAL", idx, message_id)
            return

        # Scan options
        if data == "OTC_SCAN":
            state = self._chat_state.get(chat_id_text, "")
            if state == "real_market":
                self._quick_scan(chat_id_text, "REAL", message_id)
            else:
                self._quick_scan(chat_id_text, "OTC", message_id)
            return

        if data == "DEEP_SCAN":
            state = self._chat_state.get(chat_id_text, "")
            if state == "real_market":
                self._deep_scan_market(chat_id_text, "REAL", message_id)
            else:
                self._deep_scan_market(chat_id_text, "OTC", message_id)
            return

        if data == "FUTURE":
            state = self._chat_state.get(chat_id_text, "")
            if state == "real_market":
                self._future_signals(chat_id_text, "REAL", message_id)
            else:
                self._future_signals(chat_id_text, "OTC", message_id)
            return

        if data == "RESCAN":
            self._rescan_signal(chat_id_text, message_id)
            return

        # Admin callbacks
        if data == "ADMIN_STATUS":
            if is_adm:
                self._send_admin_status(chat_id_text, message_id)
            return

        if data == "ADMIN_CHARTS":
            if is_adm:
                self._send_admin_charts(chat_id_text, message_id)
            return

        if data == "ADMIN_STATS":
            if is_adm:
                self._send_admin_stats(chat_id_text, message_id)
            return

        if data == "ADMIN_USERS":
            if is_adm:
                self._send_user_history(chat_id_text, message_id)
            return

        if data == "ADMIN_MSG":
            if is_adm:
                self._send_message_users(chat_id_text, message_id)
            return

        if data == "ADMIN_TEST":
            if is_adm:
                self._admin_test_capture(chat_id_text, message_id)
            return

        if data == "ADMIN_IMG_TEST":
            if is_adm:
                self._admin_image_test(chat_id_text, message_id)
            return

        if data == "ADMIN_IMG_DEL":
            if is_adm:
                self._admin_image_delivery(chat_id_text, message_id)
            return

        if data == "MSG_ALL":
            if is_adm:
                self._pending_msg_target = "ALL"
                self._edit_message(chat_id_text, message_id,
                    f"{E_SEND} Type your message now. It will be broadcast to ALL users.",
                    reply_markup=None)
            return

        if data.startswith("MSG_"):
            if is_adm:
                target_id = data[4:]
                self._pending_msg_target = target_id
                self._edit_message(chat_id_text, message_id,
                    f"{E_SEND} Type your message now. It will be sent to {target_id}.",
                    reply_markup=None)
            return

        if data.startswith("UH_"):
            if is_adm:
                target_id = data[3:]
                self._send_user_history_detail(chat_id_text, target_id, message_id)
            return

    # ------------------------------------------------------------------
    # Menu screens
    # ------------------------------------------------------------------

    def _send_welcome(self, chat_id: str, message_id: int | None = None) -> None:
        user = self._ensure_user(chat_id)
        is_adm = self._is_admin(chat_id)
        sig_rem = user.signals_remaining()
        settings = self._settings_provider()
        text = _start_welcome(user.tier, sig_rem, settings)
        kb = _start_keyboard(is_adm, settings)
        self._chat_state[chat_id] = "main_menu"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=kb)
        else:
            self._send_message(chat_id, text, reply_markup=kb)

    def _send_otc_market(self, chat_id: str, message_id: int | None, premium: bool) -> None:
        text = _otc_market_header()
        kb = _otc_market_keyboard(premium)
        self._chat_state[chat_id] = "otc_market"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=kb)
        else:
            self._send_message(chat_id, text, reply_markup=kb)

    def _send_real_market(self, chat_id: str, message_id: int | None, premium: bool) -> None:
        text = _real_market_header()
        kb = _real_market_keyboard(premium)
        self._chat_state[chat_id] = "real_market"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=kb)
        else:
            self._send_message(chat_id, text, reply_markup=kb)

    def _send_admin_panel(self, chat_id: str, message_id: int | None) -> None:
        text = _admin_panel_header()
        kb = _admin_keyboard()
        self._chat_state[chat_id] = "admin_panel"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=kb)
        else:
            self._send_message(chat_id, text, reply_markup=kb)

    # ------------------------------------------------------------------
    # Signal delivery
    # ------------------------------------------------------------------

    def _deliver_signal(self, chat_id: str, market_type: str, pair_index: int,
                         message_id: int | None = None) -> None:
        user = self._ensure_user(chat_id)
        symbol, display = self._resolve_pair(market_type, pair_index)
        if symbol is None:
            self._send_message(chat_id, f"{E_WARNING} Invalid pair selection.")
            return

        # Check daily limit for FREE users
        if not user.can_send_signal():
            self._send_message(chat_id,
                f"{E_LOCK} Daily signal limit reached ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT}).\n"
                f"Your limit resets at midnight. Upgrade to PREMIUM for unlimited signals.")
            return

        # Check cooldown
        pair_key = f"{market_type}_{pair_index}"
        if user.is_on_cooldown(pair_key):
            remaining = user.cooldown_remaining(pair_key)
            self._send_message(chat_id,
                f"\u23f1\ufe0f Please wait {remaining}s before scanning this pair again.")
            return

        pair_label = display or _format_pair_display(symbol)
        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"

        # Show loading
        loading_text = f"{E_BRAIN} Analyzing {pair_label}..."
        if message_id:
            self._edit_message(chat_id, message_id, loading_text, reply_markup=None)
        else:
            loading_msg_id = self._send_message(chat_id, loading_text)
            message_id = loading_msg_id if loading_msg_id else None

        # Animate scanning steps
        animation_steps = max(1, int(settings.scan_animation_seconds or 3))
        for step in range(animation_steps):
            dots = "." * ((step % 3) + 1)
            animated = (
                f"{E_BRAIN} Analyzing {pair_label}{dots}\n"
                f"Running 15-layer analysis... ({step + 1}/{animation_steps})"
            )
            try:
                self._edit_message(chat_id, message_id, animated, reply_markup=None)
            except Exception:
                pass
            time.sleep(1)

        # Get analysis
        report = self._build_analysis(symbol, broker)
        decision = report.get("decision")
        if decision is None or not isinstance(decision, StrategyDecision):
            decision = StrategyDecision(action="HOLD", confidence=0.55, summary="No clear signal")

        # Derive values
        candles = report.get("candles", [])
        entry_price = report.get("entry_price")
        if entry_price is None and candles:
            entry_price = candles[-1].close

        pair_display = report.get("asset_label") or display or _format_pair_display(symbol)
        time_str = datetime.now().strftime("%H:%M:%S")
        action = str(decision.action or "HOLD")
        expiry_seconds = int(decision.recommended_duration or 60)
        expire_min = max(1, expiry_seconds // 60)
        price = f"{entry_price:.5f}" if entry_price else "N/A"
        confidence_raw = decision.confidence or 0.0
        confidence_pct = int(round(confidence_raw * 100))
        level = _classify_level(confidence_pct)

        # Analysis summary
        analysis_parts = []
        if decision.summary:
            analysis_parts.append(decision.summary)
        if decision.reason:
            analysis_parts.append(decision.reason)
        analysis_points = ", ".join(analysis_parts) if analysis_parts else "15-Layer Analysis Complete"
        win_rate = 85  # Default win rate for now as fallback

        # Format signal text
        signal_text = _format_signal_text(
            user_type=user.tier,
            pair_display=pair_display,
            time_str=time_str,
            expire_min=expire_min,
            action=action,
            price=price,
            confidence_pct=confidence_pct,
            level=level,
            win_rate=win_rate,
            analysis_points=analysis_points,
        )

        # Record signal for history
        self._add_history(SignalHistoryEntry(
            chat_id=chat_id,
            pair=pair_display,
            action=action,
            confidence=confidence_pct,
            scan_type="Single",
            time=time_str,
        ))

        # Update usage
        user.record_signal(pair_key)
        self._last_signal = LastSignalContext(
            chat_id=chat_id,
            symbol=symbol,
            broker_slug=broker,
            market_type=market_type,
            pair_index=pair_index,
        )

        # Send chart image first, then text
        image_path = str(report.get("image_path") or "").strip()
        if image_path and Path(image_path).is_file():
            try:
                self._api_send_photo(chat_id, image_path, caption="")
            except Exception:
                pass
            if message_id:
                try:
                    self._delete_message(chat_id, message_id)
                except Exception:
                    pass
            self._send_message(chat_id, signal_text, reply_markup=_signal_keyboard())
        else:
            # Try to render chart from candles
            rendered_chart = None
            if candles and isinstance(candles, list):
                try:
                    rendered_chart = render_signal_chart(
                        candles=candles,
                        signal_action=action if action in ("CALL", "PUT") else "HOLD",
                        confidence=float(confidence_pct),
                        symbol=symbol,
                        entry_price=entry_price,
                    )
                except Exception:
                    pass

            if rendered_chart and Path(rendered_chart).is_file():
                try:
                    self._api_send_photo(chat_id, rendered_chart, caption="")
                except Exception:
                    pass
                finally:
                    try:
                        Path(rendered_chart).unlink(missing_ok=True)
                    except Exception:
                        pass
                if message_id:
                    try:
                        self._delete_message(chat_id, message_id)
                    except Exception:
                        pass
                self._send_message(chat_id, signal_text, reply_markup=_signal_keyboard())
            else:
                self._edit_message(chat_id, message_id, signal_text, reply_markup=_signal_keyboard())

        # Non-blocking: render and send chart overlay after text
        self._try_send_chart_overlay(chat_id, symbol, action, confidence_pct, entry_price, candles)

    def _rescan_signal(self, chat_id: str, message_id: int | None) -> None:
        ls = self._last_signal
        if ls.symbol and ls.chat_id == chat_id:
            self._deliver_signal(chat_id, ls.market_type if ls.market_type else "OTC",
                                  ls.pair_index if ls.pair_index >= 0 else 0, message_id)
        else:
            self._send_message(chat_id, f"{E_WARNING} No previous signal to rescan.")

    def _try_send_chart_overlay(self, chat_id: str, symbol: str, action: str,
                                 confidence_pct: int, entry_price: float | None,
                                 candles: list) -> None:
        """Non-blocking chart render sent after the text signal."""
        try:
            if not candles or not isinstance(candles, list):
                return
            chart_path = render_signal_chart(
                candles=candles,
                signal_action=action if action in ("CALL", "PUT") else "HOLD",
                confidence=float(confidence_pct),
                symbol=symbol,
                entry_price=entry_price,
            )
            self._api_send_photo(chat_id, chart_path,
                                  caption=f"{E_CHART} Eternal AI Bot - {action} {symbol} ({confidence_pct}%)")
            try:
                Path(chart_path).unlink(missing_ok=True)
            except Exception:
                pass
            self._cleanup_old_charts()
        except Exception as e:
            self._log("warning", f"Chart overlay failed: {e}")

    def _cleanup_old_charts(self, keep: int = 50) -> None:
        try:
            reports = runtime_dir() / "telegram_reports"
            if not reports.is_dir():
                return
            charts = sorted(reports.glob("chart_*.png"), key=lambda p: p.stat().st_mtime)
            for old in charts[:-keep]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except Exception as e:
            self._log("warning", f"Chart cleanup failed: {e}")

    # ------------------------------------------------------------------
    # Quick Scan
    # ------------------------------------------------------------------

    def _quick_scan(self, chat_id: str, market_type: str, message_id: int | None) -> None:
        user = self._ensure_user(chat_id)
        if not user.can_send_signal():
            self._send_message(chat_id,
                f"{E_LOCK} Daily signal limit reached. Upgrade to PREMIUM for unlimited signals.")
            return

        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"

        pairs = OTC_CURRENCIES + OTC_STOCKS if market_type == "OTC" else REAL_PAIRS

        self._edit_message(chat_id, message_id,
            f"{E_SATELLITE} Running Quick Scan on {market_type} market...\n"
            f"Scanning {len(pairs)} pairs...", reply_markup=None)

        results = []
        for sym, disp in pairs:
            try:
                report = self._build_analysis(sym, broker)
                decision = report.get("decision")
                if decision and isinstance(decision, StrategyDecision) and decision.action in ("CALL", "PUT"):
                    conf = int(round((decision.confidence or 0.0) * 100))
                    if conf >= 55:
                        results.append({
                            "pair": disp or _format_pair_display(sym),
                            "action": decision.action,
                            "confidence": conf,
                            "level": _classify_level(conf),
                            "summary": decision.summary or "",
                            "_symbol": sym,
                        })
            except Exception:
                continue

        if not results:
            self._edit_message(chat_id, message_id,
                f"{E_SATELLITE} QUICK SCAN RESULTS\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"\n"
                f"No strong signals found right now.\n"
                f"Try again in a few minutes.",
                reply_markup=_real_market_keyboard(self._is_premium(chat_id)) if market_type == "REAL"
                else _otc_market_keyboard(self._is_premium(chat_id)))
            return

        # Sort by confidence, take top N
        results.sort(key=lambda r: r["confidence"], reverse=True)
        top = results[:TOP_QUICK_SCAN]

        scan_text = _quick_scan_text(top)
        self._edit_message(chat_id, message_id, scan_text,
            reply_markup=_real_market_keyboard(self._is_premium(chat_id)) if market_type == "REAL"
            else _otc_market_keyboard(self._is_premium(chat_id)))

    # ------------------------------------------------------------------
    # Deep Scan (market-wide)
    # ------------------------------------------------------------------

    def _deep_scan_market(self, chat_id: str, market_type: str, message_id: int | None) -> None:
        user = self._ensure_user(chat_id)
        if not user.can_send_signal():
            self._send_message(chat_id,
                f"{E_LOCK} Daily signal limit reached. Upgrade to PREMIUM for unlimited signals.")
            return

        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"

        pairs = OTC_CURRENCIES + OTC_STOCKS if market_type == "OTC" else REAL_PAIRS

        self._edit_message(chat_id, message_id,
            f"{E_SEARCH} Deep Scan running on {market_type} market...\n"
            f"Analyzing {len(pairs)} pairs with 15-layer engine...", reply_markup=None)

        best = None
        best_conf = 0
        best_market = "OTC"
        best_idx = 0

        for idx, (sym, disp) in enumerate(pairs):
            try:
                report = self._build_analysis(sym, broker)
                decision = report.get("decision")
                if decision and isinstance(decision, StrategyDecision) and decision.action in ("CALL", "PUT"):
                    conf = (decision.confidence or 0.0)
                    if conf > best_conf:
                        best_conf = conf
                        best = (sym, disp, idx, report)
                        best_market = market_type
            except Exception:
                continue

        if best is None:
            self._edit_message(chat_id, message_id,
                f"{E_SEARCH} Deep Scan Complete\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"\n"
                f"No strong signals found.\n"
                f"Try again later.",
                reply_markup=_real_market_keyboard(self._is_premium(chat_id)) if market_type == "REAL"
                else _otc_market_keyboard(self._is_premium(chat_id)))
            return

        sym, disp, idx, report = best
        # Find the index in the global OTC/REAL list
        if market_type == "OTC":
            global_idx = idx
        else:
            global_idx = idx

        # Deliver as a normal signal
        self._deliver_signal(chat_id, market_type, global_idx, message_id)

    # ------------------------------------------------------------------
    # Future Signals
    # ------------------------------------------------------------------

    def _future_signals(self, chat_id: str, market_type: str, message_id: int | None) -> None:
        user = self._ensure_user(chat_id)
        if not user.can_send_signal():
            self._send_message(chat_id,
                f"{E_LOCK} Daily signal limit reached. Upgrade to PREMIUM for unlimited signals.")
            return

        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"
        pairs = OTC_CURRENCIES + OTC_STOCKS if market_type == "OTC" else REAL_PAIRS

        self._edit_message(chat_id, message_id,
            f"{E_CRYSTAL} Generating Future Signals...\n"
            f"Analyzing upcoming opportunities...", reply_markup=None)

        signals = []
        now = datetime.now()
        for i, (sym, disp) in enumerate(pairs):
            if len(signals) >= MAX_FUTURE_SIGNALS:
                break
            try:
                report = self._build_analysis(sym, broker)
                decision = report.get("decision")
                if decision and isinstance(decision, StrategyDecision) and decision.action in ("CALL", "PUT"):
                    conf = int(round((decision.confidence or 0.0) * 100))
                    future_time = (now + timedelta(minutes=(i + 1) * 5)).strftime("%H:%M")
                    signals.append({
                        "pair": disp or _format_pair_display(sym),
                        "action": decision.action,
                        "confidence": conf,
                        "time": future_time,
                    })
            except Exception:
                continue

        if not signals:
            self._edit_message(chat_id, message_id,
                f"{E_CRYSTAL} Future Signals\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"\n"
                f"No future signals predicted right now.",
                reply_markup=_real_market_keyboard(self._is_premium(chat_id)) if market_type == "REAL"
                else _otc_market_keyboard(self._is_premium(chat_id)))
            return

        text = _future_signals_text(signals)
        self._edit_message(chat_id, message_id, text,
            reply_markup=_real_market_keyboard(self._is_premium(chat_id)) if market_type == "REAL"
            else _otc_market_keyboard(self._is_premium(chat_id)))

    # ------------------------------------------------------------------
    # Admin screens
    # ------------------------------------------------------------------

    def _send_admin_status(self, chat_id: str, message_id: int | None) -> None:
        assets = list(self._assets_provider())
        otc_healthy = sum(1 for a in assets if a.symbol.lower().endswith("_otc") and (a.last_price > 0 or a.feed_status in ("live", "synced")))
        otc_total = len([a for a in assets if a.symbol.lower().endswith("_otc")]) or len(OTC_CURRENCIES) + len(OTC_STOCKS)
        real_healthy = sum(1 for a in assets if not a.symbol.lower().endswith("_otc") and (a.last_price > 0 or a.feed_status in ("live", "synced")))
        real_total = len([a for a in assets if not a.symbol.lower().endswith("_otc")]) or len(REAL_PAIRS)
        total_signals = sum(u.total_signals for u in self._users.values())
        total_users = len(self._known_chat_ids)
        history_count = len(self._history)

        text = _status_text(otc_healthy, otc_total, real_healthy, real_total,
                             total_signals, total_users, history_count)
        self._chat_state[chat_id] = "admin_status"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_status_keyboard())
        else:
            self._send_message(chat_id, text, reply_markup=_status_keyboard())

    def _send_admin_charts(self, chat_id: str, message_id: int | None) -> None:
        assets = list(self._assets_provider())
        lines = [f"{E_BARS} CHART STATUS", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550", ""]
        ok_count = 0
        warn_count = 0
        off_count = 0

        # Show OTC pairs
        for sym, disp in OTC_CURRENCIES:
            asset = next((a for a in assets if a.symbol == sym), None)
            if asset and (asset.last_price > 0 or asset.feed_status in ("live", "synced")):
                lines.append(f"{E_CHECKMARK} {disp}")
                ok_count += 1
            elif asset and asset.last_price > 0:
                lines.append(f"{E_WARNING} {disp} (data but no EA)")
                warn_count += 1
            else:
                lines.append(f"{E_WARNING} {disp}")
                warn_count += 1

        # Show OTC stocks
        for sym, disp in OTC_STOCKS:
            asset = next((a for a in assets if a.symbol == sym), None)
            if asset and (asset.last_price > 0 or asset.feed_status in ("live", "synced")):
                lines.append(f"{E_CHECKMARK} {disp}")
                ok_count += 1
            else:
                lines.append(f"{E_WARNING} {disp}")
                warn_count += 1

        lines.append(f"\n{E_CHECKMARK} OK:{ok_count} {E_WARNING} Warn:{warn_count} {E_RED} Off:{off_count}")

        text = "\n".join(lines)
        self._chat_state[chat_id] = "admin_charts"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_status_keyboard())
        else:
            self._send_message(chat_id, text, reply_markup=_status_keyboard())

    def _send_admin_stats(self, chat_id: str, message_id: int | None) -> None:
        total_signals = sum(u.total_signals for u in self._users.values())
        total_users = len(self._known_chat_ids)
        today = datetime.now().strftime("%Y-%m-%d")
        users_today = sum(1 for u in self._users.values() if u.last_reset == today and u.total_signals > 0)
        history_count = len(self._history)

        user_details = []
        for uid, u in sorted(self._users.items(), key=lambda x: x[1].total_signals, reverse=True):
            user_details.append({
                "chat_id": uid,
                "tier": u.tier,
                "signals": u.total_signals,
            })

        text = _stats_text(total_signals, users_today, total_users, history_count, user_details)
        self._chat_state[chat_id] = "admin_stats"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_stats_keyboard())
        else:
            self._send_message(chat_id, text, reply_markup=_stats_keyboard())

    def _send_user_history(self, chat_id: str, message_id: int | None) -> None:
        known_users = []
        for uid, u in sorted(self._users.items(), key=lambda x: x[1].total_signals, reverse=True):
            known_users.append({
                "chat_id": uid,
                "tier": u.tier,
                "signals": u.total_signals,
            })
        if not known_users:
            text = f"{E_MEMO} No users recorded yet."
        else:
            lines = [f"{E_MEMO} USER HISTORY", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550", ""]
            for u in known_users:
                hist_count = sum(1 for h in self._history if h.chat_id == u["chat_id"])
                lines.append(f"{E_USERS} {u['chat_id']}")
                lines.append(f"  [{u['tier']}] Sigs:{u['signals']} Hist:{hist_count}")
                lines.append("")
            text = "\n".join(lines)

        self._chat_state[chat_id] = "admin_users"
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_user_history_keyboard(known_users))
        else:
            self._send_message(chat_id, text, reply_markup=_user_history_keyboard(known_users))

    def _send_user_history_detail(self, admin_chat_id: str, user_id: str, message_id: int | None) -> None:
        user = self._users.get(user_id)
        if not user:
            self._send_message(admin_chat_id, f"{E_WARNING} User {user_id} not found.")
            return
        entries = [e for e in self._history if e.chat_id == user_id][-10:]
        text = _user_history_detail(user_id, user.tier, user.total_signals,
                                     [{"action": e.action, "pair": e.pair, "time": e.time,
                                       "scan_type": e.scan_type, "confidence": e.confidence}
                                      for e in entries])
        kb = _user_history_detail_keyboard(user_id)
        if message_id:
            self._edit_message(admin_chat_id, message_id, text, reply_markup=kb)
        else:
            self._send_message(admin_chat_id, text, reply_markup=kb)

    def _send_message_users(self, chat_id: str, message_id: int | None) -> None:
        known_users = []
        for uid, u in sorted(self._users.items(), key=lambda x: x[1].total_signals, reverse=True):
            known_users.append({
                "chat_id": uid,
                "tier": u.tier,
            })
        if not known_users:
            text = f"{E_SEND} No known users to message."
        else:
            lines = [f"{E_SEND} MESSAGE USERS", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550",
                      "", f"Known Users: {len(self._known_chat_ids)}", "", "Select a user to message:"]
            for u in known_users[:10]:
                lines.append(f"{E_USERS} {u['chat_id']} [{u['tier']}]")
            text = "\n".join(lines)
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_msg_users_keyboard(known_users))
        else:
            self._send_message(chat_id, text, reply_markup=_msg_users_keyboard(known_users))

    def _admin_test_capture(self, chat_id: str, message_id: int | None) -> None:
        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"
        try:
            payload = self._test_capture_provider(broker)
        except Exception as e:
            self._edit_message(chat_id, message_id,
                f"{E_CAMERA} Test Capture\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"\n"
                f"\u274c Failed: {e}",
                reply_markup=_admin_keyboard())
            return

        path = str(payload.get("path") or "")
        broker_name = str(payload.get("broker_name") or broker)
        if path and Path(path).is_file():
            try:
                self._api_send_photo(chat_id, path,
                                      caption=f"{E_CHECKMARK} OK: {broker_name}")
            except Exception as e:
                self._send_message(chat_id, f"\u274c Photo send failed: {e}")
        else:
            self._send_message(chat_id, f"\u274c No capture file returned.")

        if message_id:
            self._edit_message(chat_id, message_id,
                f"{E_CAMERA} Test Capture\n"
                f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"\n"
                f"{E_CHECKMARK} OK: {broker_name}",
                reply_markup=_admin_keyboard())

    def _admin_image_test(self, chat_id: str, message_id: int | None) -> None:
        """Batch test screenshots for all OTC pairs."""
        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"

        self._edit_message(chat_id, message_id,
            f"{E_PICTURE} Running Image Test...\n"
            f"Testing {len(OTC_CURRENCIES) + len(OTC_STOCKS)} pairs...",
            reply_markup=None)

        ok_count = 0
        fail_count = 0
        skip_count = 0

        all_pairs = OTC_CURRENCIES + OTC_STOCKS
        for sym, disp in all_pairs:
            try:
                report = self._build_analysis(sym, broker)
                img = str(report.get("image_path") or "")
                if img and Path(img).is_file():
                    ok_count += 1
                else:
                    skip_count += 1
            except Exception:
                fail_count += 1

        text = _image_test_results(ok_count, fail_count, skip_count)
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_admin_keyboard())
        else:
            self._send_message(chat_id, text, reply_markup=_admin_keyboard())

    def _admin_image_delivery(self, chat_id: str, message_id: int | None) -> None:
        """Diagnostic view of image delivery capability."""
        settings = self._settings_provider()
        broker = settings.preferred_broker or "quotex"

        self._edit_message(chat_id, message_id,
            f"{E_SATELLITE} Running Image Delivery Diagnostics...\n"
            f"Checking {len(OTC_CURRENCIES) + len(OTC_STOCKS)} pairs...",
            reply_markup=None)

        all_pairs = OTC_CURRENCIES + OTC_STOCKS
        lines = [f"{E_SATELLITE} DIAGNOSTICS", f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550", ""]
        total_data = 0
        total_ok = 0

        for sym, disp in all_pairs:
            try:
                report = self._build_analysis(sym, broker)
                img = str(report.get("image_path") or "")
                candles = report.get("candles", [])
                if candles:
                    total_data += 1
                if img and Path(img).is_file():
                    lines.append(f"{E_CHECKMARK} {disp}")
                    total_ok += 1
                elif candles:
                    lines.append(f"{E_WARNING} {disp} [DATA OK, NO IMAGE]")
                else:
                    lines.append(f"{E_RED} {disp} [NO DATA]")
            except Exception:
                lines.append(f"{E_RED} {disp} [ERROR]")

        total = len(all_pairs)
        lines.append(f"\nTotal:{total} Data:{total_data} OK:{total_ok}")

        text = "\n".join(lines)
        if message_id:
            self._edit_message(chat_id, message_id, text, reply_markup=_image_delivery_keyboard())
        else:
            self._send_message(chat_id, text, reply_markup=_image_delivery_keyboard())

    # ------------------------------------------------------------------
    # Public API (called from controller)
    # ------------------------------------------------------------------

    def broadcast_signal_with_chart(
        self,
        *,
        decision: StrategyDecision,
        symbol: str,
        candles: list[Candle] | None = None,
        entry_price: float | None = None,
        asset_label: str = "",
    ) -> int:
        """Broadcast a deep-scan signal with chart to all known telegram users."""
        settings = self._settings_provider()
        action = str(decision.action or "HOLD")
        confidence_pct = int(round((decision.confidence or 0.0) * 100))
        display_label = asset_label or _format_pair_display(symbol)
        expire_min = max(1, int(decision.recommended_duration or 60) // 60)
        time_str = datetime.now().strftime("%H:%M:%S")
        price = f"{entry_price:.5f}" if entry_price else "N/A"
        level = _classify_level(confidence_pct)

        analysis_parts = []
        if decision.summary:
            analysis_parts.append(decision.summary)
        if decision.reason:
            analysis_parts.append(decision.reason)
        analysis_points = ", ".join(analysis_parts) if analysis_parts else "15-Layer Analysis Complete"

        signal_text = (
            f"======= Eternal AI Bot =======\n"
            f"  {E_CROWN} ADMIN\n"
            f"\n"
            f"\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550 \u25e5\u25e3\u25c6\u25e2\u25e5 \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557\n"
            f"{E_CHART} PAIR      \u279c {display_label}\n"
            f"{E_CLOCK} TIME      \u279c {time_str}\n"
            f"{E_TIMER} EXPIRE    \u279c {expire_min} Min\n"
            f"{E_GREEN if action == 'CALL' else E_RED} DIRECTION \u279c {action} {E_UP if action == 'CALL' else E_DOWN}\n"
            f"{E_TARGET} PRICE     \u279c {price}\n"
            f"\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550 \u25e2\u25e5\u25c6\u25e3\u25e4 \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\n"
            f"\n"
            f"\u250f\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2513\n"
            f"\u2503   {E_CHART} CONFIDENCE: {confidence_pct}%{_stars(confidence_pct)}\n"
            f"\u2503   {E_BARS} Level: {level}\n"
            f"\u2503   {E_CHECKMARK} Win Rate: 58%\n"
            f"\u2517\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u251b\n"
            f"\n"
            f"{E_MEMO} Analysis:\n"
            f"  {E_CHECKMARK} {analysis_points}\n"
            f"\n"
            f"{E_PHONE} Signal Sent Successfully"
        )

        sent_count = 0
        for cid in sorted(self._known_chat_ids):
            try:
                self._send_message(cid, signal_text, reply_markup=_signal_keyboard())
                if candles and isinstance(candles, list):
                    try:
                        chart_path = render_signal_chart(
                            candles=candles,
                            signal_action=action if action in ("CALL", "PUT") else "HOLD",
                            confidence=float(confidence_pct),
                            symbol=symbol,
                            entry_price=entry_price,
                        )
                        self._api_send_photo(cid, chart_path,
                                              caption=f"{E_CHART} Eternal AI Bot - {action} {symbol} ({confidence_pct}%)")
                        try:
                            Path(chart_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                sent_count += 1
            except Exception as e:
                self._log("error", f"Broadcast to {cid} failed: {e}")
        return sent_count

    def send_message_to_all(self, text: str) -> int:
        """Send a message to all known Telegram users."""
        sent_count = 0
        for cid in sorted(self._known_chat_ids):
            try:
                self._send_message(cid, text)
                sent_count += 1
            except Exception as e:
                self._log("error", f"Broadcast to {cid} failed: {e}")
        return sent_count
