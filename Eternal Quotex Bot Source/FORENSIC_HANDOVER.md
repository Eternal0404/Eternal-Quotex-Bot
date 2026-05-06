# Eternal Quotex Bot - Engineering Handover Documentation
## Version: v14.4.10 (Gold Master)
## Date: April 28, 2026

---

## 1. ARCHITECTURAL OVERVIEW
The Eternal Quotex Bot is a multi-threaded trading automation suite. It utilizes an asynchronous backend (Python/Asyncio) bridged to a PySide6 GUI. The core innovation, the **Sentinel Bridge**, provides high-stability browser automation by enforcing a serial, state-aware connection handshake.

---

## 2. KEY ARCHITECTURAL COMPONENTS

### 2.1 The Security Gate (Gate-First Protocol)
**File:** `eternal_quotex_bot/app.py`
- **Logic:** The `main()` function enforces a strict dependency chain: 
  1. Initialize QApplication.
  2. Instantiate `BotController` (headless state validation).
  3. Execute `run_license_gate()`: This is a synchronous, blocking call. If it does not return `True` (validated), `sys.exit(0)` is invoked before any UI is instantiated.
- **Why:** Prevents "Zero-UI" state leaks where the interface could be manipulated before validation.

### 2.2 The Sentinel Bridge (Browser Ignition)
**File:** `eternal_quotex_bot/backend/live.py`
- **Logic:** A 3-stage serial handshake implementation replacing original brittle Playwright/Selenium wrappers.
  - **Stage 1 (Ignition):** Driver ignition using `undetected-chromedriver` with stealth flags (`--disable-blink-features=AutomationControlled`, `--window-size=1920,1080`).
  - **Stage 2 (DOM Watchman):** A 180s polling loop that validates the existence of the Quotex login DOM. It prevents 'undefined' errors by forcing a Desktop resolution.
  - **Stage 3 (Settle Pass):** A 3s hard-coded delay post-handshake, allowing security scripts (Cloudflare/Anti-bot) to settle before credential injection.
- **Threading Model:** Ignition occurs on a dedicated `QThread` (`IgnitionThread`), keeping the UI responsive while the browser initializes.

### 2.3 The Infinity Apex Engine (Signal Logic)
**Files:** `eternal_quotex_bot/advanced_signal_engine.py`, `strategy.py`
- **System:** Weighted 15-indicator voting system.
- **Confidence Formula:** `0.48 + (dominance * 0.32)`.
- **OTC Safety Shield:** Integrated filtering for malformed candle data; the engine skips pairs that report invalid OHLC values rather than propagating crashes to the UI.

---

## 3. HISTORICAL BUG LOG & FORENSIC RESOLUTIONS

### 3.1 JavaScript/Selector Drift
- **Issue:** `javascript error: Cannot set properties of undefined (setting 'value')`.
- **Root Cause:** Quotex introduced a dynamic DOM loading strategy where input fields are rendered only after script execution.
- **Forensic Fix:** Shifted from "Blind Injection" to "Sentinel Watching." The backend now queries the `document.readyState` and element visibility status before calling `.value` assignments.

### 3.2 The "Ready" Status Deadlock
- **Issue:** UI stuck on "Ready" despite "Connect" button clicks.
- **Root Cause:** Blocking the Main Thread during Browser Ignition.
- **Forensic Fix:** Moved all browser-level startup operations to a non-blocking `IgnitionThread`.

### 3.3 Redundant License Prompts
- **Issue:** User received an initial license prompt followed by a secondary invalidation prompt.
- **Root Cause:** Race condition between `app.py` startup checks and `main_window.py` background polling.
- **Forensic Fix:** Removed the startup scheduling logic in `main_window.py`. License validation is now strictly governed by the startup gate and silent background polling.

---

## 4. BUILD & DEPLOYMENT INSTRUCTIONS

### 4.1 Environment
- **Python:** 3.12+
- **Framework:** PySide6
- **Driver:** `undetected-chromedriver` (must be updated to match local Chrome binary).

### 4.2 Building the Executable
1. Execute `build_exe.ps1` from the project root.
2. The script performs:
   - Environment variable loading (`LICENSE_API_URL`, `LICENSE_SHARED_TOKEN`).
   - Recursively deletes `dist/` and `build/` directories to prevent file locking.
   - Triggers `PyInstaller` with `hook` configurations for `PySide6`, `scipy`, and `pandas`.
3. Output is produced in `/dist/Eternal Quotex Bot/`.

---

## 5. MAINTENANCE PROTOCOL FOR FUTURE AI
1. **Never modify `app.py` startup sequence** unless the authentication model changes.
2. **Selector Drift Protocol:** If `undefined` field errors recur, update the JS-finder in `live.py` to include new selector fallbacks.
3. **Data Integrity:** Any changes to `models.py` MUST be mirrored in `controller.py` to ensure signal channels don't disconnect.
4. **Logs:** `Eternal Quotex Bot Source\.quotexpy.log` is the source of truth for connection failures. Analyze timestamps before attempting code changes.
