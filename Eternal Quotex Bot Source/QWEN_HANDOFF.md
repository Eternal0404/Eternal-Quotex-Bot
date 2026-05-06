# Qwen Handoff

## Project
- Name: `Eternal Quotex Bot`
- Root: `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source`
- Main entry: `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\main.py`
- Current packaged build:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\dist_rebuild\Eternal Quotex Bot\Eternal Quotex Bot.exe`

## What The App Does
- Desktop trading assistant built with `PySide6`
- Main live broker path is still `Quotex` browser automation
- Alternate browser path is `IQ Option`
- Real-market data path is now `Forex Market`
- `Forex Market` is data-only and does **not** route trades

## Important Architectural Files
- UI:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\ui\main_window.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\ui\charts.py`
- Controller:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\controller.py`
- Backends:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\backend\live.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\backend\external.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\backend\mock.py`
- Signal/learning:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\strategy.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\learning.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\automation.py`
- Telegram:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\telegram_bot.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\visual_signals.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\broker_adapters.py`
- Settings/models:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\models.py`
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\eternal_quotex_bot\settings.py`

## Current Provider State

### Quotex
- Main live automation path
- Browser-authenticated
- Uses `live.py`
- Still the only serious candidate for OTC-style pairs and execution inside this app

### IQ Option
- Browser automation path
- Uses the old `pocket_option` slot renamed into IQ Option in many places
- Data/trading quality not fully proven from sandbox

### Forex Market
- Former `Exness / MT5` slot was repurposed
- Now uses remote forex data only
- Implemented in `external.py` as `TwelveDataForexBackend`, but UI/log text now says only `Forex Market`
- Requires a **feed key**
- No terminal launching
- No trade routing

## Recent Forex Market Changes
- Old MT5/MetaTrader live flow is no longer the active runtime path
- `MetaTrader5` was removed from active packaging and requirements
- Forex page now shows:
  - a visible `Feed Key` field
  - no visible login/password fields
- Auto-connect for Forex Market is disabled unless a non-empty non-demo feed key exists
- Demo/default key behavior was removed from settings defaults
- Connection now fails once with a short message instead of connecting and then spamming the log

## Why The User Saw Errors
- Earlier builds hid the real feed-key field and defaulted to `demo`
- That caused:
  - the connection page to look glitched/overcrowded
  - repeated remote feed errors
- The newer build fixes that by:
  - increasing the provider panel height
  - exposing the feed-key field
  - starting with a blank key instead of demo

## Known Limits Right Now
- `Forex Market` is data-only
- It does not submit trades
- If the user wants real forex execution later, a real broker API is needed
- The app still contains historical naming like `exness_*` in models/settings fields for compatibility, but those fields are now effectively reused for the forex feed key path

## Key Compatibility Note
- Internal settings still store the forex feed key in `connection.exness_server`
- Telegram forex feed key still uses `telegram.exness_server`
- This was kept to avoid a large breaking migration of the saved settings schema

## UI State
- `Chart Studio` has been enlarged
- Full chart widget minimum height was increased
- Chart rendering uses stronger antialiasing and larger candle bodies
- Live connection panel for Forex Market now has a taller stack height so fields and notes do not overlap

## Tests
- Test folder:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\tests`
- Latest status before handoff:
  - `98` tests passing

## Packaging
- Build script:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\build_exe.ps1`
- Spec:
  - `C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\Eternal Quotex Bot.spec`
- Latest successful build output:
  - `dist_rebuild\Eternal Quotex Bot`

## Immediate Next Steps For Qwen
1. Open the current build and confirm the Forex Market page no longer overlaps visually.
2. If needed, further refine the left-column Live layout in `main_window.py`.
3. Decide whether to keep the reused `exness_*` settings schema or migrate to explicit `forex_feed_key` fields.
4. If migrating schema, update:
   - `models.py`
   - `settings.py`
   - `main_window.py`
   - `controller.py`
   - `telegram` wiring
   - tests
5. If real forex execution is desired later, add a real broker API instead of trying to make the current data-only provider submit trades.

## Session/History Note
- Do **not** rely on Codex session files or JSONL logs.
- This handoff file and the JSON handoff file are intended to replace session-history dependence.
- The next AI should use repository state plus these handoff files as the source of truth.
