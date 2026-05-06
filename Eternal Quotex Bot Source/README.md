# Eternal Quotex Bot

Eternal Quotex Bot is a clean Python desktop source project inspired by the workflow of the bundled TBT bot, but written as its own application under the Eternal name.

## What It Includes

- Original PySide6 desktop UI with dashboard, strategy, activity, and settings views
- **Dual-Mode Quotex Connector**: High-stability engine with auto-fallback between Selenium (undetected-chromedriver) and Playwright.
- **Zero-Dependency Playwright**: Uses the system's existing Chrome or Edge browser (no `playwright install` needed).
- Offline mock mode for safe UI testing without a broker login
- Indicator-driven signal engine using EMA and RSI (Deep Scan Gen 2)
- Auto-trading guardrails with cooldown, stop-profit, stop-loss, and loss-streak limits
- Local JSON settings storage plus a dedicated runtime directory
- PyInstaller build script for generating a lean Windows `.exe`

## Run From Source

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Build EXE

The build process is optimized to include Playwright driver binaries while excluding heavy browser binaries.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

## License API

The desktop app now includes a built-in license client and admin panel.

If you want a ready-made hosted setup, use the included Supabase starter:

- `LICENSE_SETUP.md`
- `supabase/sql/license_schema.sql`
- `supabase/functions/license-validate/index.ts`

The admin panel can now generate, create, revoke, and list licenses through that same Supabase function.

## Notes

- **Quotex Connection**: The bot attempts a primary connection via Selenium. If login stalls or browser issues occur, it automatically falls back to a **Playwright-based bridge**.
- **Browser Requirements**: Requires a local installation of Google Chrome or Microsoft Edge.
- **Zero-Install**: The Playwright bridge is configured to use the `channel` parameter, removing the need for a separate 200MB browser download.
- **Deep Scan Gen 2**: The signal engine uses a confluence of 10+ indicators for 2-minute expiry decisions.
- **Mock Sandbox**: Included so the UI, charting, strategy, and trade journal can be tested without hitting the live broker.
- The app stores runtime files under `%LOCALAPPDATA%\EternalQuotexBot`.
