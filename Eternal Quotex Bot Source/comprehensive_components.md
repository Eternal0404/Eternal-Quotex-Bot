# Eternal Quotex Bot - Comprehensive Software Components Documentation

## Complete Module, Function, and Component Analysis

This document provides exhaustive detail on every software component, enabling another AI system to fully understand the architecture without requiring additional clarification.

---

## Table of Contents
1. [Application Startup and Bootstrap](#1-application-startup-and-bootstrap)
2. [Core Data Models](#2-core-data-models)
3. [Main Controller (BotController)](#3-main-controller-botcontroller)
4. [Backend Integration Layer](#4-backend-integration-layer)
5. [Signal Analysis Engines](#5-signal-analysis-engines)
6. [Trading Automation](#6-trading-automation)
7. [Learning System](#7-learning-system)
8. [Telegram Bot Integration](#8-telegram-bot-integration)
9. [User Interface Components](#9-user-interface-components)
10. [Licensing and Authentication](#10-licensing-and-authentication)
11. [Data Flow and Processing](#11-data-flow-and-processing)
12. [Utility and Support Modules](#12-utility-and-support-modules)
13. [Matrix Multi-Account System](#13-matrix-multi-account-system)
14. [Browser Automation Details](#14-browser-automation-details)
15. [WebSocket Communication](#15-websocket-communication)
16. [Configuration and Persistence](#16-configuration-and-persistence)
17. [Build and Packaging System](#17-build-and-packaging-system)
18. [Testing Infrastructure](#18-testing-infrastructure)

---

## 1. APPLICATION STARTUP AND BOOTSTRAP

### 1.1 Entry Point: `main.py`

**Location:** `Eternal Quotex Bot Source/main.py`

**Complete Code:**
```python
import multiprocessing
from eternal_quotex_bot.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
```

**Purpose:**
- `multiprocessing.freeze_support()` is critical for PyInstaller-packaged applications on Windows. It enables child processes to properly initialize when the app is frozen into an executable.
- Delegates to `app.main()` which returns an exit code.
- Uses `raise SystemExit()` instead of `sys.exit()` for cleaner process termination.

**Execution Flow:**
1. Python interpreter loads `main.py`
2. `freeze_support()` initializes multiprocessing support for frozen apps
3. Imports `main` function from `eternal_quotex_bot.app`
4. Calls `main()` which:
   - Bootstraps runtime directories
   - Creates QApplication
   - Initializes controller and main window
   - Shows license gate if enabled
   - Starts Qt event loop
5. Returns exit code to OS

### 1.2 Application Bootstrap: `app.py`

**Location:** `eternal_quotex_bot/app.py` (5.0 KB)

**Main Function Breakdown:**

```python
def main() -> int:
    # Step 1: Bootstrap runtime directories
    bootstrap_runtime()
    
    # Step 2: Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Eternal Quotex Bot")
    app.setOrganizationName("Eternal")
    
    # Step 3: Install global exception handler
    sys.excepthook = _global_exception_hook
    
    # Step 4: Create controller
    controller = BotController()
    
    # Step 5: Create and show main window
    window = MainWindow(controller)
    window.show()
    
    # Step 6: Run event loop
    return app.exec()
```

**`bootstrap_runtime()` Function:**
- Creates application data directories:
  - `%LOCALAPPDATA%\EternalQuotexBot\`
  - `%LOCALAPPDATA%\EternalQuotexBot\runtime\`
  - `%LOCALAPPDATA%\EternalQuotexBot\cache\`
  - `%LOCALAPPDATA%\EternalQuotexBot\cache\diagnostics\`
- Sets up logging to `activity.log`
- Can be overridden with `ETERNAL_QUOTEX_BOT_DATA_DIR` environment variable

**Global Exception Handler:**
```python
def _global_exception_hook(exc_type, exc_value, exc_traceback):
    # Logs unhandled exceptions
    # Shows error dialog to user
    # Prevents silent crashes
```

**Key Points:**
- The app uses PySide6 (Qt6), not PyQt5
- Exception hooks catch crashes that would otherwise terminate silently
- Runtime directories are created before any file I/O occurs

---

## 2. CORE DATA MODELS

### 2.1 Complete Models Analysis: `models.py`

**Location:** `eternal_quotex_bot/models.py` (6.4 KB)

All models use Python 3.10+ dataclasses with `slots=True` for memory efficiency.

#### Candle
```python
@dataclass(slots=True)
class Candle:
    timestamp: int          # Unix timestamp (seconds since epoch)
    open: float             # Opening price of the period
    high: float             # Highest price during the period
    low: float              # Lowest price during the period
    close: float            # Closing price of the period
    volume: float = 0.0     # Number of ticks or trading volume
```

**Usage:** Represents a single OHLCV candlestick. Created by:
- `tick_buffer.py` from real-time ticks
- Backend `fetch_candles()` from historical data
- Used by all signal engines for analysis

**Example:**
```python
Candle(timestamp=1776102563, open=96.9935, high=97.0012, low=96.9801, close=96.9946, volume=21)
```

#### AssetInfo
```python
@dataclass(slots=True)
class AssetInfo:
    symbol: str                 # Internal symbol name (e.g., "EURUSD_otc")
    payout: float               # Payout percentage (e.g., 82.0 means 82% profit)
    is_open: bool               # Whether trading is currently allowed
    category: str = "binary"    # Asset category (binary, digital, etc.)
    display_name: str = ""      # User-friendly name for UI
    last_price: float = 0.0     # Most recent price
    sentiment: float | None = None  # Market sentiment (% bullish)
    feed_status: str = "warming"    # "warming", "active", "error"
    countdown_seconds: int | None = None  # Time until next candle close
    countdown_updated_at: float = 0.0   # Timestamp of last countdown update
```

**Usage:** Represents a tradable asset pair. Populated by:
- Backend `fetch_assets()` method
- Updated periodically with price/payout changes
- Displayed in UI asset list

**Feed Status Values:**
- `"warming"`: Receiving data but not yet stable
- `"active"`: Fully operational with live data
- `"error"`: Data feed has errors or disconnected

#### TradeTicket
```python
@dataclass(slots=True)
class TradeTicket:
    id: str                     # Unique trade identifier from broker
    asset: str                  # Symbol being traded
    action: str                 # "CALL" (buy/up) or "PUT" (sell/down)
    amount: float               # Amount invested
    duration: int               # Trade duration in seconds
    opened_at: float            # Unix timestamp when trade opened
    estimated_payout: float = 80.0  # Expected payout percentage
    is_demo: bool = True        # True for practice, False for live
    accepted: bool = False      # Whether broker accepted the trade
    result: bool | None = None  # True=win, False=loss, None=pending
    profit: float | None = None # Actual profit/loss amount
    raw: dict[str, Any] = field(default_factory=dict)  # Raw broker response
```

**Usage:** Represents a single trade. Lifecycle:
1. Created by `backend.place_trade()`
2. Passed to `automation.register_open()`
3. Monitored until duration expires
4. Updated with result by `backend.check_trade_result()`
5. Passed to `automation.register_result()` and `learner.record_trade_outcome()`

#### StrategyDecision
```python
@dataclass(slots=True)
class StrategyDecision:
    action: str = "HOLD"                # "CALL", "PUT", or "HOLD"
    confidence: float = 0.0             # 0.0 to 1.0 signal strength
    summary: str = "Waiting for candles"  # Human-readable description
    reason: str = ""                    # Detailed reason for the decision
    rsi: float | None = None            # Current RSI value
    trend_strength: float = 0.0         # ADX or similar trend strength
    recommended_duration: int = 120     # Suggested trade duration (seconds)
    signal_timestamp: int = 0           # When signal was generated
    reference_price: float = 0.0        # Entry price for outcome comparison
    ema_fast: list[float] = field(default_factory=list)  # Fast EMA values
    ema_slow: list[float] = field(default_factory=list)  # Slow EMA values
```

**Usage:** Output of all signal engines. Used by:
- UI to display current signal
- Automation to decide whether to trade
- Learning system to record outcomes
- Telegram bot to broadcast signals

**Action Values:**
- `"CALL"`: Buy/up prediction (price will rise)
- `"PUT"`: Sell/down prediction (price will fall)
- `"HOLD"`: No trade recommended (insufficient data or mixed signals)

#### SessionStats
```python
@dataclass(slots=True)
class SessionStats:
    wins: int = 0                   # Total winning trades this session
    losses: int = 0                 # Total losing trades this session
    trades_taken: int = 0           # Total trades executed
    consecutive_losses: int = 0     # Current loss streak
    net_pnl: float = 0.0            # Net profit/loss for session
    active_trade_id: str | None = None  # ID of currently open trade
    automation_enabled: bool = False    # Whether auto-trading is on
    last_trade_at: float = 0.0      # Timestamp of last trade
```

**Usage:** Tracks trading session performance. Updated by:
- `automation.register_open()` - increments trades_taken
- `automation.register_result()` - updates wins/losses/net_pnl
- UI displays these stats in Auto Trading tab

#### WorkerAccount
```python
@dataclass(slots=True)
class WorkerAccount:
    email: str = ""
    password: str = ""
    enabled: bool = False
    session_cached: bool = False
```

**Usage:** Represents a single account in the matrix multi-account system.

#### MatrixSettings
```python
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
```

**Purpose:** Pre-configured worker accounts for parallel trading. Note: passwords are hardcoded as defaults but encrypted when saved to settings.json.

#### ConnectionProfile
```python
@dataclass(slots=True)
class ConnectionProfile:
    provider: str = "mock"              # quotex/iq_option/exness/multi/mock
    email: str = ""
    password: str = ""
    email_pin: str = ""                 # 2FA PIN if required
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
    headless: bool = False              # Run browser without UI
    browser_engine: str = "selenium"    # selenium or playwright
    data_source: str = "browser"        # browser or websocket
    account_mode: str = "PRACTICE"      # PRACTICE or LIVE
    selected_asset: str = ""
    candle_period: int = 60             # Seconds (60=1min, 300=5min)
    trade_duration: int = 120           # Default trade length
    trade_amount: float = 5.0           # Default trade amount
```

**Provider Values:**
- `"mock"`: Sandbox mode, no real connection
- `"quotex"`: Live Quotex browser automation
- `"iq_option"`: IQ Option via Playwright
- `"exness"`: Exness via Twelve Data API
- `"multi"`: Multiple brokers simultaneously

#### StrategySettings
```python
@dataclass(slots=True)
class StrategySettings:
    fast_ema: int = 9                   # Fast EMA period
    slow_ema: int = 21                  # Slow EMA period
    rsi_period: int = 14                # RSI calculation period
    min_confidence: float = 0.56        # Minimum for auto-trade (56%)
    auto_trade_enabled: bool = False    # Enable automatic trading
    deep_scan_min_confidence: float = 0.50  # Min for deep scan signals
    preferred_expiry_seconds: int = 120     # Default trade duration
    sticky_signal_seconds: int = 75     # How long to keep signal valid
    learning_enabled: bool = False      # Enable adaptive learning
    learning_interval_seconds: int = 45     # Learning check frequency
    learning_verify_seconds: int = 120      # Time to verify signal outcome
```

#### RiskSettings
```python
@dataclass(slots=True)
class RiskSettings:
    stop_profit: float = 30.0               # Halt at this profit ($)
    stop_loss: float = 20.0                 # Halt at this loss ($)
    max_consecutive_losses: int = 3         # Halt after N losses in a row
    cooldown_seconds: int = 90              # Wait between trades
    max_open_trades: int = 1                # Max simultaneous trades
```

#### TelegramSettings
Contains 30+ fields for Telegram bot configuration including bot token, button labels, broker credentials, admin settings, etc. See `models.py` lines 164-196 for complete definition.

#### LicenseSettings
```python
@dataclass(slots=True)
class LicenseSettings:
    enabled: bool = False
    api_url: str = ""
    api_token: str = ""
    license_key: str = ""
    remember_license_key: bool = False
    poll_seconds: int = 30              # Revalidation interval
    machine_lock_enabled: bool = True
    provider_name: str = "custom"
    status_text: str = "License disabled"
    last_checked_at: float = 0.0
    cache_valid_until: float = 0.0      # Cached validation expiry
    cached_validation_status: str = ""  # Last validation result
```

#### AppSettings (Root Container)
```python
@dataclass(slots=True)
class AppSettings:
    connection: ConnectionProfile = field(default_factory=ConnectionProfile)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    matrix: MatrixSettings = field(default_factory=MatrixSettings)
    license: LicenseSettings = field(default_factory=LicenseSettings)
```

---

## 3. MAIN CONTROLLER (BOTCONTROLLER)

### 3.1 Overview: `controller.py`

**Location:** `eternal_quotex_bot/controller.py` (108.5 KB)

**Class:** `BotController(QObject)`

**Size:** Largest logic file in the project (~3000+ lines)

**Role:** Central orchestrator that coordinates all application components. Acts as the glue between UI, backend, signal engines, automation, learning, and Telegram.

### 3.2 Initialization

```python
class BotController(QObject):
    # Qt Signals
    connection_changed = Signal(bool)
    signal_changed = Signal(StrategyDecision)
    candles_changed = Signal(list)
    trade_completed = Signal(TradeTicket)
    trade_failed = Signal(str)
    status_message = Signal(str)
    
    def __init__(self):
        super().__init__()
        # Initialize state
        self.settings = SettingsStore()
        self.backend = None
        self.connected = False
        self.connecting = False
        self.scan_in_progress = False
        self.learning_busy = False
        self.pin_flow_active = False
        
        # Subsystems
        self.tick_buffer = TickBuffer()
        self.learner = SignalLearner()
        self.automation = AutomationEngine()
        
        # Threading
        self.async_runner = AsyncRunner()
        
        # State
        self.current_asset = None
        self.current_signal = None
        self.session_stats = SessionStats()
```

### 3.3 Connection Management

#### `async connect()` [Lines ~443-550]

**Complete Flow:**
```python
async def connect(self):
    # 1. Guard against concurrent connections
    if self.connecting:
        return
    self.connecting = True
    self.status_message.emit("Connecting...")
    
    # 2. Load settings
    profile = self.settings.settings.connection
    
    # 3. Select backend based on provider
    if profile.provider == "quotex":
        from .backend.live import LiveQuotexBackend
        self.backend = LiveQuotexBackend()
    elif profile.provider == "mock":
        from .backend.mock import MockBackend
        self.backend = MockBackend()
    elif profile.provider == "iq_option":
        from .backend.external import IQOptionAdapter
        self.backend = IQOptionAdapter()
    # ... other providers
    
    # 4. Connect to backend
    try:
        success = await self.backend.connect(
            email=profile.email,
            password=profile.password,
            mode=profile.account_mode,
            headless=profile.headless
        )
        
        if not success:
            self.status_message.emit("Connection failed")
            self.connecting = False
            return
        
        # 5. Post-connection setup
        self.connected = True
        self.connecting = False
        
        # 6. Fetch assets
        await self.fetch_assets()
        
        # 7. Start price update loop
        self._start_price_updates()
        
        # 8. Emit connected
        self.connection_changed.emit(True)
        self.status_message.emit("Connected")
        
    except Exception as e:
        self._handle_async_error(e)
```

**Key Points:**
- Uses `connecting` flag to prevent concurrent connection attempts
- Backend selection is dynamic based on `provider` setting
- Connection is async to prevent UI blocking
- All exceptions routed to `_handle_async_error()`

#### `disconnect_backend()` [Lines ~552-575]

```python
def disconnect_backend(self):
    if self.backend:
        try:
            self.backend.disconnect()
        except Exception:
            pass
        self.backend = None
    
    self.connected = False
    self.connecting = False
    self.connection_changed.emit(False)
    self._stop_timers()
```

### 3.4 Asset Management

#### `async fetch_assets()` [Lines ~652-700]

```python
async def fetch_assets(self):
    assets = await self.backend.fetch_assets()
    
    # Update UI asset list
    # Filter by category (OTC vs Real)
    # Sort by payout percentage
    # Select first available asset
    
    # If auto-select is enabled:
    if not self.current_asset and assets:
        self.current_asset = assets[0]
        self.backend.set_selected_asset(self.current_asset.symbol)
    
    self.assets_loaded.emit(assets)
```

#### `async refresh_market()` [Lines ~702-730]

```python
async def refresh_market(self):
    # Refresh payouts and prices for all assets
    # Update countdown timers
    # Check for market open/close changes
    # Emit updated asset list
```

### 3.5 Trade Execution

#### `place_trade(action, source, duration)` [Lines ~576-596]

```python
def place_trade(self, action: str, source: str, duration: int):
    if not self.connected:
        self.status_message.emit("Not connected")
        return
    
    if not self.current_asset:
        self.status_message.emit("No asset selected")
        return
    
    profile = self.settings.settings.connection
    amount = profile.trade_amount
    
    # Execute trade via backend
    self.async_runner.run(
        self._place_trade_async(action, duration, amount)
    )
```

#### `async _place_trade_async(action, duration, amount)` [Internal]

```python
async def _place_trade_async(self, action, duration, amount):
    try:
        ticket = await self.backend.place_trade(
            symbol=self.current_asset.symbol,
            action=action,
            amount=amount,
            duration=duration
        )
        
        if ticket.accepted:
            self._on_trade_opened(ticket)
        else:
            self.trade_failed.emit("Trade rejected by broker")
            
    except Exception as e:
        self._handle_async_error(e)
```

#### `_on_trade_opened(ticket)` [Lines ~598-620]

```python
def _on_trade_opened(self, ticket: TradeTicket):
    # Register with automation
    self.automation.register_open(ticket)
    
    # Create learning probe
    if self.settings.settings.strategy.learning_enabled:
        probe = self.learner.create_probe(
            signal=self.current_signal,
            ticket=ticket
        )
    
    # Start monitoring for result
    self.async_runner.run(
        self._monitor_trade_result(ticket)
    )
    
    self.status_message.emit(f"Trade opened: {ticket.action} {ticket.asset}")
```

#### `_on_trade_resolved(ticket)` [Lines ~622-650]

```python
def _on_trade_resolved(self, ticket: TradeTicket):
    # Register result with automation
    self.automation.register_result(ticket)
    
    # Record learning outcome
    if ticket.result is not None:
        self.learner.record_trade_outcome(ticket)
    
    # Update session stats
    if ticket.result:
        self.session_stats.wins += 1
        self.session_stats.consecutive_losses = 0
    else:
        self.session_stats.losses += 1
        self.session_stats.consecutive_losses += 1
    
    self.session_stats.trades_taken += 1
    self.session_stats.net_pnl += ticket.profit or 0
    self.session_stats.active_trade_id = None
    
    # Emit completion
    self.trade_completed.emit(ticket)
```

### 3.6 Signal Generation

#### `_run_deep_scan()` [Controller Deep Scan, ~1450-1700 lines]

See `controller_deep_scan_new.py` for optimized version.

**Complete Flow:**
```python
async def _run_deep_scan(self):
    self.scan_in_progress = True
    self.status_message.emit("Deep scanning...")
    
    try:
        # 1. Wait for price refresh (up to 10s)
        await self._wait_for_price_refresh(timeout=10)
        
        # 2. Get all OTC pairs
        otc_pairs = self._get_otc_pairs()
        
        # 3. Fetch candles in PARALLEL (8s timeout per pair)
        tasks = []
        for pair in otc_pairs:
            task = asyncio.create_task(
                self._fetch_candles_with_timeout(pair, timeout=8)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 4. Build candle map
        candle_map = {}
        for pair, candles in zip(otc_pairs, results):
            if isinstance(candles, list) and len(candles) > 0:
                candle_map[pair] = candles
        
        # 5. Analyze pairs with candles
        signals = []
        for pair, candles in candle_map.items():
            try:
                # Run advanced engine
                from .advanced_signal_engine import AdvancedSignalEngine
                engine = AdvancedSignalEngine()
                result = engine.analyze(candles)
                
                signals.append({
                    "pair": pair,
                    "action": result.action,
                    "confidence": result.confidence,
                    "candles_available": True
                })
            except Exception:
                # Generate price-based signal if no candles
                signals.append(self._generate_price_signal(pair))
        
        # 6. Filter by confidence threshold
        min_conf = self.settings.settings.strategy.deep_scan_min_confidence
        confirmed = [s for s in signals if s["confidence"] >= min_conf]
        developing = [s for s in signals if s["confidence"] >= 0.40]
        
        # 7. Select best signal
        if confirmed:
            best = max(confirmed, key=lambda s: s["confidence"])
        elif developing:
            best = max(developing, key=lambda s: s["confidence"])
        else:
            best = {"action": "HOLD", "confidence": 0.0, "summary": "No data"}
        
        # 8. Avoid repeating last scanned asset
        if best["pair"] == self.last_scanned_asset:
            # Pick second best instead
            ...
        
        # 9. Emit result
        self.deep_scan_result.emit(best)
        
    except Exception as e:
        self._on_deep_scan_error(e)
    finally:
        self.scan_in_progress = False
```

### 3.7 Error Handling

#### `_handle_async_error(error)` [Lines 1192-1214]

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
        if not self.pin_flow_active and self.backend:
            try:
                self.backend.disconnect()
            except Exception:
                pass
    
    # Emit signals
    self.connection_changed.emit(False)
    self.log_error(f"Error: {error_msg}")
    self.status_message.emit(f"Error: {error_msg}")
```

**Critical Note:** This catches `BaseException` (line ~936 in some places), which includes `KeyboardInterrupt` and `SystemExit`. This can prevent normal application shutdown and is a known issue.

#### `_on_deep_scan_error(error)` [Lines 2183-2205]

```python
def _on_deep_scan_error(self, error: BaseException):
    import traceback
    tb = traceback.format_exc()
    
    self.log_error(f"Deep scan error:\n{tb}")
    self.scan_in_progress = False
    
    # Emit error result
    self.deep_scan_result.emit({
        "scanned": 0,
        "rows": [],
        "error": str(error)
    })
    
    self.status_message.emit("Deep scan failed")
```

---

## 4. BACKEND INTEGRATION LAYER

### 4.1 Abstract Interface: `backend/base.py`

**Location:** `eternal_quotex_bot/backend/base.py` (1.1 KB)

```python
from abc import ABC, abstractmethod

class TradingBackend(ABC):
    """Abstract interface for all broker backends"""
    
    @abstractmethod
    async def connect(self, **kwargs) -> bool:
        """Connect to broker. Returns True on success."""
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker."""
    
    @abstractmethod
    async def fetch_assets(self) -> list[AssetInfo]:
        """Get list of available trading assets."""
    
    @abstractmethod
    async def fetch_candles(self, symbol: str, period: int, count: int) -> list[Candle]:
        """Fetch historical candles for a symbol."""
    
    @abstractmethod
    async def place_trade(self, symbol: str, action: str, amount: float, duration: int) -> TradeTicket:
        """Execute a trade. Returns TradeTicket."""
    
    @abstractmethod
    async def get_account(self) -> AccountSnapshot:
        """Get account balance and mode."""
    
    @abstractmethod
    def set_selected_asset(self, symbol: str) -> None:
        """Set the currently selected asset for trading."""
```

**Design Pattern:** Strategy pattern - all broker implementations conform to this interface, allowing the controller to switch brokers without code changes.

### 4.2 Live Quotex Backend: `backend/live.py`

**Location:** `eternal_quotex_bot/backend/live.py` (341.5 KB - LARGEST FILE)

**Class:** `LiveQuotexBackend(TradingBackend)`

**Architecture:**
This is the most complex component. It uses browser automation (Selenium/Playwright) to interact with Quotex's web interface, extracts session tokens, and communicates via WebSocket for real-time data.

#### Connection Flow [Lines ~200-400]

```python
async def connect(self, email, password, mode="PRACTICE", headless=False):
    # Step 1: Initialize browser
    self._init_browser(headless=headless)
    
    # Step 2: Try cached session first
    session = self._load_session_cache()
    if session:
        try:
            self._restore_session(session)
            if self._is_session_valid():
                return True
        except Exception:
            self._clear_session_cache()
    
    # Step 3: Fresh login
    self.browser.get("https://qxbroker.com/en/sign-in")
    
    # Wait for page load
    WebDriverWait(self.browser, 30).until(
        EC.presence_of_element_located((By.ID, "email"))
    )
    
    # Fill credentials
    self.browser.find_element(By.ID, "email").send_keys(email)
    self.browser.find_element(By.ID, "password").send_keys(password)
    self.browser.find_element(By.CLASS_NAME, "btn-login").click()
    
    # Step 4: Handle email PIN if required
    if self._detect_pin_required():
        self.controller.pin_flow_active = True
        # Pause and wait for user to enter PIN
        pin = await self._wait_for_pin_input()
        self._enter_pin(pin)
        self.controller.pin_flow_active = False
    
    # Step 5: Extract session token
    self._extract_session_token()
    
    # Step 6: Cache session
    self._save_session_cache(self.session_data)
    
    # Step 7: Navigate to trade page
    trade_url = f"https://market-qx.trade/en/{mode.lower()}-trade"
    self.browser.get(trade_url)
    
    # Step 8: Start browser bridge (WebSocket)
    self._start_browser_bridge()
    
    # Step 9: Set account mode
    self._set_account_mode(mode)
    
    return True
```

**Auth Debug Logging (Recently Added):**
Eight `[Auth Debug]` print statements were added at lines ~2896-2934 and ~3103-3140 to diagnose token extraction issues. These print:
- Current URL
- Page title
- Session data keys
- Alternative token field values

This indicates the broker changed their session data structure, requiring fallback token field names: `"ssid"`, `"session_id"`, `"auth_token"`, `"accessToken"`, `"access_token"`.

#### Browser Bridge Client [Internal Class]

```python
class _BrowserBridgeClient:
    """Direct WebSocket link to Quotex market data"""
    
    def __init__(self, browser):
        self.browser = browser
        self.socket_url = None
        self.authorized = False
        self.account_balance = None
        self.instruments = []
        self.history_by_asset = {}
        self.last_error = None
    
    def start(self):
        # Inject JavaScript into browser page to intercept WebSocket
        script = """
        // Capture WebSocket connections
        const originalWebSocket = window.WebSocket;
        window.WebSocket = function(url) {
            // Notify Python about WebSocket URL
            window.postMessage({type: 'websocket_url', url: url}, '*');
            return new originalWebSocket(url);
        };
        """
        self.browser.execute_script(script)
        
        # Connect to captured WebSocket
        self._connect_to_socket()
    
    def request_candles(self, symbol, period, count):
        # Send candle request via WebSocket
        # Wait for response with timeout
        # Return parsed candles
```

**Key Features:**
- Intercepts browser WebSocket connections
- Sends candle history requests through the browser's authenticated session
- Receives and parses real-time price updates
- Maintains instrument list with payouts
- Tracks account balance

#### Candle Fetching with Fallbacks [Lines ~502-600]

```python
async def fetch_candles(self, symbol, period, count):
    # Attempt 1: Browser bridge WebSocket
    try:
        candles = await self.bridge.request_candles(symbol, period, count, timeout=10)
        if candles:
            return candles
    except TimeoutError:
        pass
    
    # Attempt 2: Market page data extraction
    try:
        candles = await self._get_candles_with_market_fallback(symbol, period, count)
        if candles:
            return candles
    except Exception:
        pass
    
    # Attempt 3: DOM price extraction
    try:
        price = self._fallback_market_snapshot(symbol)
        # Build minimal candles from current price
        return self._build_synthetic_candles(price, period, count)
    except Exception:
        pass
    
    # All attempts failed
    raise TimeoutError(f"Candle fetch for {symbol} timed out after all fallbacks")
```

**Known Issue:** The diagnostic files show that fallback chain is failing for certain OTC pairs (USDBDT_otc, USDEGP_otc) with `TimeoutError`. The bridge receives data (`incomingCount: 1449`) but fails to send proper history requests (`outgoingCount: 26`).

#### Session Caching [Lines ~375-443]

```python
def _session_cache_file(self):
    return runtime_dir() / "quotex_session.pkl"

def _load_session_cache(self):
    cache_file = self._session_cache_file()
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None

def _save_session_cache(self, payload):
    cache_file = self._session_cache_file()
    if not payload:
        # Delete cache if payload is empty
        if cache_file.exists():
            cache_file.unlink()
        return
    
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(payload, f)
    except Exception as e:
        self.log_error(f"Failed to save session cache: {e}")
```

**Cached Data Structure:**
```python
{
    email: [
        cookies,          # Cookie string
        ssid,             # Session ID
        user_agent,       # Browser UA
        wss_url,          # WebSocket URL
        wss_candidates,   # Multiple WS URL candidates
        ws_origin,        # Origin header
        ws_host,          # WS host
        ws_headers        # Additional headers
    ]
}
```

#### Symbol Normalization

```python
_broker_symbol_aliases = {
    "EUR/USD": "EURUSD_otc",
    "USD/JPY": "USDJPY_otc",
    "eur_usd": "EURUSD_otc",
    # ... many more aliases
}

def _normalize_symbol(self, symbol):
    # Handle broker display variations
    return self._broker_symbol_aliases.get(symbol, symbol)
```

#### Browser Version Retry [Lines ~2778-2789]

```python
# Detect Chrome version mismatch from undetected_chromedriver
retry_major = _parse_browser_major_from_driver_error(message)
if retry_major and retry_major != launch_kwargs.get("version_main"):
    # Retry with corrected version
    retry_kwargs = dict(launch_kwargs)
    retry_kwargs["version_main"] = retry_major
    return self._launch_browser(**retry_kwargs)
```

**Purpose:** Chrome auto-update can break the bot. This workaround detects version mismatch errors and retries with the correct version number.

### 4.3 Mock Backend: `backend/mock.py`

**Location:** `eternal_quotex_bot/backend/mock.py` (6.8 KB)

**Class:** `MockBackend(TradingBackend)`

**Purpose:** Offline testing without real money or network connection.

```python
class MockBackend(TradingBackend):
    def __init__(self):
        self.connected = False
        self.balance = 10000.0
        self.assets = [
            AssetInfo("EURUSD", 82.0, True, last_price=1.0850),
            AssetInfo("GBPUSD", 80.0, True, last_price=1.2650),
            AssetInfo("USDJPY", 81.0, True, last_price=149.50),
            AssetInfo("XAUUSD", 85.0, True, last_price=2350.0),
            AssetInfo("EURUSD_otc", 87.0, True, last_price=1.0850),
        ]
    
    async def connect(self, **kwargs):
        self.connected = True
        return True
    
    async def disconnect(self):
        self.connected = False
    
    async def fetch_assets(self):
        return self.assets
    
    async def fetch_candles(self, symbol, period, count):
        # Generate synthetic candles with realistic price movement
        return self._generate_candles(symbol, count)
    
    async def place_trade(self, symbol, action, amount, duration):
        # Simulate trade with 50/50 win rate
        import random
        win = random.random() > 0.5
        profit = amount * 0.82 if win else -amount
        
        return TradeTicket(
            id=f"mock-{uuid4()}",
            asset=symbol,
            action=action,
            amount=amount,
            duration=duration,
            accepted=True,
            result=win,
            profit=profit
        )
```

### 4.4 External Backends: `backend/external.py`

**Location:** `eternal_quotex_bot/backend/external.py` (69.0 KB)

**Classes:**
- `IQOptionPlaywrightAdapter` - IQ Option via Playwright
- `TwelveDataForexAdapter` - Exness via Twelve Data API
- `MultiBrokerBackend` - Orchestrates multiple brokers

**IQ Option Adapter:**
- Uses Playwright for browser automation
- Similar login flow to Quotex
- Different asset symbols and trade execution API

**Twelve Data Adapter:**
- REST API client (no browser)
- 65+ forex pairs
- Real-time price streaming via WebSocket
- Used for Exness integration

**Multi-Broker Backend:**
- Maintains connections to multiple brokers simultaneously
- Routes trades to best available broker
- Aggregates assets from all brokers

---

*Documentation continues in Part 2 (Signal Engines, Automation, Learning, Telegram, UI, Licensing, Utilities, Build System, Testing, Bug History, and Current Status)*
