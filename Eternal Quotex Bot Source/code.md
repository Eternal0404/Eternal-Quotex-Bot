# Eternal Quotex Bot - Complete Code Architecture Documentation

## Project Overview

**Eternal Quotex Bot** is a sophisticated algorithmic trading desktop application designed for binary options trading on Quotex and other brokers. It features advanced signal analysis using 15-indicator voting systems, adaptive machine learning, multi-broker support, Telegram integration, and automated trading with comprehensive risk management.

**Version:** v214 (Apex Engine)
**Language:** Python 3.10+
**UI Framework:** PySide6 (Qt6)
**Build System:** PyInstaller

---

## 1. DIRECTORY STRUCTURE

```
Eternal Quotex Bot Source/
├── main.py                              # Development entry point
├── session.json                         # Session history (NEW)
├── memories.json                        # Project knowledge base (NEW)
├── logic.md                             # Feature-to-logic mapping (NEW)
├── code.md                              # This file (NEW)
│
├── eternal_quotex_bot/                  # Main application package
│   ├── __init__.py                      # Package initialization
│   ├── app.py                           # Application entry point (5.0 KB)
│   ├── controller.py                    # Main orchestrator (108.5 KB)
│   ├── controller_deep_scan_new.py      # Deep scan implementation (13.7 KB)
│   ├── models.py                        # Data structures (6.4 KB)
│   ├── paths.py                         # Directory management (1.7 KB)
│   ├── settings.py                      # Settings persistence (11.5 KB)
│   ├── automation.py                    # Auto-trade logic (2.5 KB)
│   ├── learning.py                      # Adaptive learning (18.0 KB)
│   ├── licensing.py                     # License validation (21.7 KB)
│   ├── tick_buffer.py                   # Real-time candle building (9.1 KB)
│   ├── device.py                        # Machine fingerprinting (1.7 KB)
│   ├── visual_signals.py                # Signal formatting (16.1 KB)
│   ├── chart_renderer.py                # Chart generation (17.3 KB)
│   ├── ws_worker_pool.py                # WebSocket pooling (17.8 KB)
│   ├── pw_price_pool.py                 # Price caching (13.7 KB)
│   ├── pine_script.py                   # TradingView integration (25.4 KB)
│   ├── theme.py                         # Legacy theming (5.9 KB)
│   ├── matrix.py                        # Matrix settings (7.6 KB)
│   ├── matrix_orchestrator.py           # Multi-account automation (20.7 KB)
│   ├── broker_adapters.py               # Broker wrappers (9.3 KB)
│   │
│   ├── strategy.py                      # Standard signal engine (18.3 KB)
│   ├── advanced_signal_engine.py        # 15-indicator engine (22.0 KB)
│   ├── apex_analysis.py                 # Apex voting system (14.0 KB)
│   ├── sniper_scan.py                   # Deep scan v1 (34.4 KB)
│   ├── broadcast_scan.py                # Deep scan v2 (9.4 KB)
│   │
│   ├── backend/                         # Backend integrations
│   │   ├── __init__.py
│   │   ├── base.py                      # Abstract interface (1.1 KB)
│   │   ├── live.py                      # Live Quotex trading (341.5 KB)
│   │   ├── mock.py                      # Offline testing (6.8 KB)
│   │   └── external.py                  # IQ Option, Exness (69.0 KB)
│   │
│   ├── ui/                              # User interface
│   │   ├── __init__.py
│   │   ├── main_window.py               # Main UI (178.4 KB)
│   │   ├── charts.py                    # Chart rendering (9.2 KB)
│   │   ├── license_gate.py              # License dialog (10.6 KB)
│   │   └── glassmorphism_theme.py       # QSS theming (30.0 KB)
│   │
│   ├── telegram_bot.py                  # Telegram integration (76.8 KB)
│   │
│   └── tests/                           # Unit tests
│       └── test_*.py                    # Component tests
│
├── supabase/                            # License server backend
│   ├── config.toml                      # Function configuration
│   ├── sql/
│   │   └── license_schema.sql           # Database schema
│   └── functions/
│       └── license-validate/
│           └── index.ts                 # License API (TypeScript)
│
└── build_exe.ps1                        # PyInstaller build script
```

---

## 2. APPLICATION FLOW

### 2.1 Startup Sequence

```
main.py
  |
  +-> multiprocessing.freeze_support()
  +-> from eternal_quotex_bot.app import main
  +-> raise SystemExit(main())
       |
       +-> app.py: main()
            |
            +-> bootstrap_runtime()
            |     -> Create data directories
            |     -> Initialize logging
            |
            +-> QApplication = QApplication(sys.argv)
            +-> Apply glassmorphism theme
            |
            +-> controller = BotController()
            +-> window = MainWindow(controller)
            |
            +-> Load settings from settings.json
            |     -> ConnectionProfile
            |     -> StrategySettings
            |     -> RiskSettings
            |     -> TelegramSettings
            |     -> LicenseSettings
            |     -> MatrixSettings
            |
            +-> If license.enabled:
            |     -> Show LicenseGate dialog
            |     -> Validate key
            |     -> Block if invalid
            |
            +-> window.show()
            +-> sys.exit(app.exec())
```

### 2.2 Connection Flow

```
User clicks Connect
  |
  +-> MainWindow._connect_clicked()
  |     -> controller.connect()
  |
  +-> BotController.async connect()
  |     |
  |     +-> Set connecting = True
  |     +-> Choose backend based on provider:
  |     |     "quotex" -> LiveQuotexBackend
  |     |     "iq_option" -> IQOptionPlaywrightAdapter
  |     |     "exness" -> TwelveDataForexAdapter
  |     |     "mock" -> MockBackend
  |     |     "multi" -> MultiBrokerBackend
  |     |
  |     +-> backend.connect(email, password, mode, headless)
  |     |     |
  |     |     +-> Live backend:
  |     |     |     -> Initialize browser (Selenium/Playwright)
  |     |     |     -> Navigate to broker login
  |     |     |     -> Fill credentials
  |     |     |     -> Handle email PIN if required
  |     |     |     -> Cache session cookies
  |     |     |     -> Start price streaming
  |     |     |
  |     |     +-> Mock backend:
  |     |     |     -> Set connected = True
  |     |     |     -> Generate simulated prices
  |     |     |
  |     |     +-> External backend:
  |     |           -> Broker-specific connection logic
  |     |
  |     +-> Emit connection_changed(True)
  |     +-> fetch_assets()
  |     |     -> backend.fetch_assets()
  |     |     -> Update UI asset list
  |     |
  |     +-> Start price update loop
  |     +-> Set connecting = False
  |
  +-> Update UI:
        -> Show connected status
        -> Display balance
        -> Show asset list
        -> Enable trading buttons
```

---

## 3. MODULE DETAILS

### 3.1 models.py - Data Structures

**Purpose:** Define all data classes used throughout the application

**Classes:**

```python
@dataclass(slots=True)
class Candle:
    """OHLCV candlestick data"""
    timestamp: int          # Unix timestamp
    open: float             # Opening price
    high: float             # Highest price
    low: float              # Lowest price
    close: float            # Closing price
    volume: float = 0.0     # Tick count or volume

@dataclass(slots=True)
class AssetInfo:
    """Trading pair metadata"""
    symbol: str             # e.g., "EURUSD_otc"
    payout: float           # Payout percentage (e.g., 82.0)
    is_open: bool           # Whether trading is allowed
    category: str = "binary"
    display_name: str = ""  # User-friendly name
    last_price: float = 0.0
    sentiment: float | None = None
    feed_status: str = "warming"  # warming, active, error
    countdown_seconds: int | None = None
    countdown_updated_at: float = 0.0

@dataclass(slots=True)
class TradeTicket:
    """Trade record"""
    id: str                 # Unique trade ID
    asset: str              # Symbol traded
    action: str             # "CALL" or "PUT"
    amount: float           # Trade amount
    duration: int           # Duration in seconds
    opened_at: float        # Unix timestamp
    estimated_payout: float = 80.0
    is_demo: bool = True
    accepted: bool = False
    result: bool | None = None      # True=win, False=loss
    profit: float | None = None
    raw: dict = field(default_factory=dict)

@dataclass(slots=True)
class StrategyDecision:
    """Signal output"""
    action: str = "HOLD"            # CALL, PUT, or HOLD
    confidence: float = 0.0         # 0.0 to 1.0
    summary: str = "Waiting for candles"
    reason: str = ""
    rsi: float | None = None
    trend_strength: float = 0.0     # ADX value
    recommended_duration: int = 120
    signal_timestamp: int = 0
    reference_price: float = 0.0
    ema_fast: list[float] = field(default_factory=list)
    ema_slow: list[float] = field(default_factory=list)

@dataclass(slots=True)
class SessionStats:
    """Session performance tracking"""
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
    """Matrix worker credentials"""
    email: str = ""
    password: str = ""
    enabled: bool = False
    session_cached: bool = False

@dataclass(slots=True)
class MatrixSettings:
    """Multi-account automation settings"""
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
    """Broker connection credentials"""
    provider: str = "mock"          # quotex, iq_option, exness, multi, mock
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
    browser_engine: str = "selenium"  # selenium or playwright
    data_source: str = "browser"      # browser or websocket
    account_mode: str = "PRACTICE"
    selected_asset: str = ""
    candle_period: int = 60
    trade_duration: int = 120
    trade_amount: float = 5.0

@dataclass(slots=True)
class StrategySettings:
    """Signal analysis parameters"""
    fast_ema: int = 9
    slow_ema: int = 21
    rsi_period: int = 14
    min_confidence: float = 0.56
    auto_trade_enabled: bool = False
    deep_scan_min_confidence: float = 0.50
    preferred_expiry_seconds: int = 120
    sticky_signal_seconds: int = 75
    learning_enabled: bool = False
    learning_interval_seconds: int = 45
    learning_verify_seconds: int = 120

@dataclass(slots=True)
class RiskSettings:
    """Trade guardrails"""
    stop_profit: float = 30.0
    stop_loss: float = 20.0
    max_consecutive_losses: int = 3
    cooldown_seconds: int = 90
    max_open_trades: int = 1

@dataclass(slots=True)
class UiSettings:
    """UI preferences"""
    auto_refresh_seconds: int = 3
    show_warming_pairs: bool = True

@dataclass(slots=True)
class TelegramSettings:
    """Telegram bot configuration"""
    enabled: bool = False
    bot_token: str = ""
    engine_name: str = "Eternal AI Bot (Apex Engine v214)"
    start_title: str = "Eternal AI Bot (Apex Engine v214)"
    start_message: str = "Choose a pair, review the market..."
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
    # Broker credentials for Telegram
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
    """License validation configuration"""
    enabled: bool = False
    api_url: str = ""
    api_token: str = ""
    license_key: str = ""
    remember_license_key: bool = False
    poll_seconds: int = 30
    machine_lock_enabled: bool = True
    provider_name: str = "custom"
    status_text: str = "License disabled"
    last_checked_at: float = 0.0
    cache_valid_until: float = 0.0
    cached_validation_status: str = ""

@dataclass(slots=True)
class AppSettings:
    """Root settings container"""
    connection: ConnectionProfile = field(default_factory=ConnectionProfile)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    matrix: MatrixSettings = field(default_factory=MatrixSettings)
    license: LicenseSettings = field(default_factory=LicenseSettings)
```

---

### 3.2 controller.py - Main Orchestrator

**Purpose:** Central controller that coordinates all application components

**Size:** 108.5 KB (largest logic file)

**Key Responsibilities:**
- Backend lifecycle management
- Asset fetching and market data updates
- Signal generation and deep scan operations
- Trade execution and automation
- Telegram bot integration
- License validation and polling
- Learning system management
- Matrix orchestrator coordination

**Class:** `BotController(QObject)`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `async connect()` | Connect to broker backend | 443-550 |
| `disconnect_backend()` | Disconnect from backend | 552-575 |
| `place_trade(action, source, duration)` | Execute trade | 576-596 |
| `_on_trade_opened(ticket)` | Post-trade setup | 598-620 |
| `_on_trade_resolved(ticket)` | Result processing | 622-650 |
| `async fetch_assets()` | Update asset list | 652-700 |
| `async refresh_market()` | Update prices | 702-730 |
| `_run_deep_scan()` | Trigger deep scan | 1450-1700 |
| `deep_scan_all()` | Public deep scan entry | 1400-1450 |
| `validate_license()` | License verification | 800-850 |
| `_poll_learning_loop()` | Adaptive learning | 1261-1372 |
| `update_tick_buffer(symbol, price, timestamp)` | Ingest price tick | 2019-2057 |
| `_handle_async_error(error)` | Central error handler | 1192-1214 |
| `_on_deep_scan_error(error)` | Deep scan error handler | 2183-2205 |
| `_asset_changed()` | Asset selection handler | 900-950 |
| `_connect_clicked()` | Connect button handler | 850-900 |
| `_toggle_automation()` | Auto-trade toggle | 1100-1120 |
| `_continuous_monitor_toggled()` | Monitor toggle | 1120-1140 |

**Signals:**
- `connection_changed(bool)` - Connection status
- `signal_changed(StrategyDecision)` - New signal
- `candles_changed(list[Candle])` - New candles
- `trade_completed(TradeTicket)` - Trade result
- `trade_failed(str)` - Trade error
- `status_message(str)` - Status update

**Threading:**
- Uses `AsyncRunner` for async operations on separate event loop
- Prevents UI blocking during network operations

---

### 3.3 backend/base.py - Abstract Interface

**Purpose:** Define the TradingBackend abstract interface

**Class:** `TradingBackend(ABC)`

**Abstract Methods:**
```python
@abstractmethod
async def connect(self, **kwargs) -> bool: ...

@abstractmethod
async def disconnect(self) -> None: ...

@abstractmethod
async def fetch_assets(self) -> list[AssetInfo]: ...

@abstractmethod
async def fetch_candles(self, symbol: str, period: int, count: int) -> list[Candle]: ...

@abstractmethod
async def place_trade(self, symbol: str, action: str, amount: float, duration: int) -> TradeTicket: ...

@abstractmethod
async def get_account(self) -> AccountSnapshot: ...

@abstractmethod
def set_selected_asset(self, symbol: str) -> None: ...
```

---

### 3.4 backend/live.py - Live Quotex Trading

**Purpose:** Real-time trading via browser automation

**Size:** 341.5 KB (largest file)

**Key Components:**

**Class:** `LiveQuotexBackend(TradingBackend)`

**Features:**
- Browser automation via Selenium/Playwright
- Chrome driver management with undetected_chromedriver
- WebSocket pool for alternative data sources
- Browser bridge client for direct price/candle streaming
- Parallel candle fetching with async locks
- Tick caching and fallback mechanisms
- Price normalization (Broker display symbols ↔ OTC symbols)
- External market feed integration (Twelve Data API)
- OTC-specific pricing corrections
- Session caching with pickle

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `async connect()` | Browser login | 200-400 |
| `async disconnect()` | Close browser | 402-420 |
| `async fetch_assets()` | Get market pairs | 450-500 |
| `async fetch_candles()` | Get historical candles | 502-600 |
| `async place_trade()` | Execute trade via browser | 602-700 |
| `async get_account()` | Get balance and mode | 702-720 |
| `_load_session_cache()` | Load cached cookies | 422-431 |
| `_save_session_cache(payload)` | Save session | 434-443 |
| `_session_cache_file()` | Get cache path | 375-377 |
| `_write_live_diagnostics()` | Debug snapshots | 6189-6232 |

**Browser Bridge Client:**
```python
class _BrowserBridgeClient:
    """Direct WebSocket link to Quotex market data"""
    - Connects to Quotex WebSocket
    - Streams prices in real-time
    - Handles reconnection
    - Provides candle data
```

**Session Management:**
- Cache file: `quotex_session.pkl`
- Stores: cookies, SSID, user_agent, wss_url, headers
- Reused on next login to skip authentication

**Price Normalization:**
- Maps broker display symbols to internal OTC symbols
- Handles symbol variations (EURUSD vs EUR/USD vs eur_usd)
- Applies OTC-specific pricing corrections

---

### 3.5 backend/mock.py - Offline Testing

**Purpose:** Sandbox mode for testing without real money

**Features:**
- Simulated price movement with realistic bias
- Default assets: EURUSD, GBPUSD, USDJPY, XAUUSD, EURUSD_otc
- Mock trade execution with profit/loss simulation
- No network required

---

### 3.6 backend/external.py - Multi-Broker Support

**Purpose:** Support for IQ Option, Exness, and multi-broker orchestration

**Supported Integrations:**
1. **IQ Option / Pocket Option** - Playwright browser automation
2. **Exness** - Twelve Data Forex API
3. **Multi-Broker** - Orchestrates across multiple brokers

**Features:**
- Exness: 65+ forex pairs via Twelve Data API
- Dynamic broker selection
- Unified asset catalog across brokers

---

### 3.7 advanced_signal_engine.py - 15-Indicator Engine

**Purpose:** Comprehensive signal analysis with weighted voting

**Size:** 22.0 KB

**Class:** `AdvancedSignalEngine`

**15 Indicators:**

| # | Indicator | Weight | Purpose |
|---|-----------|--------|---------|
| 1 | EMA Fast/Slow (9/21) | 4.0 | Trend crossover |
| 2 | EMA 50 | 3.0 | Medium-term trend |
| 3 | RSI (14) | 3.0 | Overbought/Oversold |
| 4 | MACD (12/26/9) | 3.5 | Momentum |
| 5 | Bollinger Bands (20) | 2.5 | Volatility |
| 6 | Stochastic (14/3) | 2.5 | Momentum oscillator |
| 7 | Williams %R (14) | 2.0 | Overbought/Oversold |
| 8 | CCI (20) | 2.0 | Commodity Channel Index |
| 9 | MFI (14) | 1.5 | Money Flow Index |
| 10 | VWAP | 2.5 | Volume-weighted price |
| 11 | Momentum (5) | 2.0 | Recent direction |
| 12 | Candle Structure | 2.5 | Body/close analysis |
| 13 | Parabolic SAR | 2.0 | Trend direction |
| 14 | Engulfing Pattern | 2.5 | Reversal pattern |
| 15 | Pin Bar | 2.0 | Reversal pattern |

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `_analyze_comprehensive(candles)` | Main 15-indicator engine | 367-686 |
| `analyze(candles)` | Public entry point | 695-698 |
| `_ema(values, period)` | Exponential MA | 40-50 |
| `_rsi(closes, period)` | Relative Strength Index | 53-73 |
| `_macd(closes, fast, slow, signal)` | MACD | 76-101 |
| `_bollinger_bands(closes, period, std_mult)` | BB | 104-120 |
| `_stochastic(candles, k_period, d_period)` | Stochastic | 123-140 |
| `_williams_r(candles, period)` | Williams %R | 143-157 |
| `_cci(candles, period)` | CCI | 160-173 |
| `_atr(candles, period)` | Average True Range | 176-193 |
| `_adx(candles, period)` | ADX | 196-232 |
| `_mfi(candles, period)` | Money Flow Index | 235-254 |
| `_detect_engulfing(candles)` | Engulfing pattern | 257-270 |
| `_detect_pin_bar(candles)` | Pin bar pattern | 273-286 |
| `_detect_doji(candles)` | Doji pattern | 289-298 |
| `_vwap(candles)` | VWAP | 301-309 |
| `_momentum_score(candles, lookback)` | Momentum | 312-323 |
| `_parabolic_sar(candles)` | Parabolic SAR | 326-364 |

**SignalResult Dataclass:**
```python
@dataclass
class SignalResult:
    action: str           # CALL or PUT
    confidence: float     # 0.0 to 1.0
    indicator_count: int  # Number of indicators used
    trend_strength: float # ADX value
    pattern_detected: str # Detected patterns
    rsi: float
    macd: float
```

---

### 3.8 sniper_scan.py - Deep Scan v1

**Purpose:** High-confidence single signal with OTC-specific analysis

**Size:** 34.4 KB

**Class:** `SniperScanner`

**Key Features:**
- Multi-timeframe confirmation (1m, 2m, 5m candles)
- OTC-specific pattern detection (repeating tick sequences)
- Tick momentum analysis (last 20 ticks trend)
- Support/Resistance bounce detection
- 15-indicator voting system

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `scan(symbol)` | Single pair deep scan | 579-614 |
| `_scan_with_candles(target, candles, price)` | Full analysis | 616-754 |
| `_scan_with_ticks(target, price)` | Tick fallback | 756-885 |
| `scan_all()` | Scan all pairs | 891-896 |
| `best_signal()` | Return best signal | 902-916 |
| `to_strategy_decision(signal)` | Convert format | 974-999 |
| `_detect_repeating_patterns(prices, min_len, max_len, tolerance)` | OTC patterns | 103-164 |
| `_tick_momentum_analysis(prices, lookback)` | Momentum | 171-209 |
| `_sr_bounce_analysis(candles, support, resistance, tolerance_pct)` | S/R bounce | 216-253 |
| `_score_indicators(candles, closes, signal)` | 15-indicator scoring | 260-527 |

**SniperSignal Dataclass:**
```python
@dataclass
class SniperSignal:
    symbol: str
    action: str
    confidence: float
    expiry_seconds: int
    entry_price: float
    rsi: float
    trend_strength: float
    indicators_used: list[str]
    pattern_detected: str
    multi_timeframe_aligned: bool
```

---

### 3.9 broadcast_scan.py - Deep Scan v2

**Purpose:** Multi-pair parallel scanning for Telegram distribution

**Size:** 9.4 KB

**Class:** `BroadcastScanner`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `scan_all()` | Parallel multi-pair scan | 182-223 |
| `scan_single(pair)` | Analyze single pair | 225-240 |
| `_analyze_pair(pair)` | 12-indicator evaluation | 242-263 |
| `update_pairs/add_pair/remove_pair()` | Pair management | 265-277 |

**BroadcastResult Dataclass:**
```python
@dataclass
class BroadcastResult:
    signals: list[BroadcastSignal]
    scanned_pairs: int
    pairs_with_data: int
    scan_timestamp: float
    scan_duration_ms: float

    def format_telegram_message(engine_name: str) -> str: ...
```

---

### 3.10 learning.py - Adaptive Learning

**Purpose:** Self-improving confidence based on trade outcomes

**Size:** 18.0 KB

**Class:** `SignalLearner`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `create_probe(signal, context)` | Create learning probe | 231-252 |
| `settle_probe(probe_id, result_price)` | Determine win/loss | 382-411 |
| `adjusted_confidence(signal, context)` | Apply learning | 165-229 |
| `_apply_outcome_update(probe, outcome)` | Update weights | 280-380 |
| `save()` | Persist to JSON | 117-119 |
| `load()` | Load from JSON | 110-115 |

**Learning Algorithm:**
```
1. Create probe with feature vector:
   - confidence, trend_strength, rsi_bias, payout
   - expiry_bias, body_bias, call_bias, put_bias, bias

2. Wait for verify_at time

3. Settle probe:
   - Fetch price at verify time
   - Compare to reference_price
   - CALL: result > reference -> win
   - PUT: result < reference -> win

4. Update weights:
   - learning_rate = 0.14-0.32
   - weight += lr * (target - prediction) * feature_value
   - Clamp weights to [-3.0, 3.0]

5. Update statistics:
   - asset_stats: win/loss per asset
   - context_stats: win/loss per context
   - Track streaks

6. Save to signal_learner.json
```

**Persistence:**
- File: `cache/signal_learner.json`
- Stores: weights, biases, asset_stats, context_stats, recent trades

---

### 3.11 tick_buffer.py - Real-Time Candle Building

**Purpose:** Build candles from real-time tick prices

**Size:** 9.1 KB

**Class:** `TickBuffer`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `add_tick(symbol, price, timestamp)` | Ingest a tick | 45-63 |
| `get_candles(symbol, count, period)` | Build OHLCV candles | 65-125 |
| `get_multi_timeframe_candles(symbol)` | Get 1m/2m/5m candles | 127-150 |
| `get_momentum(symbol, lookback)` | Linear regression momentum | 152-170 |
| `get_volatility(symbol, lookback)` | Average % change | 172-185 |
| `get_support_resistance(symbol, lookback)` | 5th/95th percentile | 187-200 |

**Candle Generation Algorithm:**
```
1. Group ticks by time buckets (1min/2min/5min)
2. For each completed bucket:
   - Open: first tick price
   - High: max tick price
   - Low: min tick price
   - Close: last tick price
   - Volume: tick count
3. Exclude currently forming candle
4. Return up to N completed candles
```

---

### 3.12 automation.py - Auto-Trade Logic

**Purpose:** Risk-managed automatic trading

**Size:** 2.5 KB

**Class:** `AutomationEngine`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `can_trade(decision)` | Check if trade allowed | 22-40 |
| `register_open(ticket)` | Record trade opened | 42-48 |
| `register_result(ticket)` | Record trade result | 50-60 |

**can_trade() Logic:**
```python
def can_trade(self, decision) -> tuple[bool, str]:
    # ALL 8 conditions must pass:
    if not self.enabled:
        return False, "Automation disabled"
    if self.active_trade_id is not None:
        return False, "Trade already open"
    if decision.action == "HOLD":
        return False, "Signal is HOLD"
    if decision.confidence < self.min_confidence:
        return False, f"Confidence {decision.confidence:.2f} < {self.min_confidence:.2f}"
    if self.net_pnl >= self.stop_profit:
        return False, f"Stop profit reached: {self.net_pnl:.2f}"
    if self.net_pnl <= -self.stop_loss:
        return False, f"Stop loss reached: {self.net_pnl:.2f}"
    if self.consecutive_losses >= self.max_consecutive_losses:
        return False, f"Max consecutive losses: {self.consecutive_losses}"
    if (now - self.last_trade_at) < self.cooldown_seconds:
        return False, f"Cooldown active"
    return True, "OK"
```

---

### 3.13 licensing.py - License Validation

**Purpose:** Server-side license validation with machine locking

**Size:** 21.7 KB

**Components:**

**Class:** `LicenseClient`
- POST to license API endpoint
- Sends: license_key, machine_id, machine_fingerprint, app
- Receives: valid, status, expires_at, machine_id, reason

**Class:** `LicenseRateLimiter`
- Prevents brute force: 4 attempts -> escalating cooldown
- Cooldown: 2, 5, 10, 20, 30+ minutes
- Stores lockout state in JSON file

**Class:** `LicenseAttemptTracker`
- File: `license_attempts.json`
- Tracks: attempt count, lockout count, timestamp

**Machine Fingerprinting:**
- `machine_display_id()` - User-friendly machine name
- `machine_fingerprint()` - Crypto hash of hardware
- `machine_fernet_key()` - Encryption key derivation

**License Flow:**
```
1. User enters license key
2. Client validates with server
3. Server checks:
   - Key exists and active
   - Not expired
   - Machine match (if locked)
4. Server returns valid/invalid
5. Client caches result
6. Poll every 30 seconds to revalidate
```

---

### 3.14 telegram_bot.py - Telegram Integration

**Purpose:** Remote signal access via Telegram

**Size:** 76.8 KB (second largest file)

**Class:** `TelegramBotService`

**Key Methods:**

| Method | Purpose | Lines |
|--------|---------|-------|
| `start()` | Start bot polling | 700-750 |
| `stop()` | Stop bot | 752-760 |
| `_process_update(update)` | Route messages | 800-900 |
| `_send_welcome()` | Welcome message | 1041-1042 |
| `_deliver_signal()` | Send signal to user | 1102-1108 |
| `_deep_scan_market()` | Market-wide scan | 1127-1133 |
| `broadcast_signal_with_chart()` | Broadcast to all users | 1885-1955 |
| `send_message_to_all()` | Broadcast arbitrary message | 1957-1966 |
| `_send_admin_panel()` | Admin panel | 1094-1098 |
| `_send_admin_status()` | System status | 1148-1151 |
| `_send_admin_stats()` | Statistics | 1158-1161 |
| `_send_message_users()` | Message users | 1168-1171 |

**User Management:**
```python
@dataclass
class UserUsage:
    chat_id: int
    tier: str  # FREE, PREMIUM, ADMIN
    daily_signals: int
    cooldown_pairs: dict[str, float]

@dataclass
class SignalHistoryEntry:
    chat_id: int
    pair: str
    action: str
    confidence: float
    scan_type: str
    time: float
    win: bool | None
```

**Constants:**
- `FREE_DAILY_LIMIT = 15` signals per day
- `COOLDOWN_SECONDS = 30` between same pair scans
- `MAX_HISTORY = 500` history entries
- `MAX_KNOWN_USERS = 200`

---

### 3.15 ui/main_window.py - User Interface

**Purpose:** 13-tab desktop interface

**Size:** 178.4 KB (largest UI file)

**Framework:** PySide6 (Qt6)

**Tabs:**

| Tab | Key | Builder Method |
|-----|-----|---------------|
| Markets | markets | `_build_dashboard_page()` |
| Chart Studio | charts | `_build_chart_studio_page()` |
| Strategy AI | strategy | `_build_strategy_page()` |
| Live | live | `_build_live_page()` |
| Telegram | telegram | `_build_telegram_page()` |
| Deep Scan | deep_scan | `_build_deep_scan_page()` |
| Signal Format | signal_format | `_build_signal_format_page()` |
| Auto Trading | auto_trading | `_build_auto_trading_page()` |
| Auto History | auto_history | `_build_history_page()` |
| Pine Editor | pine_editor | `_build_pine_editor_page()` |
| Log | log | `_build_log_page()` |
| Settings | settings | Various |
| Admin | admin | `_build_admin_panel_page()` |

**Key Components:**
- Signal display with color coding (green=CALL, red=PUT, yellow=HOLD)
- Confidence percentage and trend indicator
- Chart rendering with mplfinance integration
- Real-time clock
- Status bar with connection indicator

**Event Handlers:**
- Asset selection -> `_asset_changed()`
- Period change -> `_period_changed()`
- Connect -> `_connect_clicked()`
- Disconnect -> `controller.disconnect_backend()`
- Engine button -> `_engine_button_clicked()`
- Deep Scan -> `controller.deep_scan_all()`
- Buy/Sell -> `_submit_manual_trade("CALL"/"PUT")`
- Auto trade toggle -> `_toggle_automation()`
- Continuous monitor -> `_continuous_monitor_toggled()`
- Telegram settings -> `_update_telegram_preview()`

---

### 3.16 ui/charts.py - Chart Rendering

**Purpose:** OHLCV candlestick chart generation

**Size:** 9.2 KB

**Key Function:**
```python
def render_signal_chart(candles, signal_action, confidence, symbol, entry_price) -> str:
    """
    Generates PNG chart for Telegram sharing
    Uses mplfinance for professional OHLC display
    Adds signal entry point marker
    Displays confidence percentage
    Returns file path
    """
```

**Features:**
- OHLC candlestick chart
- Volume bars (optional)
- EMA overlays (fast/slow)
- Signal marker (green arrow for CALL, red for PUT)
- Entry price line
- Title with symbol, timeframe, action, confidence%

---

### 3.17 settings.py - Settings Persistence

**Purpose:** Save/load application settings

**Size:** 11.5 KB

**Class:** `SettingsStore`

**Features:**
- Saves to: `%LOCALAPPDATA%\EternalQuotexBot\settings.json`
- JSON-based persistence
- Automatic encryption for sensitive fields (passwords, PINs)
- Fernet (symmetric encryption) using machine-derived key
- Fallback defaults if corrupted

**Save Operation:**
```python
def save(self) -> None:
    payload = {
        "connection": asdict(self.settings.connection),
        "strategy": asdict(self.settings.strategy),
        "risk": asdict(self.settings.risk),
        "ui": asdict(self.settings.ui),
        "telegram": asdict(self.settings.telegram),
        "matrix": asdict(self.settings.matrix),
        "license": asdict(self.settings.license),
    }
    # Encrypt sensitive fields
    self._encrypt_sensitive_fields(payload)
    # Write to file
    self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

**Encrypted Fields:**
- Passwords (all broker credentials)
- Email PINs
- Bot token
- License key
- API tokens

---

### 3.18 paths.py - Directory Management

**Purpose:** Manage application data directories

**Size:** 1.7 KB

**Key Functions:**

| Function | Returns |
|----------|---------|
| `app_data_dir()` | `%LOCALAPPDATA%\EternalQuotexBot` |
| `runtime_dir()` | `%LOCALAPPDATA%\EternalQuotexBot\runtime` |
| `cache_dir()` | `%LOCALAPPDATA%\EternalQuotexBot\cache` |
| `settings_file()` | `app_data_dir() / "settings.json"` |
| `log_file()` | `app_data_dir() / "activity.log"` |

**Environment Override:**
- `ETERNAL_QUOTEX_BOT_DATA_DIR` - Custom data directory path

---

### 3.19 matrix_orchestrator.py - Multi-Account Automation

**Purpose:** Automated trading across multiple accounts

**Size:** 20.7 KB

**Class:** `MatrixOrchestrator`

**Features:**
- Creates worker threads per account
- Shares signal from primary
- Executes independently on each worker
- Aggregates results
- Error isolation per worker

**Workflow:**
```
1. Initialize workers from MatrixSettings
2. For each enabled worker:
   - Connect to broker
   - Wait for signal from primary
   - Execute trade independently
3. Aggregate results:
   - Total wins, losses
   - Per-account performance
   - Combined PNL
4. Handle errors per worker independently
```

---

### 3.20 ws_worker_pool.py - WebSocket Pool

**Purpose:** Manage concurrent WebSocket connections

**Size:** 17.8 KB

**Features:**
- Multiple WS connections for redundancy
- Fallback data source when browser fails
- Manages connection lifecycle
- Reconnection logic

---

### 3.21 pine_script.py - TradingView Integration

**Purpose:** Custom indicator support via Pine Script

**Size:** 25.4 KB

**Features:**
- Pine Script syntax parsing
- Generate Python equivalent
- Apply to chart as overlay
- Save/Load scripts
- Run backtests

---

## 4. ERROR HANDLING PATTERNS

### 4.1 Central Error Handler

**File:** `controller.py`, `_handle_async_error()` [lines 1192-1214]

```python
def _handle_async_error(self, error: BaseException):
    error_msg = str(error)
    # Clear all busy flags
    self.scan_in_progress = False
    self.learning_busy = False
    self.connecting = False
    # Stop timers if not connected
    if not self.connected:
        self._stop_timers()
        # Disconnect backend (except during PIN flow)
        if not self.pin_flow_active:
            self.backend.disconnect()
    # Emit signals
    self.connection_changed.emit(False)
    self.log_error(f"Error: {error_msg}")
    self.status_message.emit(f"Error: {error_msg}")
```

### 4.2 Deep Scan Error Handler

**File:** `controller.py`, `_on_deep_scan_error()` [lines 2183-2205]

```python
def _on_deep_scan_error(self, error: BaseException):
    # Capture full traceback
    tb = traceback.format_exc()
    self.log_error(f"Deep scan error:\n{tb}")
    # Clear flags
    self.scan_in_progress = False
    # Emit error result
    self.deep_scan_result.emit({
        "scanned": 0,
        "rows": [],
        "error": str(error)
    })
    # Update UI
    self.status_message.emit("Deep scan failed")
```

### 4.3 Fallback Chains

**Signal Evaluation Fallback:**
```
1. Advanced engine analyze() (preferred)
2. Standard evaluate_signal() (fallback on exception)
3. Tick momentum analysis (no candles)
4. Neutral HOLD (no data at all)
```

**Candle Cache Fallback:**
```
1. Check local controller cache
2. Check backend candle_cache
3. Check backend._get_cached_candles method
4. Return whatever is available (even if empty)
```

**Telegram API Fallback:**
```
1. Normal API call with 35s timeout
2. Retry with exponential backoff (1s -> 10s max)
3. On SSLError: retry without SSL verification
4. On edit failure: send new message instead
```

---

## 5. CONFIGURATION FILES

### 5.1 Settings File

**Location:** `%LOCALAPPDATA%\EternalQuotexBot\settings.json`

**Structure:**
```json
{
  "connection": {
    "provider": "quotex",
    "email": "user@example.com",
    "password": "<encrypted>",
    "primary_broker": "quotex",
    "account_mode": "PRACTICE",
    "candle_period": 60,
    "trade_duration": 120,
    "trade_amount": 5.0
  },
  "strategy": {
    "fast_ema": 9,
    "slow_ema": 21,
    "rsi_period": 14,
    "min_confidence": 0.56,
    "auto_trade_enabled": false,
    "learning_enabled": false
  },
  "risk": {
    "stop_profit": 30.0,
    "stop_loss": 20.0,
    "max_consecutive_losses": 3,
    "cooldown_seconds": 90
  },
  "telegram": {
    "enabled": false,
    "bot_token": "<encrypted>",
    "engine_name": "Eternal AI Bot (Apex Engine v214)"
  },
  "license": {
    "enabled": false,
    "api_url": "https://vxwfmqvjwjxlrfskopts.supabase.co/functions/v1/license-validate",
    "license_key": "<encrypted>",
    "poll_seconds": 30,
    "machine_lock_enabled": true
  }
}
```

### 5.2 Supabase License Schema

**File:** `supabase/sql/license_schema.sql`

```sql
CREATE TABLE licenses (
    license_key VARCHAR PRIMARY KEY,
    user_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'active',  -- active, disabled, revoked, expired
    expires_at TIMESTAMP WITH TIME ZONE,
    machine_lock BOOLEAN DEFAULT false,
    machine_id VARCHAR,
    machine_fingerprint VARCHAR,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 5.3 Supabase Config

**File:** `supabase/config.toml`

```toml
[functions.license-validate]
verify_jwt = false  # Allow public validation
```

---

## 6. BUILD SYSTEM

### 6.1 PyInstaller Build

**Script:** `build_exe.ps1`

**Process:**
```
1. Install dependencies: pip install -r requirements.txt
2. Run PyInstaller:
   pyinstaller --name "Eternal Quotex Bot" ^
               --windowed ^
               --onefile ^
               --icon=icon.ico ^
               --add-data "eternal_quotex_bot;eternal_quotex_bot" ^
               main.py
3. Output: dist_rebuild/Eternal Quotex Bot/Eternal Quotex Bot.exe
```

### 6.2 Launcher

**File:** `run_eternal_quotex_bot.py`

**Purpose:** PyInstaller launcher that loads bundled packages

---

## 7. DEPENDENCIES

### 7.1 Core Dependencies

| Package | Purpose |
|---------|---------|
| PySide6 | Qt6 desktop UI framework |
| quotexpy | Quotex API client (patched at runtime) |
| selenium | Browser automation |
| playwright | Modern browser automation |
| undetected_chromedriver | Anti-detection Chrome driver |
| pandas | Data analysis (indicators) |
| mplfinance | OHLC charting |
| requests | HTTP client |
| beautifulsoup4 | HTML parsing |
| cryptography | Fernet encryption |
| websockets | WebSocket protocol |

### 7.2 Development Dependencies

| Package | Purpose |
|---------|---------|
| pytest | Unit testing |
| pyinstaller | Executable packaging |

---

## 8. DATA FLOW DIAGRAMS

### 8.1 Complete Data Flow

```
User Input / Price Stream
         |
         v
+-------------------+
|   Backend Layer   |
| (Live/Mock/Ext)   |
+-------------------+
         |
         v (ticks/candles)
+-------------------+
|   Tick Buffer     |
|  (Candle Builder) |
+-------------------+
         |
         v (candles)
+-------------------+
|  Signal Engines   |
| (Advanced/Sniper) |
+-------------------+
         |
         v (StrategyDecision)
+-------------------+
|  Learning System  |
| (Confidence Adj)  |
+-------------------+
         |
         v (adjusted decision)
+-------------------+
|   Automation      |
|  (Risk Checks)    |
+-------------------+
         |
    +----+----+
    |         |
    v         v
+------+  +--------+
|Trade |  | UI/    |
|Exec  |  |Telegram|
+------+  +--------+
    |         |
    v         v
+--------+  +--------+
|Result  |  |Message |
|Record  |  |History |
+--------+  +--------+
    |
    v
+--------+
|Learning|
|Feedback|
+--------+
```

### 8.2 Signal Generation Flow

```
Candles Available
    |
    v
+------------------+
| Indicator Calc   |
| (15 indicators)  |
+------------------+
    |
    v (scores)
+------------------+
| Weighted Voting  |
| (CALL vs PUT)    |
+------------------+
    |
    v (dominance)
+------------------+
| Confidence Calc  |
| (0.48 + dom*0.32)|
+------------------+
    |
    v (raw confidence)
+------------------+
| Learning Adjust  |
| (Historical perf)|
+------------------+
    |
    v (adjusted confidence)
+------------------+
| Duration Select  |
| (Trend strength) |
+------------------+
    |
    v
StrategyDecision
```

### 8.3 Trade Execution Flow

```
Signal Qualified
    |
    v
+------------------+
| Risk Check       |
| (8 conditions)   |
+------------------+
    |
    v (pass)
+------------------+
| Place Trade      |
| (Backend API)    |
+------------------+
    |
    v (ticket)
+------------------+
| Register Open    |
| (Track in stats) |
+------------------+
    |
    v
+------------------+
| Create Probe     |
| (Learning record)|
+------------------+
    |
    v (wait duration)
+------------------+
| Check Result     |
| (Poll backend)   |
+------------------+
    |
    v (win/loss)
+------------------+
| Record Outcome   |
| (Update weights) |
+------------------+
    |
    v
Update Stats & UI
```

---

## 9. TESTING STRATEGY

### 9.1 Unit Tests

**Location:** `eternal_quotex_bot/tests/`

**Test Coverage:**
- Signal engine accuracy
- Candle generation from ticks
- Risk management logic
- Learning weight updates
- Settings persistence

### 9.2 Mock Backend Testing

**Use Case:** Test without real money or network

```python
# Use mock provider for safe testing
controller.connect(provider="mock")
# Run strategies, test signals, verify logic
```

### 9.3 Sandbox Mode

**Recommendation:** Always test new features in PRACTICE mode first

---

## 10. SECURITY CONSIDERATIONS

### 10.1 Credential Storage

- All passwords encrypted with Fernet
- Machine-derived encryption key
- Never stored in plaintext

### 10.2 License Protection

- Machine fingerprinting prevents sharing
- Rate limiting prevents brute force
- Server-side validation required

### 10.3 API Tokens

- Never hardcoded in source
- Stored in settings with encryption
- Rotated as needed

---

## 11. PERFORMANCE OPTIMIZATIONS

### 11.1 Parallel Candle Fetch

```python
# Fetch candles for all pairs concurrently
tasks = [fetch_candles(pair) for pair in pairs]
results = await asyncio.gather(*tasks, return_exceptions=True)
# Per-pair timeout prevents slow pairs from blocking others
```

### 11.2 Signal Caching

- Last analysis cached to avoid redundant computation
- Invalidated on new candle or parameter change

### 11.3 WebSocket Pool

- Multiple concurrent WS connections
- Fallback when primary fails
- Automatic reconnection

### 11.4 UI Update Throttling

- Debounce rapid updates
- Prevent UI freezing during heavy computation
- Use async operations for network calls

---

## 12. EXTENSION POINTS

### 12.1 Adding New Broker

1. Create new backend class inheriting `TradingBackend`
2. Implement all abstract methods
3. Register in controller backend selector
4. Add credentials to `ConnectionProfile`

### 12.2 Adding New Indicator

1. Add calculation function to signal engine
2. Add weight to voting system
3. Update indicator count in documentation
4. Test with historical data

### 12.3 Adding New Telegram Command

1. Add callback handler in `telegram_bot.py`
2. Route callback data in `_process_update()`
3. Add button to keyboard layout
4. Test with bot

---

## 13. TROUBLESHOOTING GUIDE

### 13.1 Connection Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| Login fails | Wrong credentials | Check email/password in settings |
| Browser won't open | Chrome driver issue | Reinstall undetected_chromedriver |
| PIN required | 2FA enabled | Enter PIN in UI dialog |
| Session expired | Cache invalid | Re-authenticate |

### 13.2 Signal Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| HOLD always | Insufficient candles | Wait for more data |
| Low confidence | Mixed indicators | Adjust EMA/RSI settings |
| No signals | Deep scan not running | Check backend connection |

### 13.3 Trade Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| Trade rejected | Risk guardrails | Check stop-loss, cooldown |
| Trade failed | Backend error | Retry, check connection |
| Wrong amount | Settings mismatch | Update trade_amount |

### 13.4 Telegram Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| Bot not responding | Invalid token | Check bot_token |
| Rate limited | Too many requests | Wait for cooldown |
| Images not sending | Chart render fail | Check mplfinance |

---

## 14. QUICK REFERENCE

### 14.1 File Sizes

| File | Size | Purpose |
|------|------|---------|
| backend/live.py | 341.5 KB | Live trading |
| ui/main_window.py | 178.4 KB | Main UI |
| controller.py | 108.5 KB | Orchestrator |
| telegram_bot.py | 76.8 KB | Telegram bot |
| sniper_scan.py | 34.4 KB | Deep scan v1 |
| glassmorphism_theme.py | 30.0 KB | UI theme |
| pine_script.py | 25.4 KB | Custom indicators |
| advanced_signal_engine.py | 22.0 KB | 15-indicator engine |
| licensing.py | 21.7 KB | License validation |
| matrix_orchestrator.py | 20.7 KB | Multi-account |
| strategy.py | 18.3 KB | Signal engine |
| learning.py | 18.0 KB | Adaptive learning |
| chart_renderer.py | 17.3 KB | Chart generation |
| ws_worker_pool.py | 17.8 KB | WebSocket pool |
| visual_signals.py | 16.1 KB | Signal formatting |
| pw_price_pool.py | 13.7 KB | Price caching |
| controller_deep_scan_new.py | 13.7 KB | Deep scan |
| apex_analysis.py | 14.0 KB | Apex engine |
| settings.py | 11.5 KB | Persistence |
| broadcast_scan.py | 9.4 KB | Deep scan v2 |
| tick_buffer.py | 9.1 KB | Candle builder |
| ui/charts.py | 9.2 KB | Chart rendering |
| broker_adapters.py | 9.3 KB | Broker wrappers |
| backend/external.py | 69.0 KB | Multi-broker |

### 14.2 Key Constants

| Constant | Value | Location |
|----------|-------|----------|
| FREE_DAILY_LIMIT | 15 | telegram_bot.py |
| COOLDOWN_SECONDS | 30 | telegram_bot.py |
| MAX_HISTORY | 500 | telegram_bot.py |
| MAX_KNOWN_USERS | 200 | telegram_bot.py |
| DEFAULT_FAST_EMA | 9 | models.py |
| DEFAULT_SLOW_EMA | 21 | models.py |
| DEFAULT_RSI_PERIOD | 14 | models.py |
| DEFAULT_MIN_CONFIDENCE | 0.56 | models.py |
| DEFAULT_STOP_PROFIT | 30.0 | models.py |
| DEFAULT_STOP_LOSS | 20.0 | models.py |
| DEFAULT_COOLDOWN | 90 | models.py |
| DEFAULT_DURATION | 120 | models.py |
| DEFAULT_AMOUNT | 5.0 | models.py |

---

## 15. APPENDIX

### 15.1 Indicator Formulas

**Exponential Moving Average (EMA):**
```
EMA = (Close - Previous_EMA) * (2 / (period + 1)) + Previous_EMA
```

**Relative Strength Index (RSI):**
```
RS = Average Gain / Average Loss
RSI = 100 - (100 / (1 + RS))
```

**Moving Average Convergence Divergence (MACD):**
```
MACD Line = EMA(12) - EMA(26)
Signal Line = EMA(9) of MACD Line
Histogram = MACD Line - Signal Line
```

**Bollinger Bands:**
```
Middle Band = SMA(20)
Upper Band = Middle + (2 * StdDev(20))
Lower Band = Middle - (2 * StdDev(20))
```

**Stochastic Oscillator:**
```
%K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100
%D = SMA(%K, 3)
```

**Average Directional Index (ADX):**
```
+DI = +DM / ATR * 100
-DI = -DM / ATR * 100
DX = |+DI - -DI| / |+DI + -DI| * 100
ADX = SMA(DX, 14)
```

### 15.2 OTC Symbol Mapping

| Display Symbol | Internal Symbol |
|---------------|-----------------|
| EUR/USD | EURUSD_otc |
| GBP/USD | GBPUSD_otc |
| USD/JPY | USDJPY_otc |
| EUR/USD (Real) | EURUSD |

### 15.3 WebSocket Events

| Event | Data | Purpose |
|-------|------|---------|
| price_update | symbol, price, timestamp | Stream live prices |
| candle_close | symbol, candle | Notify candle completion |
| trade_result | ticket_id, result, profit | Trade outcome |
| account_update | balance, mode | Account changes |

---

This documentation provides complete understanding of the Eternal Quotex Bot architecture. Use it alongside `session.json`, `memories.json`, and `logic.md` for comprehensive project knowledge.
