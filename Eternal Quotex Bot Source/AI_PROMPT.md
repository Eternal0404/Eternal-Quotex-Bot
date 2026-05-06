# Prompt for AI Developer: Quotex Bot Rebuild

---

## TASK SUMMARY
Rebuild the Eternal Quotex Bot EXE from source with fixes for WebSocket send errors, token extraction crashes, and subscription failures. The bot must connect to Quotex broker, extract live price data from WebSocket, and display prices in the UI.

---

## CRITICAL ISSUES TO FIX

### 1. WebSocket Send Error
**ERROR LOG**: `Immediate sub failed: 'WebSocket' object has no attribute 'send'`

**ROOT CAUSE**: Playwright's intercepted WebSocket objects are READ-ONLY. You cannot call `ws.send()` on them.

**FIX REQUIRED**: Use JavaScript injection via `page.evaluate()` to send messages through the browser's actual WebSocket. Example pattern:
```python
result = await page.evaluate("""(msgs) => {
    let ws = null;
    // Method 1: window.io.engine.transport.ws
    if (window.io?.engine?.transport?.ws) {
        ws = window.io.engine.transport.ws;
    }
    // Method 2: Search globals for WebSocket instance
    if (!ws) {
        for (const key of Object.keys(window)) {
            try {
                const obj = window[key];
                if (obj instanceof WebSocket && obj.readyState === WebSocket.OPEN) {
                    ws = obj; break;
                }
            } catch(e) {}
        }
    }
    // Method 3: Hook future connections via window.io.connect
    if (!ws && window.io) {
        const orig = window.io.connect;
        window.io.connect = function(...args) {
            const socket = orig.apply(this, args);
            socket.on('connect', () => {
                if (socket.io?.engine?.transport?.ws) {
                    window._quotex_ws_hook = socket.io.engine.transport.ws;
                }
            });
            return socket;
        };
    }
    // Send messages
    if (ws) {
        for (const msg of msgs) { ws.send(msg); }
        return {success: true, sent: msgs.length};
    }
    return {success: false, error: 'No WebSocket found'};
}""", messages)
```

---

### 2. Token Extraction Context Destroyed
**ERROR LOG**: `Token extraction error: Page.evaluate: Execution context was destroyed, most likely because of a navigation`

**ROOT CAUSE**: Page navigates after login form submission while token extraction JavaScript is running.

**FIX REQUIRED**: Catch the navigation error and return empty string - the wait loop will retry:
```python
except Exception as e:
    err_msg = str(e).lower()
    if "execution context was destroyed" in err_msg or "navigation" in err_msg:
        self._log("warn", "Token extraction: page navigating, will retry...")
        return ""
    self._log("warn", f"Token extraction error: {e}")
    return ""
```

---

### 3. No Page for WebSocketSubscriptions
**ERROR LOG**: `No page for WebSocket subscriptions`

**ROOT CAUSE**: `self._page` becomes None after login navigation, but WebSocket listener is still active.

**FIX REQUIRED**: Use fallback chain to get page reference:
```python
page = getattr(self, '_page', None)
if not page and self._session and self._session.page:
    page = self._session.page
if not page:
    self._log("warn", "No page available for WebSocket subscriptions")
    return
```

---

### 4. QTextEdit setMaximumBlockCount
**ERROR LOG**: `'PySide6.QtWidgets.QTextEdit' object has no attribute 'setMaximumBlockCount'`

**ROOT CAUSE**: PySide6's QTextEdit doesn't have this method.

**FIX REQUIRED**: Use document limit instead:
```python
doc = self.log_output.document()
doc.setMaximumBlockCount(10000)  # Keep last 10k lines
```

---

## ARCHITECTURE REQUIREMENTS

### Playwright Setup
- Use system Chrome/Edge: `executable_path` to Chrome or Edge install location
- NOT headless: Quotex blocks headless browsers
- Use Playwright channel: `chrome` or `msedge`
- Store page reference in BOTH `self._page` AND `self._session.page`

### WebSocket Subscription Flow
1. WebSocket connects → `_attach_ws_listener(ws)` called
2. Wait 2 seconds → `threading.Timer(2.0, do_immediate_sub).start()`
3. In `do_immediate_sub()` → call `_do_subscribe()`
4. `_do_subscribe()` → uses page.evaluate() to inject JS and send subscription messages
5. Subscription format: `42["instruments/update",{"asset":"EURUSD_otc","period":0}]`
6. Also subscribe to: `42["depth/follow","EURUSD_otc"]` and `42["tick"]`

### Multi-Pair Price Handling
Subscribe to these pairs (all with `_otc` suffix):
```python
self._pending_subscriptions = [
    "EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc", "USDJPY_otc",
    "EURJPY_otc", "GBPJPY_otc", "USDCAD_otc", "USDCHF_otc",
    "EURGBP_otc", "USDBDT_otc", "NZDCAD_otc", "USDEGP_otc",
    "NZDUSD_otc", "USDMXN_otc", "AUDCHF_otc", "USDCOP_otc",
    "USDINR_otc", "USDPKR_otc", "EURNZD_otc", "USDDZD_otc",
    "USDZAR_otc", "USDARS_otc", "CADCHF_otc", "AUDNZD_otc", "USDIDR_otc"
]
```

### Price Data Parsing
Handle these WebSocket frame formats:

1. **List format**: `["symbol", timestamp, price]`
```python
if isinstance(data, list) and len(data) >= 3:
    symbol = data[0].upper() + "_OTC"
    price = data[2]  # Usually index 2
```

2. **Dict format**: `{"symbol": "EURUSD_otc", "price": 1.0856}`
```python
elif isinstance(data, dict):
    symbol = data.get("symbol", "").upper() + "_OTC"
    price = data.get("price", 0)
```

3. **Skip placeholders**: `{"_placeholder": True}`
```python
if isinstance(data, dict) and data.get("_placeholder"):
    return  # Skip acknowledgments
```

---

## SOURCE FILES TO EDIT

1. **`eternal_quotex_bot/backend/playwright_bridge.py`** - Main fixes:
   - `_attach_ws_listener()` - Add page fallback
   - `_do_subscribe()` - Add page fallback, use JS injection
   - `_process_ws_frame()` - Add page fallback for heartbeat pong
   - `_handle_market_event()` - Better logging for received prices
   - `_extract_token()` - Catch navigation errors

2. **`eternal_quotex_bot/ui/main_window.py`** - Fix QTextEdit:
   - In `_build_log_page()`: Replace `self.log_output.setMaximumBlockCount()` with `self.log_output.document().setMaximumBlockCount()`

---

## BUILD INSTRUCTIONS

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Output: `dist/EternalQuotexBot_v5.exe`

---

## TESTING CHECKLIST

After rebuild, verify:

1. [ ] App launches without crash
2. [ ] Login form fills and submits
3. [ ] 2FA PIN prompt works
4. [ ] WebSocket connects (check log: "WebSocket detected: wss://...")
5. [ ] No "No page for WebSocket subscriptions" error
6. [ ] Subscription messages sent (check log: "Subscribed to N pairs")
7. [ ] Live prices appear (check log: "PRICE EURUSD_OTC = 1.0856" or "TICK EURUSD_OTC: 1.0856")
8. [ ] Log panel shows data (no QTextEdit error)

---

## KEY FILES IN PROJECT

- `eternal_quotex_bot/backend/playwright_bridge.py` - WebSocket and login logic
- `eternal_quotex_bot/ui/main_window.py` - UI with log panel
- `eternal_quotex_bot/backend/selenium_bridge.py` - Fallback Selenium bridge
- `main.py` - Entry point
- `main.spec` - PyInstaller spec
- `build_exe.ps1` - Build script

---

## LOG FILE LOCATION
`%LOCALAPPDATA%\EternalQuotexBot\activity.log`

---

## QUOTEX WEBSOCKET DETAILS
- URL: `wss://ws2.market-qx.trade/socket.io/?EIO=3&transport=websocket`
- Protocol: Socket.IO
- Auth event: `42["s_authorization"]`
- Subscribe: `42["instruments/update",{"asset":"PAIR_otc","period":0}]`
- Price stream: `451-["quotes/stream",{"_placeholder":true}]` (placeholder, no actual data yet means subscription failed)

---

## EXPECTED SUCCESS LOG PATTERN
```
WebSocket detected: wss://ws2.market-qx.trade/socket.io/...
Immediate subscription to all OHLC pairs...
Subscribed to 25 pairs (ws.send, sent=25)
WS frame: 451-["quotes/stream",...]
PRICE EURUSD_OTC = 1.0856 (or TICK: message)
```

---

## IF PRICES STILL DON'T WORK
If after fixes you only see `{"_placeholder":true}` with no actual price data in frames, the JS injection is finding the WebSocket but the subscription format may be wrong. Try these alternative formats:
- `42["instruments/update",{"asset":"EURUSD_otc","period":60}]` (60 = 1min candle)
- `42["depth/follow","EURUSD_otc"]` (depth follows price)
- `42["tick"]` (request all ticks)
- `42["subscribe",{"asset":"EURUSD_otc"}]` (alternative event name)

The bot should try multiple subscription formats and log which one works.