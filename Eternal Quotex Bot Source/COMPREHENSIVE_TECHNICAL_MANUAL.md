# MASTER ENGINEERING BRIEFING: ETERNAL QUOTEX BOT ARCHITECTURE
**Date: April 30, 2026**
**Subject: Stabilization, WebSocket Tunneling, and Multi-Engine Redundancy**

## 1. EXECUTIVE SUMMARY
The Eternal Quotex Bot is a hybrid trading platform that integrates a Playwright-controlled browser environment with a modified `quotexpy` backend. The primary challenge resolved in this iteration was the "Data Blackout" caused by Quotex mirror domain redirection and the rigid, hardcoded connection logic of the `quotexpy` library. This document provides a deep-dive for the successor AI to maintain the current "Bulletproof" state.

---

## 2. THE CONNECTIVITY STACK: "WS TUNNELING"
The bot no longer relies on guessing the Quotex WebSocket endpoint. Instead, it implements a "Spy-and-Sync" strategy.

### A. The Interception Mechanism (`playwright_bridge.py`)
We use `page.on("websocket")` to intercept the browser's native connection. 
*   **Mirror Detection**: We extract the `base_url` (e.g., `market-qx.trade`) directly from the page state because the server frequently redirects users to regional mirrors.
*   **URL Capture**: We capture the *full* `wss://` URL used by the browser, including the `sid` and `transport=websocket` parameters. This URL is stored in `PlaywrightSession.captured_ws_url`.

### B. The backend Handoff (`live.py`)
In `_connect_via_playwright`, we hand off the browser's credentials to the `quotexpy` client.
*   **Token Injection**: We set `api.SSID = session.token`. Note that `api.ssid` (lowercase) is a property that returns the `Ssid` channel object. Overwriting lowercase `ssid` with a string will crash the WebSocket thread with a `TypeError`. **ALWAYS use `api.SSID` (uppercase) for the token string.**
*   **Domain Alignment**: We inject `api.base_url` and `api.captured_ws_url`. These are custom attributes we added to the `QuotexAPI` instance to bypass hardcoded defaults.

---

## 3. THE MONKEY-PATCH SUITE
The `quotexpy` library (v1.x) is designed for a standalone Selenium flow. To make it work inside our Playwright/PyInstaller environment, we have applied critical runtime overrides in `_ensure_quotexpy_runtime_patch`.

### A. `Quotex.connect` Override
The original `connect` method recreates the `api` object, destroying our injected token. Our patch:
1.  Detects if an `SSID` already exists on the instance.
2.  If found, it **skips** the `api = QuotexAPI(...)` constructor call.
3.  It calls `api.connect()` directly using the existing, pre-configured instance.

### B. `QuotexAPI.start_websocket` Override
This is the most critical patch. The original method has hardcoded `origin` and `host` values (`qxbroker.com`). 
*   **The Fix**: Our patch uses `urlparse` to decompose the `base_url`. It dynamically calculates the `ws_host` and `ws_origin` to match the mirror.
*   **Handshake Alignment**: If the origin sent in the WebSocket header doesn't match the domain where the token was issued, the Quotex server returns a `403`. Our dynamic patch ensures perfect alignment.

### C. `QuotexAPI.check_session` Override
We forced this method to return the memory-injected `SSID` and `cookies` immediately. This prevents the library from attempting to read `.session.pkl` from the filesystem, which is non-deterministic in a frozen EXE environment.

---

## 4. DATA REDUNDANCY: THE "FAIL-OVER" PATH
To satisfy the requirement of "confirmed data reception," we implemented a secondary data pipeline.

### WebSocket-Interception Fallback
Even if the `quotexpy` WebSocket is blocked, `PlaywrightQuotexBridge` listens to the *browser's* WebSocket frames. 
*   It parses Engine.IO frames (starting with `42`).
*   It extracts `tick`, `quotes`, and `candles` events.
*   It stores these in `self._tick_history`.

### UI-Scraping Fallback
In `live.py`, the `fetch_assets` method now follows this priority:
1.  **Level 1**: Request via authorized `quotexpy` WebSocket (Primary).
2.  **Level 2**: If primary returns empty, call `PlaywrightQuotexBridge.get_instruments()`. This method executes JavaScript on the browser page to scrape the asset list from the DOM.
3.  **Level 3**: If a price is missing, check the captured `tick_history` from the browser's intercepted frames.

---

## 5. RECOVERY & 2FA HANDLING
The 2FA flow is handled asynchronously. 
*   If the browser detects a 2FA prompt, it triggers the `pin_callback`.
*   The UI pauses, the user enters the PIN, and the Playwright bridge resumes.
*   The `PlaywrightSession` is only returned *after* the browser URL contains `/trade`, ensuring the token is fully authorized before the WebSocket attempts to connect.

## 6. INSTRUCTIONS FOR SUCCESSOR AI
*   **Build Integrity**: Always use `build_exe.ps1`. If you change imports, you must verify the PyInstaller hidden-imports in the `.spec` file.
*   **Debugging**: If "WebSocket failed to open" appears in the log, check the `ws_origin` vs `ws_host` in the `live.py` print statements. Any mismatch will cause a 403.
*   **Data Stream**: The `_apply_price_update` method is the gatekeeper for the UI charts. Ensure any new data source calls this method to keep the charts moving.

**Status: STABLE / BULLETPROOF**
**Handover Complete.**
