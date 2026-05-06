from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True)
class AssetInfo:
    symbol: str
    payout: float
    is_open: bool
    category: str = "binary"
    display_name: str = ""
    last_price: float = 0.0
    sentiment: float | None = None
    feed_status: str = "warming"
    countdown_seconds: int | None = None
    countdown_updated_at: float = 0.0


@dataclass(slots=True)
class AccountSnapshot:
    balance: float
    mode: str
    backend_name: str
    connected: bool = True


@dataclass(slots=True)
class TradeTicket:
    id: str
    asset: str
    action: str
    amount: float
    duration: int
    opened_at: float
    expiry_time: float = 0.0
    estimated_payout: float = 80.0
    is_demo: bool = True
    accepted: bool = False
    result: bool | None = None
    profit: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyDecision:
    asset: str = ""
    action: str = "HOLD"
    confidence: float = 0.0
    summary: str = "Waiting for candles"
    reason: str = ""
    rsi: float | None = None
    trend_strength: float = 0.0
    recommended_duration: int = 120
    signal_timestamp: int = 0
    reference_price: float = 0.0
    ema_fast: list[float] = field(default_factory=list)
    ema_slow: list[float] = field(default_factory=list)
    atr: float = 0.0

@dataclass(slots=True)
class SessionStats:
    wins: int = 0
    losses: int = 0
    trades_taken: int = 0
    consecutive_losses: int = 0
    net_pnl: float = 0.0
    active_trade_id: str | None = None
    automation_enabled: bool = False
    last_trade_at: float = 0.0


@dataclass(slots=True)
class WorkerAccount:
    email: str = ""
    password: str = ""
    enabled: bool = False
    session_cached: bool = False


@dataclass(slots=True)
class MatrixSettings:
    enabled: bool = False
    workers: list[WorkerAccount] = None
    
    def __post_init__(self):
        if self.workers is None:
            self.workers = [
                WorkerAccount(email="du8eszv@nextsuns.com", password="Ethar2021()"),
                WorkerAccount(email="epicgames191456@gmail.com", password="Ethar2021()"),
                WorkerAccount(email="ioyugwb@cloud-temp.com", password="Ethar2021()"),
            ]


@dataclass(slots=True)
class ConnectionProfile:
    provider: str = "mock"
    email: str = ""
    password: str = ""
    email_pin: str = ""
    quotex_email: str = ""
    quotex_password: str = ""
    quotex_email_pin: str = ""
    pocket_option_url: str = "https://iqoption.com/en/login"
    pocket_option_email: str = ""
    pocket_option_password: str = ""
    exness_login: str = ""
    exness_password: str = ""
    exness_server: str = ""
    enabled_brokers: str = "quotex,iq_option,exness"
    use_all_brokers: bool = False
    primary_broker: str = "quotex"
    remember_password: bool = True
    headless: bool = False
    browser_engine: str = "selenium"  # "selenium" or "playwright"
    data_source: str = "browser"  # "browser" or "websocket"
    account_mode: str = "PRACTICE"
    selected_asset: str = ""  # Empty by default - will be set to first available asset
    candle_period: int = 60
    trade_duration: int = 120
    trade_amount: float = 5.0


@dataclass(slots=True)
class StrategySettings:
    fast_ema: int = 9
    slow_ema: int = 21
    rsi_period: int = 14
    min_confidence: float = 0.56
    auto_trade_enabled: bool = False
    deep_scan_min_confidence: float = 0.50
    preferred_expiry_seconds: int = 120
    entry_timer_seconds: int = 5
    sticky_signal_seconds: int = 75
    learning_enabled: bool = False
    learning_interval_seconds: int = 45
    learning_verify_seconds: int = 120
    take_profit_multiplier: float = 0.0 # 0.0 to disable, e.g. 1.5 for 1.5x ATR
    stop_loss_multiplier: float = 0.0 # 0.0 to disable, e.g. 1.0 for 1.0x ATR


@dataclass(slots=True)
class RiskSettings:
    stop_profit: float = 30.0
    stop_loss: float = 20.0
    max_consecutive_losses: int = 3
    cooldown_seconds: int = 90
    max_open_trades: int = 1
    dynamic_sizing_enabled: bool = False
    sizing_base_amount: float = 5.0
    sizing_multiplier_per_confidence_point: float = 0.0 # e.g. 0.1 for $0.10 per 0.01 confidence
    max_trade_amount: float = 100.0
    martingale_enabled: bool = False
    martingale_factor: float = 2.0
    martingale_max_steps: int = 3
    asset_cooldown_seconds: int = 300 # Cooldown per asset after a trade


@dataclass(slots=True)
class UiSettings:
    auto_refresh_seconds: int = 3
    show_warming_pairs: bool = True


@dataclass(slots=True)
class TelegramSettings:
    enabled: bool = False
    auto_broadcast: bool = False
    sound_enabled: bool = True
    bot_token: str = ""
    engine_name: str = "Eternal AI Bot (Apex Engine v214)"
    start_title: str = "Eternal AI Bot (Apex Engine v214)"
    start_message: str = "Choose a pair, review the market, or run Deep Scan All for the strongest confirmed setup."
    pairs_title: str = "Available OTC Pairs"
    pair_label_template: str = "{pair} ({payout:.0f}%)"
    deep_scan_label: str = "Deep Scan All"
    start_button_text: str = "Open Markets"
    status_button_text: str = "Signal Status"
    pairs_button_text: str = "Show Pairs"
    otc_button_text: str = "💰 OTC Market"
    real_button_text: str = "🌍 Real Market"
    admin_button_text: str = "⚙️ Admin Panel"
    admin_status_text: str = "📊 Status"
    admin_charts_text: str = "📈 Charts"
    admin_broadcast_text: str = "📬 Message Users"
    admin_test_capture_text: str = "📸 Test Capture"
    admin_chat_ids: str = ""
    preferred_broker: str = "quotex"
    enabled_brokers: str = "quotex,iq_option,exness"
    use_all_brokers: bool = True
    scan_animation_seconds: int = 3
    quotex_email: str = ""
    quotex_password: str = ""
    pocket_option_url: str = "https://iqoption.com/en/login"
    pocket_option_email: str = ""
    pocket_option_password: str = ""
    exness_login: str = ""
    exness_password: str = ""
    exness_server: str = ""


@dataclass(slots=True)
class LicenseSettings:
    enabled: bool = True
    api_url: str = ""
    api_token: str = ""
    license_key: str = ""
    remember_license_key: bool = False
    poll_seconds: int = 30  # Increased from 10 to reduce API calls
    machine_lock_enabled: bool = True
    provider_name: str = "custom"
    status_text: str = "License disabled"
    last_checked_at: float = 0.0
    # Validation cache to prevent redundant API calls
    cache_valid_until: float = 0.0
    cached_validation_status: str = ""
    cached_expires_at: str = ""
    integrity_hash: str = ""
    is_admin: bool = False


@dataclass(slots=True)
class AppSettings:
    connection: ConnectionProfile = field(default_factory=ConnectionProfile)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    matrix: MatrixSettings = field(default_factory=MatrixSettings)
    license: LicenseSettings = field(default_factory=LicenseSettings)
