# Eternal Quotex Bot - Feature-to-Logic Mapping

## 1. MANDATORY SECURITY PROTOCOL (v14.4.10)
**File:** `eternal_quotex_bot/app.py`

**Purpose:** Enforce a "Gate-First" startup that blocks UI initialization until a valid license is confirmed.

**Logic Flow:**
1.  **Bootstrap**: Initialize Qt Application, themes, and directories.
2.  **Controller Init**: Instantiate `BotController` to prepare the backend diagnostic state.
3.  **Mandatory Gate**: Call `run_license_gate(controller)`.
    -   If False (User exits/Invalid): Immediate process termination (exit code 0).
    -   If True: Proceed to UI initialization.
4.  **UI Ignition**: Load `MainWindow` only after license verification.

---

## 2. SENTINEL CONNECTION BRIDGE (v4.20)
**File:** `eternal_quotex_bot/backend/live.py`

**Purpose:** High-stability browser ignition using a 3-stage serial handshake.

**Logic Flow:**
1.  **Stage 1 (Ignition)**: Initialize `undetected-chromedriver` with forensic stealth flags (1920x1080 resolution, headless-detect bypass).
2.  **Stage 2 (DOM Watchman)**: Execute a 180s progressive polling loop. Wait for Quotex security scripts to render the login fields.
3.  **Stage 3 (Selector Proxy)**: If standard selectors fail, inject a JavaScript proxy to map dynamic attributes to static library IDs.
4.  **Stage 4 (Session Settle)**: 3-second mandatory "Settle Pass" to guarantee DOM stability before credential injection.

### 1.1 Standard Strategy Engine
**File:** `eternal_quotex_bot/strategy.py`

**Purpose:** Baseline signal evaluation using EMA crossover and RSI

**Logic Flow:**
```
Input: candles (list of Candle), strategy_settings (StrategySettings)
  |
  +-> Check minimum candle count (>= slow_ema + 5)
  |     -> If insufficient: return HOLD with low confidence
  |
  +-> Calculate indicators:
  |     - EMA fast (default 9 periods)
  |     - EMA slow (default 21 periods)
  |     - RSI (default 14 periods)
  |     - Support/Resistance levels
  |     - Bollinger Bands (20 period)
  |     - MACD (12/26/9)
  |     - Stochastic (14/3)
  |     - Williams %R (14)
  |     - CCI (20)
  |     - ATR (14)
  |     - VWAP
  |     - Momentum (5 candle lookback)
  |
  +-> Score CALL and PUT independently:
  |     - EMA crossover: fast > slow -> CALL+, fast < slow -> PUT+
  |     - RSI zones: < 30 -> CALL+, > 70 -> PUT+
  |     - S/R bounces: near support -> CALL+, near resistance -> PUT+
  |     - BB position: near lower band -> CALL+, near upper -> PUT+
  |
  +-> Calculate confidence:
  |     - base = 0.48 + (dominance * 0.32)
  |     - dominance = |call_score - put_score| / (call_score + put_score)
  |
  +-> Return StrategyDecision:
        - action: "CALL" or "PUT" (never HOLD unless insufficient data)
        - confidence: 0.0 to 1.0
        - recommended_duration: 120s default
        - rsi, trend_strength, ema_fast[], ema_slow[]
```

**Key Functions:**
- `evaluate_signal(candles, settings)` - Main entry point [line 229-518]
- `_ema(values, period)` - Exponential moving average [line 40-50]
- `_rsi(closes, period)` - Relative Strength Index [line 53-73]
- `_macd(closes)` - Moving Average Convergence Divergence [line 76-101]
- `_bollinger_bands(closes)` - Volatility bands [line 104-120]
- `_stochastic(candles)` - Momentum oscillator [line 123-140]

---

### 1.2 Advanced Signal Engine
**File:** `eternal_quotex_bot/advanced_signal_engine.py`

**Purpose:** 15-indicator comprehensive voting system with pattern detection

**Logic Flow:**
```
Input: candles (list of Candle)
  |
  +-> Calculate all 15 indicators
  |
  +-> Score each indicator for CALL or PUT:
  |     1. EMA Fast/Slow (9/21) - Weight 4.0
  |        - Crossover direction determines vote
  |     2. EMA 50 (medium-term trend) - Weight 3.0
  |        - Price vs EMA 50 position
  |     3. RSI (14) - Weight 3.0
  |        - Overbought/Oversold zones
  |     4. MACD (12/26/9) - Weight 3.5
  |        - Line crossover + histogram momentum
  |     5. Bollinger Bands (20) - Weight 2.5
  |        - Position within bands
  |     6. Stochastic (14/3) - Weight 2.5
  |        - K/D crossover + zones
  |     7. Williams %R (14) - Weight 2.0
  |        - Overbought/Oversold
  |     8. CCI (20) - Weight 2.0
  |        - Commodity Channel Index
  |     9. MFI (14) - Weight 1.5
  |        - Money Flow Index (volume-weighted)
  |    10. VWAP - Weight 2.5
  |        - Price vs volume-weighted average
  |    11. Momentum (5) - Weight 2.0
  |        - Recent price direction
  |    12. Candle Structure - Weight 2.5
  |        - Body size and close position
  |    13. Parabolic SAR - Weight 2.0
  |        - SAR position relative to price
  |    14. Engulfing Pattern - Weight 2.5
  |        - Bullish/Bearish engulfing detection
  |    15. Pin Bar - Weight 2.0
  |        - Reversal candle pattern
  |
  +-> Apply ADX trend multiplier:
  |     - ADX > 30: 1.25x (strong trend)
  |     - ADX > 20: 1.1x (moderate trend)
  |     - ADX < 15: 0.9x (weak trend)
  |
  +-> Calculate final confidence:
  |     - call_score = sum of CALL votes * weights
  |     - put_score = sum of PUT votes * weights
  |     - dominance = |call - put| / (call + put)
  |     - confidence = 0.48 + (dominance * 0.32)
  |
  +-> Return SignalResult:
        - action: "CALL" or "PUT"
        - confidence: 0.0 to 1.0
        - indicator_count: number of indicators used
        - trend_strength: ADX value
        - pattern_detected: detected candle patterns
        - rsi, macd values for reference
```

**Pattern Detection:**
- `_detect_engulfing(candles)` - Bullish: current body engulfs previous, close > open
- `_detect_pin_bar(candles)` - Long wick, small body, reversal direction
- `_detect_doji(candles)` - Very small body, indecision signal

---

### 1.3 Apex Analysis Engine
**File:** `eternal_quotex_bot/apex_analysis.py`

**Purpose:** Alternative weighted voting system with different weightings

**Logic Flow:**
```
Similar to Advanced Engine but with:
- Different weight distribution
- Adaptive confidence calculation
- Returns ApexVoteResult with detailed vote breakdown
```

---

### 1.4 Sniper Scanner (Deep Scan v1)
**File:** `eternal_quotex_bot/sniper_scan.py`

**Purpose:** High-confidence single signal with OTC-specific analysis

**Logic Flow:**
```
Input: symbol (optional, scans all if not provided)
  |
  +-> Get candles from tick_buffer
  |     -> If insufficient: fall back to tick analysis
  |
  +-> If has candles:
  |     +-> Run 15-indicator scoring (_score_indicators)
  |     +-> Multi-timeframe analysis:
  |           - 1min EMA alignment
  |           - 2min EMA alignment
  |           - 5min EMA alignment
  |           - All aligned -> +confidence bonus
  |     +-> OTC-specific fusion:
  |           - Tick momentum analysis (last 20 ticks)
  |           - Repeating pattern detection (3-8 tick sequences)
  |           - Support/Resistance bounce check
  |           - Apply bonuses: momentum +0.05, pattern +0.08, SR +0.07
  |
  +-> If no candles (tick fallback):
  |     +-> Tick momentum analysis only
  |     +-> Weighted linear regression on last N ticks
  |     +-> Return directional signal with 0.50-0.65 confidence
  |
  +-> Calculate confidence:
  |     - Base: 0.48 + (dominance * 0.32)
  |     - Caps: ADX < 18 -> max 0.68, body_ratio < 0.25 -> max 0.69
  |     - OTC bonuses added
  |     - Multi-timeframe bonus: up to +0.06
  |
  +-> Return SniperSignal:
        - symbol, action, confidence, expiry_seconds
        - entry_price, rsi, trend_strength
        - indicators_used[], pattern_detected
        - multi_timeframe_aligned (bool)
```

**Key Functions:**
- `scan(symbol)` - Single pair deep scan [line 579-614]
- `_scan_with_candles(target, candles, price)` - Full analysis [line 616-754]
- `_scan_with_ticks(target, price)` - Tick fallback [line 756-885]
- `scan_all()` - Scan all configured pairs [line 891-896]
- `best_signal()` - Return highest confidence signal [line 902-916]
- `to_strategy_decision(signal)` - Convert to API-compatible format [line 974-999]

**OTC Pattern Detection:**
- `_detect_repeating_patterns(prices)` - Searches for repeating price-change sequences
  - Tests pattern lengths 3-8
  - Tolerance: 5% price variation allowed
  - Returns: pattern string, direction, confidence

**Tick Momentum Analysis:**
- `_tick_momentum_analysis(prices, lookback)` - Weighted linear regression
  - Exponential weighting (recent ticks more important)
  - Returns momentum score [-1.0, 1.0]
  - Positive = upward momentum, Negative = downward

**Support/Resistance Analysis:**
- `_sr_bounce_analysis(candles, support, resistance)` - Check bounce
  - Support = 5th percentile of recent prices
  - Resistance = 95th percentile of recent prices
  - Returns: near_support (bool), near_resistance (bool), description

---

### 1.5 Broadcast Scanner (Deep Scan v2)
**File:** `eternal_quotex_bot/broadcast_scan.py`

**Purpose:** Multi-pair parallel scanning for Telegram distribution

**Logic Flow:**
```
Input: None (scans all OTC pairs)
  |
  +-> For each OTC pair (37 pairs by default):
  |     +-> Get candles from tick_buffer
  |     +-> Run 12-indicator analysis (evaluate_signal)
  |     +-> Filter by confidence threshold (default 0.65)
  |
  +-> Compile results:
  |     - signals: list of BroadcastSignal above threshold
  |     - scanned_pairs: total count
  |     - pairs_with_data: count with valid candles
  |     - scan_timestamp, scan_duration_ms
  |
  +-> Return BroadcastResult:
        - format_telegram_message(engine_name) - Formatted output
```

**Key Functions:**
- `scan_all()` - Parallel multi-pair scan [line 182-223]
- `scan_single(pair)` - Analyze single pair [line 225-240]
- `_analyze_pair(pair)` - 12-indicator evaluation [line 242-263]
- `BroadcastResult.format_telegram_message(engine_name)` - Telegram formatting [line 105-152]

**Default OTC Pairs (37):**
EURUSD_otc, GBPUSD_otc, USDJPY_otc, AUDUSD_otc, USDCAD_otc, NZDUSD_otc, USDCHF_otc, EURGBP_otc, EURJPY_otc, GBPJPY_otc, AUDCAD_otc, AUDJPY_otc, CADJPY_otc, CHFJPY_otc, EURCAD_otc, EURAUD_otc, EURNZD_otc, GBPAUD_otc, GBPCAD_otc, GBPNZD_otc, NZDCAD_otc, NZDJPY_otc, AUDNZD_otc, CADCHF_otc, EURCHF_otc, USDINR_otc, USDIDR_otc, USDMXN_otc, USDPHP_otc, USDTHB_otc, USDSGD_otc, USDCOP_otc, USDARS_otc, etc.

---

## 2. TRADING LOGIC

### 2.1 Trade Execution Flow
**File:** `eternal_quotex_bot/controller.py`

```
User triggers trade (manual or auto):
  |
  +-> controller.place_trade(action, source, duration)
  |     |
  |     +-> Validate: connected, asset selected, amount > 0
  |     +-> Call: backend.place_trade(symbol, action, amount, duration)
  |     |     |
  |     |     +-> Live backend: browser automation API call
  |     |     +-> Mock backend: simulated result
  |     |     +-> External backend: broker-specific API
  |     |     |
  |     |     +-> Returns: TradeTicket (id, accepted, estimated_payout)
  |     |
  |     +-> If accepted:
  |           -> _on_trade_opened(ticket)
  |                -> automation.register_open(ticket)
  |                -> learner.create_outcome_context(ticket, signal)
  |                -> Start result checking loop
  |                     -> backend.check_trade_result(ticket)
  |                          -> Poll until duration expires
  |                          -> Returns updated ticket with result
  |                     -> _on_trade_resolved(ticket)
  |                          -> automation.register_result(ticket)
  |                          -> learner.record_trade_outcome(ticket)
  |                          -> Update session stats
  |                          -> Emit trade_completed signal
```

**Key Methods:**
- `place_trade(action, source, duration)` - Execute trade [line 576-596]
- `_on_trade_opened(ticket)` - Post-trade setup [line 598-620]
- `_on_trade_resolved(ticket)` - Result processing [line 622-650]

---

### 2.2 Automation Engine
**File:** `eternal_quotex_bot/automation.py`

**Purpose:** Risk-managed auto-trading

**Logic:**
```
automation.can_trade(decision):
  |
  +-> Check 8 conditions (ALL must pass):
  |     1. automation_enabled == True
  |     2. active_trade_id is None (no open trade)
  |     3. decision.action != "HOLD"
  |     4. decision.confidence >= min_confidence (default 0.56)
  |     5. net_pnl < stop_profit (default 30.0)
  |     6. net_pnl > -stop_loss (default -20.0)
  |     7. consecutive_losses < max_consecutive_losses (default 3)
  |     8. (now - last_trade_at) > cooldown_seconds (default 90)
  |
  +-> Return: True if all pass, False otherwise
  |
  +-> If False, return reason for denial
```

**Risk Management:**
- Stop-profit: Halt trading when profit reaches $30
- Stop-loss: Halt trading when loss reaches $20
- Max consecutive losses: Halt after 3 losses in a row
- Cooldown: Wait 90 seconds between trades
- Max open trades: Only 1 trade at a time

**Session Tracking:**
- `SessionStats`: wins, losses, trades_taken, consecutive_losses, net_pnl
- Updated after each trade resolution

---

## 3. DATA FLOW PIPELINES

### 3.1 Price Capture Pipeline
```
Quotex Browser/WS
  |
  +-> backend/stream_prices()
  |     -> Live backend: browser JavaScript injection
  |     -> WS backend: WebSocket messages
  |
  +-> controller.update_tick_buffer(symbol, price, timestamp)
  |     |
  |     +-> tick_buffer.add_tick(symbol, price, timestamp)
  |           |
  |           +-> Append to tick list for symbol
  |           +-> Maintain max buffer size (prevent memory bloat)
  |
  +-> Candle generation on demand:
        -> tick_buffer.get_candles(symbol, count, period)
             |
             +-> Group ticks by time buckets (1min/2min/5min)
             +-> Calculate OHLCV for each bucket:
             |     - Open: first tick price
             |     - High: max tick price
             |     - Low: min tick price
             |     - Close: last tick price
             |     - Volume: tick count
             +-> Return completed candles only
```

**Key Files:**
- `tick_buffer.py` - Tick ingestion and candle generation
- `backend/live.py` - Browser price streaming
- `ws_worker_pool.py` - WebSocket data source

---

### 3.2 Signal Generation Pipeline
```
Candles Available
  |
  +-> Evaluate signal:
  |     Option A: advanced_engine.analyze(candles)
  |     Option B: evaluate_signal(candles, settings)
  |     Option C: sniper_scanner.scan(symbol)
  |
  +-> Indicator calculation:
  |     -> EMA, RSI, MACD, BB, Stochastic, etc.
  |     -> Weighted voting (CALL vs PUT scores)
  |     -> Confidence calculation
  |
  +-> Learning adjustment:
  |     -> learner.adjusted_confidence(signal, context)
  |          -> Apply historical performance weights
  |          -> Asset bias adjustment
  |          -> Context bias adjustment
  |
  +-> Duration preference:
  |     -> trend_strength -> recommended_duration
  |     -> Strong trend: 180s, Moderate: 120s, Weak: 60s
  |
  +-> Return StrategyDecision:
        -> Emit via signal_changed / candles_changed
        -> UI updates display
        -> Automation checks can_trade()
        -> If qualified: place_trade()
```

---

### 3.3 Learning Feedback Loop
```
Signal Generated
  |
  +-> learner.create_probe(signal, context)
  |     -> Record: confidence, trend, rsi, payout, etc.
  |     -> Set verify_at = now + learning_verify_seconds
  |
  +-> Wait for verification time
  |
  +-> controller._learning_cycle_async()
  |     |
  |     +-> Fetch price at verify time
  |     +-> learner.settle_probe(probe_id, result_price)
  |           |
  |           +-> Determine win/loss:
  |           |     CALL: result_price > reference_price -> win
  |           |     PUT: result_price < reference_price -> win
  |           |
  |           +-> _apply_outcome_update(probe, outcome)
  |                |
  |                +-> Update feature weights:
  |                |     - learning_rate = 0.14-0.32
  |                |     - weight += lr * (target - prediction) * feature
  |                |     - Clamp weights to [-3.0, 3.0]
  |                |
  |                +-> Update asset_stats:
  |                |     - Increment win/loss count
  |                |     - Track streaks
  |                |
  |                +-> Update context_stats:
  |                      - Group by feature vector similarity
  |
  +-> Save to signal_learner.json
  |
  +-> Future signals use adjusted_confidence()
        -> Combines raw confidence with learned probability
        -> Improves over time with more data
```

**Key Files:**
- `learning.py` - SignalLearner class
- `controller.py` - _learning_cycle_async() method

---

## 4. TELEGRAM INTEGRATION

### 4.1 Bot Command Flow
**File:** `eternal_quotex_bot/telegram_bot.py`

```
User sends message or presses button
  |
  +-> _process_update(update)
  |     |
  |     +-> If text message:
  |     |     -> Route to command handler
  |     |          /start, /menu -> _send_welcome()
  |     |          /help -> Help text + keyboard
  |     |
  |     +-> If callback query:
  |           -> Route by callback_data
  |                OTC -> _send_otc_market()
  |                REAL -> _send_real_market()
  |                P_OTC_N / P_REAL_N -> _deliver_signal()
  |                DEEP_SCAN -> _deep_scan_market()
  |                ADMIN -> _send_admin_panel()
  |                ADMIN_STATUS -> _send_admin_status()
  |                ADMIN_STATS -> _send_admin_stats()
  |                ADMIN_MSG -> _send_message_users()
  |                etc.
  |
  +-> Track user in _known_users
  |     -> chat_id, tier (FREE/PREMIUM/ADMIN)
  |     -> daily signal count
  |     -> cooldown tracking
  |
  +-> Enforce limits:
        -> FREE_DAILY_LIMIT = 15 signals/day
        -> COOLDOWN_SECONDS = 30 between same pair
```

**Signal Delivery:**
```
_deliver_signal(pair, chat_id)
  |
  +-> Check user limits (daily count, cooldown)
  +-> Trigger deep scan for pair
  +-> Format signal message:
  |     -> Pair name, direction, confidence
  |     -> Entry price, expiry time
  |     -> Engine name, timestamp
  |     -> Unicode box formatting
  |
  +-> Send message via Telegram API
  +-> Log to SignalHistoryEntry
  +-> Update user stats
```

**Broadcast Flow:**
```
broadcast_signal_with_chart(signal)
  |
  +-> Render chart:
  |     -> render_signal_chart(candles, action, confidence, symbol, entry_price)
  |     -> Returns PNG file path
  |
  +-> For each known user:
  |     -> Send text signal message
  |     -> Send chart photo
  |     -> Track sent_count
  |
  +-> Log broadcast completion
```

**Admin Features:**
- System status view
- Chart health monitoring
- User statistics
- Broadcast messaging
- User history browsing
- Browser capture testing
- Image delivery diagnostics

---

## 5. LICENSING SYSTEM

### 5.1 Validation Flow
**File:** `eternal_quotex_bot/licensing.py`

```
Application startup (if license enabled)
  |
  +-> LicenseGate dialog shown
  |     -> User enters license key
  |
  +-> LicenseClient.validate(key, machine_id, fingerprint)
  |     |
  |     +-> POST to LICENSE_API_URL
  |     |     Body: {
  |     |       license_key: key,
  |     |       machine_id: machine_display_id(),
  |     |       machine_fingerprint: machine_fingerprint(),
  |     |       app: "eternal_quotex_bot"
  |     |     }
  |     |
  |     +-> Server response:
  |     |     {
  |     |       valid: true/false,
  |     |       status: "active" | "disabled" | "revoked" | "expired",
  |     |       expires_at: ISO timestamp,
  |     |       machine_id: locked machine ID,
  |     |       reason: error message if invalid
  |     |     }
  |     |
  |     +-> If valid:
  |           -> Cache validation status
  |           -> Set cache_valid_until = now + poll_seconds
  |           -> Allow application to proceed
  |
  +-> If invalid:
        -> Show error message
        -> Block access
        -> Increment failure count
```

**Rate Limiting:**
```
LicenseAttemptTracker
  |
  +-> Track attempts in license_attempts.json
  +-> After 4 failed attempts:
  |     -> Lockout with escalating cooldown:
  |          1st: 2 minutes
  |          2nd: 5 minutes
  |          3rd: 10 minutes
  |          4th: 20 minutes
  |          5th+: 30 minutes
  |
  +-> Reset on successful validation
```

**Machine Locking:**
- First validation binds license to machine_id
- Subsequent validations check machine match
- Prevents license sharing across devices

---

## 6. UI COMPONENTS

### 6.1 Main Window Structure
**File:** `eternal_quotex_bot/ui/main_window.py`

**13 Tabs:**

| Tab | Builder Method | Key Components |
|-----|---------------|----------------|
| **Markets** | `_build_dashboard_page()` | Welcome banner, toolbar, chart, signal display, market focus card, scan focus card |
| **Chart Studio** | `_build_chart_studio_page()` | Asset combo, period combo, category combo, search, full_chart CandleChartWidget |
| **Strategy AI** | `_build_strategy_page()` | Signal values, confidence, RSI, trend, expiry, EMA/RSI/confidence controls, risk settings |
| **Live** | `_build_live_page()` | Connection center, provider panels (stacked), trade card, watchlist |
| **Telegram** | `_build_telegram_page()` | Runtime status, bot token, settings, preview, broker config |
| **Deep Scan** | `_build_deep_scan_page()` | Scan mode combo, sniper pairs, market health table, scan results, continuous monitor, learning brain |
| **Signal Format** | `_build_signal_format_page()` | Expiry combo, sticky signal spin, preview |
| **Auto Trading** | `_build_auto_trading_page()` | Automation card, session stats, PNL, state |
| **Auto History** | `_build_history_page()` | Trade journal table (8 columns) |
| **Pine Editor** | `_build_pine_editor_page()` | Indicator combo, editor, output, load/run/save/apply/clear buttons |
| **Log** | `_build_log_page()` | log_output QTextEdit (read-only) |
| **Settings** | Various | Connection settings, broker configs, license |
| **Admin** | `_build_admin_panel_page()` | Hidden by default, license management, matrix workers |

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

## 7. ERROR HANDLING & RECOVERY

### 7.1 Connection Errors
```
Backend connect() fails
  |
  +-> _handle_async_error(error)
  |     -> Clear flags: scan_in_progress, learning_busy, connecting
  |     -> Stop timers if not connected
  |     -> Disconnect backend (except during PIN flow)
  |     -> Emit connection_changed(False)
  |     -> Log error, emit status
  |
  +-> User can retry with correct credentials
```

### 7.2 Signal Engine Failures
```
analyze() or evaluate_signal() raises exception
  |
  +-> Catch exception
  +-> Fallback chain:
  |     1. Try simpler engine
  |     2. Try tick momentum analysis
  |     3. Return neutral HOLD
  |
  +-> Log error for diagnostics
  +-> Continue operation (don't crash)
```

### 7.3 Trade Execution Failures
```
place_trade() returns False or raises exception
  |
  +-> Log error
  +-> Emit trade_failed signal
  +-> Continue operation
  +-> User can retry manually
```

### 7.4 Telegram API Failures
```
API call timeout or HTTP error
  |
  +-> Retry with exponential backoff:
  |     1s -> 2s -> 4s -> 8s -> 10s (max)
  +-> On SSLError: retry without SSL verification
  +-> On edit failure: send new message instead
  +-> Log error for diagnostics
```

### 7.5 License Validation Failures
```
API returns invalid or rate limited
  |
  +-> Increment failure count
  +-> Enforce cooldown period
  +-> Persist to license_attempts.json
  +-> User must wait or contact admin
```

---

## 8. CONFIGURATION SETTINGS

### 8.1 Strategy Settings
| Parameter | Default | Purpose |
|-----------|---------|---------|
| fast_ema | 9 | Fast EMA period for crossover |
| slow_ema | 21 | Slow EMA period for crossover |
| rsi_period | 14 | RSI calculation period |
| min_confidence | 0.56 | Minimum confidence for auto-trade |
| auto_trade_enabled | False | Enable automatic trading |
| deep_scan_min_confidence | 0.50 | Minimum confidence for deep scan signals |
| preferred_expiry_seconds | 120 | Default trade duration |
| sticky_signal_seconds | 75 | Signal persistence time |
| learning_enabled | False | Enable adaptive learning |
| learning_interval_seconds | 45 | Learning check interval |
| learning_verify_seconds | 120 | Time to verify signal outcome |

### 8.2 Risk Settings
| Parameter | Default | Purpose |
|-----------|---------|---------|
| stop_profit | 30.0 | Halt trading at this profit |
| stop_loss | 20.0 | Halt trading at this loss |
| max_consecutive_losses | 3 | Halt after N consecutive losses |
| cooldown_seconds | 90 | Wait time between trades |
| max_open_trades | 1 | Maximum simultaneous trades |

### 8.3 Connection Settings
| Parameter | Default | Purpose |
|-----------|---------|---------|
| provider | mock | Broker provider (quotex/iq_option/exness/mock) |
| primary_broker | quotex | Primary broker for trading |
| account_mode | PRACTICE | Practice or Live mode |
| candle_period | 60 | Candle timeframe in seconds |
| trade_duration | 120 | Default trade duration |
| trade_amount | 5.0 | Default trade amount |
| browser_engine | selenium | Browser automation engine |
| data_source | browser | Price data source |

### 8.4 Telegram Settings
| Parameter | Default | Purpose |
|-----------|---------|---------|
| enabled | False | Enable Telegram bot |
| bot_token | "" | Telegram Bot API token |
| engine_name | "Eternal AI Bot (Apex Engine v214)" | Bot display name |
| free_daily_limit | 15 | Free user daily signal limit |
| cooldown_seconds | 30 | Cooldown between same pair scans |
| max_history | 500 | Maximum history entries |
| max_known_users | 200 | Maximum tracked users |

### 8.5 License Settings
| Parameter | Default | Purpose |
|-----------|---------|---------|
| enabled | False | Enable license validation |
| api_url | "" | License server API URL |
| api_token | "" | Shared API token |
| license_key | "" | User's license key |
| poll_seconds | 30 | Validation check interval |
| machine_lock_enabled | True | Lock license to machine |

---

## 9. DEEPSCAN DETAILED ALGORITHMS

### 9.1 OTC Pattern Detection
```
_detect_repeating_patterns(prices, min_len=3, max_len=8, tolerance=0.05)
  |
  +-> Calculate price changes: changes[i] = prices[i] - prices[i-1]
  +-> For each pattern length L from 3 to 8:
  |     +-> Take last L changes as candidate pattern
  |     +-> Search for repeated occurrences
  |     +-> If found >= 2 occurrences with tolerance:
  |           -> Return pattern string, direction, confidence
  |
  +-> Return empty if no pattern found
```

### 9.2 Tick Momentum Analysis
```
_tick_momentum_analysis(prices, lookback=20)
  |
  +-> Take last N prices
  +-> Assign exponential weights: w[i] = exp(-i/lookback)
  +-> Linear regression on weighted prices
  +-> Return slope normalized to [-1.0, 1.0]
  +-> Positive = upward momentum, Negative = downward
```

### 9.3 Multi-Timeframe Confirmation
```
get_multi_timeframe_candles(symbol)
  |
  +-> Build 1min candles
  +-> Build 2min candles
  +-> Build 5min candles
  +-> Check EMA alignment across timeframes:
  |     - All timeframes show CALL -> strong alignment
  |     - Mixed -> weak alignment
  |     - All show PUT -> strong alignment (reverse)
  |
  +-> Apply confidence bonus for alignment
```

---

## 10. MATRIX ORCHESTRATOR

### 10.1 Multi-Account Trading
**File:** `eternal_quotex_bot/matrix_orchestrator.py`

```
Matrix enabled with N workers
  |
  +-> Create worker thread for each account:
  |     -> Connect to broker
  |     -> Share signal from primary
  |     -> Execute trade independently
  |
  +-> Aggregator collects results:
  |     -> Total wins, losses
  |     -> Per-account performance
  |     -> Combined PNL
  |
  +-> Error isolation:
  |     -> One worker failure doesn't affect others
  |     -> Failed worker retries independently
  |
  +-> Session persistence:
        -> Save session data per email
        -> Restore on restart
```

**Worker Configuration:**
- Pre-configured test accounts in MatrixSettings
- Email/password per worker
- Enable/disable per worker
- Session caching for faster reconnects

---

## 11. PINE SCRIPT INTEGRATION

### 11.1 Custom Indicators
**File:** `eternal_quotex_bot/pine_script.py`

```
User writes Pine Script in editor
  |
  +-> Compile script:
  |     -> Parse Pine Script syntax
  |     -> Extract indicator calculations
  |     -> Generate Python equivalent
  |
  +-> Apply to chart:
  |     -> Calculate indicator values
  |     -> Overlay on price chart
  |     -> Generate buy/sell signals
  |
  +-> Save/Load scripts:
  |     -> Persist to local storage
  |     -> Load on demand
  |
  +-> Run backtest:
        -> Apply to historical candles
        -> Calculate performance metrics
```

---

## 12. VISUAL SIGNALS

### 12.1 Signal Formatting
**File:** `eternal_quotex_bot/visual_signals.py`

```
build_boxed_caption(signal, include_chart=True)
  |
  +-> Format signal data:
  |     -> Pair name, direction (CALL/PUT)
  |     -> Confidence percentage
  |     -> Entry price, expiry
  |     -> RSI, trend strength
  |
  +-> Add Unicode box drawing:
  |     -> ╔════════════════╗
  |     -> ║  SIGNAL INFO   ║
  |     -> ╚════════════════╝
  |
  +-> Add emoji indicators:
  |     -> ✅ CALL
  |     -> 🔴 PUT
  |     -> ⏳ HOLD
  |
  +-> Include chart image if available
  +-> Return formatted string
```

### 12.2 Chart Rendering
**File:** `eternal_quotex_bot/ui/charts.py`, `chart_renderer.py`

```
render_signal_chart(candles, action, confidence, symbol, entry_price)
  |
  +-> Create mplfinance figure:
  |     -> OHLC candlestick chart
  |     -> Volume bars (optional)
  |     -> EMA overlays (fast/slow)
  |
  +-> Add signal marker:
  |     -> Green arrow for CALL
  |     -> Red arrow for PUT
  |     -> Entry price line
  |
  +-> Add title:
  |     -> Symbol, timeframe
  |     -> Action, confidence%
  |
  +-> Save to PNG file
  +-> Return file path
```

---

## 13. BROWSER AUTOMATION

### 13.1 Live Quotex Backend
**File:** `eternal_quotex_bot/backend/live.py`

```
connect(email, password, mode, headless)
  |
  +-> Initialize browser:
  |     -> Selenium with undetected_chromedriver
  |     -> OR Playwright browser engine
  |     -> Load cached session if available
  |
  +-> Navigate to Quotex login
  +-> Fill credentials
  +-> Handle email PIN if required:
  |     -> Pause for user input
  |     -> Resume after PIN entry
  |
  +-> Wait for dashboard load
  +-> Inject JavaScript for price streaming:
  |     -> Subscribe to WebSocket
  |     -> Stream prices to Python
  |
  +-> Cache session cookies:
  |     -> Save to quotex_session.pkl
  |     -> Reuse on next login
  |
  +-> Start price update loop
  +-> Emit connected signal
```

**Price Streaming:**
```
JavaScript injection:
  -> Subscribe to Quotex WebSocket
  -> On price update:
  |     -> Call Python via bridge
  |     -> controller.update_tick_buffer(symbol, price, timestamp)
  |
  -> Fallback: Poll DOM for prices
```

**WebSocket Pool:**
- Multiple WS connections for redundancy
- Fallback data source when browser fails
- Manages connection lifecycle

---

This document provides complete mapping of features to their logic implementations. Use it alongside `code.md` for full project understanding.
