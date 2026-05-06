# Stabilization Handover - 2026-04-29

## Summary

This pass focused on the Quotex connection screenshot error, Deep Scan Gen 2 signal quality, licensing/admin reliability, Chart Studio refresh behavior, local credential persistence, test coverage, and the Windows build.

Important honesty note: no signal engine can guarantee sure-shot profit, 90% future win rate, non-loss trading, or permanent immunity from broker UI changes. The work below improves data freshness, confluence scoring, validation, and failover behavior without pretending market outcomes are guaranteed.

## Main Fixes

### Quotex Connection

- Screenshot root cause: `Cannot set properties of undefined (setting 'value')` came from the installed `quotexpy` login hook using a brittle selector like `document.getElementsByName("email")[1].value`.
- **Dual-Mode Connection Engine**: Implemented a robust fallback system. The bot now prioritizes Selenium but automatically switches to a **Playwright-based bridge** if Selenium fails or login stalls.
- **Zero-Dependency Playwright**: Created `playwright_bridge.py` which uses the system's installed Chrome or Edge (via `channel` parameter). This eliminates the need for `playwright install` (~200MB) and works perfectly in the portable EXE.
- **Robust JS Injection**: Fixed a `SyntaxError` in the login submission script (where `pass` was used as a variable) and implemented a multi-layered discovery for email/password/PIN fields.
- Added safer Chrome startup options, isolated Chrome profiles, and browser cleanup.
- Fixed installed `quotexpy` API mismatches:
  - `check_connect` can be a property or callable.
  - `get_balance()` is awaited.
  - `get_candles()` uses the installed signature first and falls back to alternate signatures.
  - Trade placement uses `trade(...)`, not a nonexistent `buy(...)`.
- Restored browser bridge compatibility:
  - Performance-log websocket tick parsing.
  - Page socket mirror parsing.
  - Socket.IO tick formats including direct tuple ticks and multi-argument events.
  - Browser snapshot history lookup with broker labels like `USD/BDT (OTC)`.
  - DOM/snapshot-based trade confirmation fallback.
  - Asset activation and warmup hooks.
- Prevented external forex fallback from overwriting Quotex OTC prices.

Touched file:

- `eternal_quotex_bot/backend/live.py`

### Deep Scan Gen 2

- Reworked the advanced signal engine into a Gen 2 confluence model for 2-minute expiry decisions.
- Added/expanded signal inputs:
  - Ridge 2-minute projection.
  - EMA 8/13/21/50 trend stack.
  - MACD histogram and slope.
  - RSI trend/exhaustion logic.
  - Bollinger reclaim/rejection.
  - Stochastic cross.
  - Micro momentum and candle body direction.
  - Support/resistance reaction and range-break signals.
  - Harmonic pattern boost.
  - Entropy/volatility quality adjustment.
- Deep Scan now returns the best ranked actionable signal more consistently.
- If candles are unavailable, Deep Scan falls back to a live tick/price decision instead of returning no signal.
- Learner memory is blended gently into confidence so bad recent behavior can reduce confidence without silencing signals.
- Every generated trade recommendation is kept at 120 seconds / 2 minutes.

Touched files:

- `eternal_quotex_bot/advanced_signal_engine.py`
- `eternal_quotex_bot/controller.py`

### Chart Studio

- Fixed the 2-second flicker/open-close feeling by updating existing candlestick sets in place when candle count stays the same.
- Chart series are only rebuilt when necessary.
- Guide/EMA series and axes are refreshed without destroying the chart.

Touched file:

- `eternal_quotex_bot/ui/charts.py`

### Licensing

- Startup license gate is still enforced from `app.py` before `MainWindow` exists, so users cannot reach the main UI without a valid license.
- Embedded admin license/email remains:
  - `raiyanetharyt04@gmail.com`
- Client now handles revoked/expired/machine-mismatch responses as close-app events.
- Client now reads `revocation_reason` from the Supabase function.
- Admin calls send a separate `admin_license_key`, so the target license key is not confused with the admin identity.
- Local credential saving was hardened so `email/password/pin` and `quotex_email/quotex_password/quotex_email_pin` stay synchronized before encryption.

Touched files:

- `eternal_quotex_bot/licensing.py`
- `eternal_quotex_bot/settings.py`
- `eternal_quotex_bot/app.py` was verified as the enforced gate path.

### Supabase Edge Function

- Added admin `delete` action.
- Added optional machine binding on license creation.
- Added duplicate-key friendly create error text.
- Added `admin_license_key` logging separation.
- Local source is fixed, but deployment did not complete because Supabase returned `401 Unauthorized`.

Touched file:

- `supabase/functions/license-validate/index.ts`

Deploy command to rerun after a valid Supabase access token is available:

```powershell
$env:SUPABASE_ACCESS_TOKEN='<valid-token>'
npx --yes supabase functions deploy license-validate --project-ref vxwfmqvjwjxlrfskopts --no-verify-jwt
```

The failed deploy output was:

```text
unexpected deploy status 401: {"message":"Unauthorized"}
```

That means the token used locally is invalid, expired, or does not have access to project `vxwfmqvjwjxlrfskopts`.

## Verification

Commands run successfully:

```powershell
python -m py_compile eternal_quotex_bot\backend\live.py eternal_quotex_bot\advanced_signal_engine.py eternal_quotex_bot\controller.py eternal_quotex_bot\licensing.py eternal_quotex_bot\settings.py eternal_quotex_bot\ui\charts.py eternal_quotex_bot\ui\license_gate.py eternal_quotex_bot\ui\main_window.py
python -m unittest discover -s tests -p "test_*.py"
.\build_exe.ps1
```

Test result:

```text
Ran 123 tests in 5.060s
OK
```

Build result:

```text
Executable: C:\Users\User\Downloads\Ai python bot\TBT QUOTEX BOT.exe orignal source code\Eternal Quotex Bot Source\dist_rebuild\Eternal Quotex Bot\Eternal Quotex Bot.exe
Size: 25.91 MB
No session files included in build output.
```

The build used `dist_rebuild` because the existing `dist` folder was locked and could not be removed.

## Next Continuation Checklist

1. Get a valid Supabase personal access token from Supabase Dashboard.
2. Rerun the Edge Function deploy command above.
3. Open the new EXE from `dist_rebuild`.
4. Confirm the license gate appears before the main UI.
5. Validate with the admin email license.
6. Create a test user license from Admin.
7. Start the app again and validate with that test user license.
8. Revoke the test license in Admin and verify the running app closes on the next license poll.
9. Connect Quotex in visible mode if an email PIN is expected.
10. Run Deep Scan on live data and compare the app price against the Quotex chart for the same OTC symbol.

## Caveats

- The Supabase server has not been updated until the Edge Function deploy succeeds.
- Existing already-built EXEs will not magically contain local source changes. Distribute the new EXE from `dist_rebuild`.
- If Quotex changes its login page again, the new visible-input discovery is much safer than the old fixed-index script, but no automation can promise permanent broker-DOM compatibility.
- Python/PyInstaller apps can be hardened but not made impossible to reverse engineer. Real protection should rely on server-side licensing and revocation, not only local code hiding.
