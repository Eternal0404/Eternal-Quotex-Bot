# Eternal Quotex Bot - Technical Documentation

## Overview

Eternal Quotex Bot is a Python desktop application for automated binary options trading on the Quotex broker platform. It uses Playwright for browser automation and WebSocket for real-time price data.

**Current State**: Working with fixes applied for WebSocket and token extraction issues.

---

## Project Structure

```
Eternal Quotex Bot Source/
├── main.py                 # Entry point
├── main.spec              # PyInstaller spec file
├── build_exe.ps1         # Build script
├── eternal_quotex_bot/
│   ├── __init__.py
│   ├── app.py           # Main app initialization
│   ├── backend/
│   │   ├── playwright_bridge.py   # KEY FILE - Playwright + WebSocket handling
│   │   ├── selenium_bridge.py
│   │   └── quotex_api.py
│   ├── ui/
│   │   ├── main_window.py    # UI with QTextEdit logging
│   │   └── ...
│   └── ...
├── dist/
│   └── EternalQuotexBot_v5.exe  # Built executable
└── requirements.txt
```

---

## Architecture

### Authentication Flow

1. **Browser Launch**: Uses system Chrome/Edge via Playwright (no bundled browsers needed)
2. **Login**: Fill email/password, submit form
3. **2FA**: Detect PIN input, request from user via callback
4. **Token Extraction**: Extract SSID from cookies/localStorage after login

### WebSocket Handling (CRITICAL)

**Problem**: Playwright's intercepted WebSocket objects are READ-ONLY. You CANNOT call `ws.send()` on them.

**Solution**: Use JavaScript injection via `page.evaluate()` to find and send through the browser's actual WebSocket:

```python
# In _do_subscribe() method:
async def _send_via_js():
    result = await page.evaluate("""(msgs) => {
        let ws = null;
        // Method 1: Look for io.engine.transport.ws
        if (window.io && window.io.engine && window.io.engine.transport && window.io.engine.transport.ws) {
            ws = window.io.engine.transport.ws;
        }
        // Method 2: Search all globals for WebSocket
        if (!ws) {
            for (const key of Object.keys(window)) {
                const obj = window[key];
                if (obj && obj instanceof WebSocket && obj.readyState === WebSocket.OPEN) {
                    ws = obj; break;
                }
            }
        }
        // Send messages
        if (ws) {
            for (const msg of msgs) {
                ws.send(msg);
            }
            return {success: true};
        }
        return {success: false};
    }""", messages)
```

### Authentication Events

After WebSocket connects, Quotex sends confirmation events:
- `42["s_authorization"]` - Auth success
- `451-["instruments/list", {"_placeholder":true}]` - Auth confirmed

**CRITICAL**: When these events arrive, trigger subscription via `_do_subscribe()`. Use `self._session.page` as fallback if `self._page` is None (page may have navigated after login).

---

## Key Fixes Applied

### 1. WebSocket Send Error (FIXED)
**Error**: `'WebSocket' object has no attribute 'send'`

**Cause**: Playwright intercepted WebSockets are read-only

**Fix**: Use JS injection (see Architecture section above)

### 2. Token Extraction Context Destroyed (FIXED)
**Error**: `Page.evaluate: Execution context was destroyed, most likely because of a navigation`

**Cause**: Page navigates after login while token extraction is running

**Fix**: Catch the error and return empty string - `_wait_for_auth()` will retry:
```python
except Exception as e:
    err_msg = str(e).lower()
    if "execution context was destroyed" in err_msg or "navigation" in err_msg:
        self._log("warn", "Token extraction: page navigating, will retry...")
        return ""
```

### 3. No Page for WebSocket (FIXED)
**Error**: `No page for WebSocket subscriptions`

**Cause**: `self._page` is None after navigation, but WebSocket listener is still active

**Fix**: Use fallback chain:
```python
page = getattr(self, '_page', None)
if not page and self._session and self._session.page:
    page = self._session.page
```

### 4. QTextEdit setMaximumBlockCount (FIXED)
**Error**: `'PySide6.QtWidgets.QTextEdit' object has no attribute 'setMaximumBlockCount'`

**Fix**: Use document limit instead:
```python
doc = self.log_output.document()
doc.setMaximumBlockCount(10000)
```

---

## Price Data Handling

### WebSocket Frame Formats

Quotex sends data in two formats:

1. **Engine.IO format**: `451-["event_name", data]`
2. **Socket.IO format**: `42["event_name", data]`

### Price Data Parsing

```python
def _handle_market_event(self, event_name: str, data: Any) -> None:
    # Skip placeholders
    if isinstance(data, dict) and data.get("_placeholder"):
        return
    
    # Handle list format: ["symbol", timestamp, price]
    if isinstance(data, list) and len(data) >= 3:
        symbol = data[0].upper() + "_OTC"
        price = data[2]  # Usually index 2
        self._tick_history[symbol].append({"time": timestamp, "price": price})
    
    # Handle dict format: {"symbol": "EURUSD_otc", "price": 1.0856}
    elif isinstance(data, dict):
        symbol = data.get("symbol", "").upper() + "_OTC"
        price = data.get("price", 0)
```

---

## Building the EXE

### Prerequisites
- Python 3.12+
- All requirements installed: `pip install -r requirements.txt`
- PyInstaller: `pip install pyInstaller`

### Build Command
```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

### Output
- Location: `dist/EternalQuotexBot_v5.exe`
- Size: ~334MB (includes Python runtime, Playwright, browsers)

---

## Known Limitations

1. **Token Extraction Timing**: After login navigation, token extraction may fail initially. The wait loop should retry.

2. **WebSocket Subscription**: Sometimes JS injection can't find WebSocket. Current approaches:
   - `window.io.engine.transport.ws`
   - Search all `window.*` globals for `WebSocket` instance
   - Hook `window.io.connect` for future connections

3. **No Prices Flowing**: If subscriptions fail, you'll only see placeholder frames like `451-["quotes/stream",{"_placeholder":true}]` with no actual price data.

---

## Troubleshooting

### App Won't Start
- Check: Is Chrome/Edge installed?
- Check: Any missing DLLs? Rebuild with fresh virtualenv

### Login Fails
- Check credentials
- Check: Is Quotex site accessible in browser?
- Check log for specific error

### No Live Prices
1. Check log for "No page for WebSocket subscriptions" - if present, needs rebuild with fix
2. Check log for subscription success: "Subscribed to N pairs"
3. If only `{"_placeholder":true}` frames, subscription via JS failed

### UI Crashes
- Check PySide6 version compatibility
- Check log for specific error

---

## Development Notes

### Page Reference Storage
After login, store page reference in BOTH:
- `self._page` (set during connect)
- `self._session.page` (set in PlaywrightSession)

This ensures WebSocket listeners can access page even after navigation.

### Async Context
`_do_subscribe()` uses `page.evaluate()` which is async. Be careful with:
```python
# Wrong - doesn't await
asyncio.ensure_future(_send_via_js())

# Correct for sync context:
loop = asyncio.get_event_loop()
if loop.is_running():
    asyncio.ensure_future(_send_via_js())
else:
    loop.run_until_complete(_send_via_js())
```

### Thread Safety
WebSocket callbacks come from Playwright's async context. Use `threading.Timer` for delayed operations:
```python
import threading
threading.Timer(2.0, do_immediate_sub).start()
```

---

## File Locations

- Log file: `%LOCALAPPDATA%\EternalQuotexBot\activity.log`
- Settings: `%LOCALAPPDATA%\EternalQuotexBot\settings.json`
- Session: `%LOCALAPPDATA%\EternalQuotexBot\session.json`

---

## Contact / References

- Quotex API: Uses Socket.IO protocol
- WebSocket: `wss://ws2.market-qx.trade/socket.io/`
- Playwright Python: https://playwright.dev/python/