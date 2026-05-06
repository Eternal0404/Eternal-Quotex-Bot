"""
Playwright-based Quotex Browser Bridge.

Uses the system's installed Chrome or Edge browser (via Playwright's 'channel'
parameter) so NO separate "playwright install" is needed.  This makes the bridge
work inside a PyInstaller bundle without shipping 200+ MB of Chromium binaries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PlaywrightSession:
    """Result of a successful Playwright login."""
    ssid: str = ""
    cookies: str = ""
    user_agent: str = ""
    token: str = ""
    page: Any = None
    browser: Any = None
    context: Any = None
    base_url: str = ""
    captured_ws_url: str = ""


def _find_system_chrome() -> str | None:
    """Return the path to an installed Chrome or Edge executable, or None."""
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
    # On Linux/macOS we just try well-known names
    for name in ("google-chrome", "google-chrome-stable", "chromium", "msedge"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _detect_channel() -> str:
    """Pick the best Playwright channel for the system browser."""
    chrome = _find_system_chrome()
    if chrome:
        lower = chrome.lower()
        if "edge" in lower or "msedge" in lower:
            return "msedge"
        return "chrome"
    return "chrome"


def _get_quotex_host() -> str | None:
    """Get the detected Quotex host from session."""
    return None


def _open_chart_for_prices(self) -> None:
    """Open chart page to trigger price streaming - must stay on chart for live prices."""
    page = getattr(self, '_page', None)
    if not page:
        self._log("warn", "No page available to open chart")
        return
    
    # Navigate to chart for EURUSD to trigger price stream
    # Quotex only sends live prices to ACTIVE chart pages
    async def _do_navigate():
        try:
            # Use trade URL with asset parameter
            chart_url = f"{self._base_url}/en/demo-trade?asset=EURUSD_otc"
            self._log("info", f"Opening chart: {chart_url}")
            await page.goto(chart_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)
            # Stay on page - don't navigate away as that's when price streaming stops
        except Exception as e:
            self._log("warn", f"Chart navigation failed: {e}")
    
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_do_navigate())
        else:
            loop.run_until_complete(_do_navigate())
    except Exception as e:
        self._log("warn", f"Could not run chart navigation: {e}")


class PlaywrightQuotexBridge:
    """
    Playwright-based connection bridge for Quotex.

    Uses the system-installed Chrome/Edge (channel="chrome" or "msedge") to:
    1. Login to Quotex and extract session token
    2. Intercept WebSocket frames for live market data
    3. Provide candle/tick data to the signal engine

    No "playwright install" is required because we use the user's existing browser.
    """

    BASE_URLS = [
        "https://market-qx.trade",
        "https://qxbroker.com",
        "https://quotex.com",
        "https://quotex.io",
    ]

    def __init__(self, log_callback: Callable | None = None) -> None:
        self._log_cb = log_callback
        self._session: PlaywrightSession | None = None
        self._playwright: Any = None
        self._ws_frames: list[dict] = []
        self._tick_history: dict[str, list[dict]] = {}
        self._running = False
        self._base_url: str = "https://qxbroker.com"
        self._page: Any = None  # Store page for navigation

    def _log(self, level: str, msg: str) -> None:
        if self._log_cb:
            self._log_cb(level, msg)
        else:
            getattr(logger, level.lower(), logger.info)(msg)

    def _setup_bundled_browsers(self) -> None:
        """Configure environment to use browsers bundled in PyInstaller EXE."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled_path = os.path.join(sys._MEIPASS, "playwright", "ms-playwright")
            if os.path.isdir(bundled_path):
                self._log("info", f"Setting Playwright browser path to bundled: {bundled_path}")
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_path
                # Ensure we don't try to use system browsers if we explicitly bundled them
                self._use_bundled = True
            else:
                self._log("warn", "Frozen but bundled playwright browsers not found at _MEIPASS path.")
                self._use_bundled = False
        else:
            self._use_bundled = False

    async def connect(
        self,
        email: str,
        password: str,
        email_pin: str = "",
        headless: bool = True,
        timeout: float = 120.0,
        pin_callback: Callable[[], str] | None = None,
    ) -> PlaywrightSession:
        """Launch Playwright, login to Quotex, extract session token."""
        self._setup_bundled_browsers()
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright Python package is not installed. Run: pip install playwright"
            )

        # Verify a system browser is available (unless we are using bundled)
        system_browser = None if self._use_bundled else _find_system_chrome()
        channel = _detect_channel() if not self._use_bundled else None
        
        if self._use_bundled:
            self._log("info", "Using bundled Playwright browser from EXE.")
        elif system_browser:
            self._log("info", f"Using system browser: {system_browser} (channel={channel})")
        else:
            self._log("warn", "No system Chrome/Edge found. Trying Playwright's own browser...")

        self._log("info", "Launching Playwright for Quotex login...")
        self._playwright = await async_playwright().start()

        # Isolate Playwright from user's real Chrome using a temp profile
        import tempfile
        self._temp_user_dir = tempfile.mkdtemp(prefix="quotex_bot_profile_")
        
        # Browser args common to both headless and visible modes
        common_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
        ]
        
        # When headless: hide browser off-screen (Quotex may block true headless)
        # When visible: show browser normally so user can see login / PIN prompts
        if headless:
            common_args.extend([
                "--window-position=-32000,-32000",
                "--start-minimized",
            ])
        
        launch_args = {
            "headless": False,  # never true headless (Quotex blocks it)
            "args": common_args,
            "viewport": {"width": 1366, "height": 768},
            "locale": "en-US",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }

        # Use system browser channel or bundled path
        if self._use_bundled:
            pass
        elif system_browser:
            self._log("info", f"Using system browser via executable_path: {system_browser}")
            launch_args["executable_path"] = system_browser
            launch_args.pop("channel", None)
        else:
            pass

        try:
            context = await self._playwright.chromium.launch_persistent_context(
                self._temp_user_dir, **launch_args
            )
            browser = context.browser
        except Exception as launch_err:
            err_msg = str(launch_err)
            if "Executable doesn't exist" in err_msg or "browserType.launch" in err_msg.lower():
                chrome_path = _find_system_chrome()
                if chrome_path:
                    self._log("warn", f"Channel launch failed, trying direct path: {chrome_path}")
                    launch_args.pop("channel", None)
                    launch_args["executable_path"] = chrome_path
                    try:
                        context = await self._playwright.chromium.launch_persistent_context(
                            self._temp_user_dir, **launch_args
                        )
                        browser = context.browser
                    except Exception as retry_err:
                        raise RuntimeError(
                            f"Could not launch browser.\n"
                            f"System browser found at: {chrome_path}\n"
                            f"Error: {retry_err}\n"
                            f"Please ensure Chrome or Edge is installed and up to date."
                        ) from retry_err
                else:
                    raise RuntimeError(
                        "No browser available for Playwright.\n"
                        "Please install Google Chrome or Microsoft Edge.\n"
                        "Download Chrome: https://www.google.com/chrome/\n"
                        f"Original error: {err_msg}"
                    ) from launch_err
            else:
                raise

        # Stealth: remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            if (!window.chrome) window.chrome = { runtime: {} };
        """)

        page = await context.new_page()

        # Intercept WebSocket frames
        page.on("websocket", lambda ws: self._attach_ws_listener(ws))

        # Try each base URL
        login_url = None
        for base in self.BASE_URLS:
            test_url = f"{base}/en/sign-in"
            self._log("info", f"Trying {test_url}...")
            try:
                await page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
                # Wait for Cloudflare to pass
                await page.wait_for_timeout(5000)
                login_url = test_url
                self._base_url = base
                break
            except Exception:
                continue
        
        if not login_url:
            login_url = f"{self.BASE_URLS[0]}/en/sign-in"
            self._base_url = self.BASE_URLS[0]
            self._log("warn", f"Falling back to {login_url}")
            try:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
            except Exception as nav_err:
                self._log("warn", f"Navigation timeout/error: {nav_err}. Continuing anyway...")

        # Wait longer for login form and any overlays to clear
        await page.wait_for_timeout(2000)

        current_url = page.url
        self._log("info", f"Page loaded: {current_url}")

        if "/trade" not in current_url:
            # Fill login form
            await self._fill_login_form(page, email, password)
            await page.wait_for_timeout(500)

            # Submit
            submitted = await self._submit_form(page)
            self._log("info", f"Form submitted: {submitted}")

            # Wait for navigation to trade page or PIN prompt
            token = await self._wait_for_auth(
                page, email_pin=email_pin, timeout=timeout, pin_callback=pin_callback
            )
        else:
            self._log("info", "Already on trade page (session cached).")
            token = await self._extract_token(page)

        if not token:
            raise RuntimeError(
                "Quotex authentication timed out. Could not extract session token."
            )

        # Page is already on trading page after _wait_for_auth returned the token
        # Don't force another navigation - it causes net::ERR_ABORTED
        # Just wait for the page to fully settle
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # Page might already be stable

        user_agent = await page.evaluate("navigator.userAgent")
        cookies_list = await context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_list)
        url_parts = urlparse(page.url)

        self._session = PlaywrightSession(
            ssid=token,
            cookies=cookie_str,
            user_agent=user_agent,
            token=token,
            page=page,
            browser=browser,
            context=context,
            base_url=f"{url_parts.scheme}://{url_parts.netloc}" if 'url_parts' in locals() else "https://qxbroker.com"
        )

        # Store page for later chart navigation
        self._page = page
        
        self._running = True
        self._log("info", f"Playwright session established. Token length: {len(token)}")
        return self._session

    async def _fill_login_form(self, page: Any, email: str, password: str) -> None:
        """Fill email and password using multiple selector strategies."""
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id="email"]',
            'input[autocomplete="email"]',
            'input[placeholder*="mail" i]',
            'input[placeholder*="Email" i]',
            '#email',
            '[data-testid="email"]',
            'input.form-input',
            'input.input-field',
        ]
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id="password"]',
            'input[autocomplete="current-password"]',
            'input[autocomplete="new-password"]',
            '#password',
            '[data-testid="password"]',
        ]

        # Try each selector for email
        email_filled = False
        for sel in email_selectors:
            try:
                locator = page.locator(f"{sel}:visible").first
                if await locator.count() > 0:
                    await locator.click()
                    await locator.fill(email)
                    email_filled = True
                    self._log("info", f"Email filled via: {sel}")
                    break
            except Exception:
                continue

        if not email_filled:
            # Fallback: JS injection with React-compatible setter
            await page.evaluate(
                """(email) => {
                    for (const inp of document.querySelectorAll('input')) {
                        const t = (inp.type || '').toLowerCase();
                        const n = (inp.name || '').toLowerCase();
                        if (t === 'email' || n === 'email' || n.includes('mail')) {
                            const setter = Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype, 'value'
                            )?.set;
                            if (setter) setter.call(inp, email); else inp.value = email;
                            inp.dispatchEvent(new Event('input', {bubbles:true}));
                            inp.dispatchEvent(new Event('change', {bubbles:true}));
                            break;
                        }
                    }
                }""",
                email,
            )
            self._log("info", "Email filled via JS fallback.")

        # Try each selector for password
        pw_filled = False
        for sel in password_selectors:
            try:
                locator = page.locator(f"{sel}:visible").first
                if await locator.count() > 0:
                    await locator.click()
                    await locator.fill(password)
                    pw_filled = True
                    self._log("info", f"Password filled via: {sel}")
                    break
            except Exception:
                continue

        if not pw_filled:
            await page.evaluate(
                """(pw) => {
                    for (const inp of document.querySelectorAll('input')) {
                        if ((inp.type || '').toLowerCase() === 'password') {
                            const setter = Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype, 'value'
                            )?.set;
                            if (setter) setter.call(inp, pw); else inp.value = pw;
                            inp.dispatchEvent(new Event('input', {bubbles:true}));
                            inp.dispatchEvent(new Event('change', {bubbles:true}));
                            break;
                        }
                    }
                }""",
                password,
            )
            self._log("info", "Password filled via JS fallback.")

    async def _submit_form(self, page: Any) -> bool:
        """Submit the login form."""
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            "button:has-text('Sign In')",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
            "button:has-text('Войти')",
            "button.btn--primary",
            "button.btn--success",
        ]
        for sel in submit_selectors:
            try:
                locator = page.locator(f"{sel}:visible").first
                if await locator.count() > 0:
                    await locator.click()
                    return True
            except Exception:
                continue

        # JS fallback
        # JS fallback (Aggressive Walker)
        try:
            result = await page.evaluate("""() => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                };
                
                const pwField = Array.from(document.querySelectorAll('input[type="password"], input[name="password"]')).find(visible);
                
                const selectors = [
                    'button[type="submit"]', 'input[type="submit"]', 'button.btn-primary', 'button.btn-success',
                    'button.button--primary', '.btn--green', '.btn--primary', '.button--primary',
                    '.form__submit', '.auth-form__submit', 'button.btn'
                ];
                
                let btns = [];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        if (visible(el)) btns.push(el);
                    });
                });
                
                const findByText = (root, pattern) => {
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
                    let node;
                    while (node = walker.nextNode()) {
                        if (node.textContent.toLowerCase().includes(pattern)) {
                            let parent = node.parentElement;
                            while (parent && parent !== root) {
                                const tag = parent.tagName.toLowerCase();
                                if (tag === 'button' || tag === 'a' || parent.onclick || parent.getAttribute('role') === 'button') return parent;
                                parent = parent.parentElement;
                            }
                        }
                    }
                    return null;
                };

                ['sign in', 'log in', 'enter', 'войти', 'login'].forEach(txt => {
                    const found = findByText(document.body, txt);
                    if (found && visible(found) && !btns.includes(found)) btns.push(found);
                });

                let button = btns[0];
                if (!button && pwField) {
                    const form = pwField.closest('form');
                    if (form) button = form.querySelector('button, input[type="submit"]');
                }

                if (button) {
                    button.disabled = false;
                    button.scrollIntoView({block: "center"});
                    button.focus();
                    const eventTypes = ['mousedown', 'mouseup', 'click'];
                    eventTypes.forEach(type => {
                        try {
                            button.dispatchEvent(new MouseEvent(type, {
                                bubbles: true, cancelable: true, view: window, buttons: 1
                            }));
                        } catch(e) {}
                    });
                    if (typeof button.click === 'function') button.click();
                    return true;
                }

                if (pwField) {
                    pwField.focus();
                    ['keydown', 'keypress', 'keyup'].forEach(type => {
                        pwField.dispatchEvent(new KeyboardEvent(type, {
                            key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true
                        }));
                    });
                    const form = pwField.closest('form');
                    if (form) {
                        try { form.submit(); return true; } catch(e) {}
                    }
                }
                return false;
            }""")
            return bool(result)
        except Exception as e:
            self._log("warn", f"Form submission JS fallback failed: {e}")
            return False

    async def _wait_for_auth(
        self, page: Any, email_pin: str = "", timeout: float = 120.0, pin_callback: Callable[[], str] | None = None
    ) -> str:
        """Wait for Quotex to authenticate, handling PIN if needed."""
        deadline = time.time() + timeout
        pin_sent = False
        check = 0
        authenticated_from_ws = False

        while time.time() < deadline:
            check += 1
            current_url = page.url

            # Check for authenticated session via WebSocket data (receiving quotes means we're logged in)
            if authenticated_from_ws:
                token = await self._extract_token(page)
                if token:
                    self._log("info", f"Token extracted (authenticated via WebSocket data)!")
                    return token
            
            # Also check URL for token
            if "qx" in current_url or "quotex" in current_url or "trade" in current_url:
                token = await self._extract_token(page)
                if token:
                    self._log("info", f"Token extracted from page!")
                    return token
            
            # Check for WebSocket that received data - this means we're authenticated
            if self._tick_history and any(len(v) > 0 for v in self._tick_history.values()):
                authenticated_from_ws = True
                self._log("info", "WebSocket data received - authentication detected!")

            # Check for PIN input
            if not pin_sent:
                try:
                    pin_locator = page.locator(
                        'input[name="code"]:visible, '
                        'input[inputmode="numeric"]:visible, '
                        'input[placeholder*="code" i]:visible'
                    ).first
                    if await pin_locator.count() > 0:
                        code = email_pin
                        if not code and pin_callback:
                            self._log("info", "Requesting 2FA PIN from user...")
                            # Call pin_callback directly (it's a sync callback for UI dialog)
                            if asyncio.iscoroutinefunction(pin_callback):
                                code = await pin_callback()
                            else:
                                code = pin_callback()
                        
                        if code:
                            await pin_locator.fill(code)
                            await self._submit_form(page)
                            pin_sent = True
                            self._log("info", "PIN code submitted.")
                except Exception:
                    pass

            if check % 10 == 0:
                self._log("info", f"Waiting for auth... check #{check}, URL: {current_url[:60]}")

            await asyncio.sleep(1.0)

        # Last try - if we have WebSocket data, we're authenticated even without token
        if self._tick_history and any(len(v) > 0 for v in self._tick_history.values()):
            self._log("warn", "Timeout but WebSocket data received - extracting cookies from browser...")
            cookies_list = await page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_list)
            return cookie_str
        
        return ""

    async def _extract_token(self, page: Any) -> str:
        """Extract session token (SSID) using multiple methods. Playwright cookies + localStorage."""
        try:
            # === PRIMARY: Playwright context cookies for SSID specifically ===
            try:
                context = page.context
                all_cookies = await context.cookies()
                for cookie in all_cookies:
                    name = cookie.get("name", "")
                    # Only exact SSID cookie names - never broad patterns (laravel_session is NOT SSID)
                    if name.lower() in ("ssid", "sid"):
                        val = cookie.get("value", "")
                        if val and len(val) >= 20 and len(val) <= 60:
                            self._log("info", f"SSID extracted from Playwright cookie: {name}")
                            return str(val)
                self._log("debug", f"Cookies found: {[c.get('name','') for c in all_cookies]}")
            except Exception as cookie_err:
                self._log("debug", f"Playwright cookie extraction failed: {cookie_err}")

            # === METHOD 2: localStorage (quotexpy extracts SSID from here) ===
            try:
                ssid = await page.evaluate("() => localStorage.getItem('SSID') || localStorage.getItem('ssid')")
                if ssid and len(ssid) >= 20 and len(ssid) <= 60:
                    self._log("info", "SSID extracted from localStorage")
                    return str(ssid)
            except Exception:
                pass

            # === FALLBACK: JavaScript evaluation ===
            token = await page.evaluate("""() => {
                // Method 1: window.settings
                if (window.settings && window.settings.token) return window.settings.token;
                if (window.settings && window.settings.session) return window.settings.session;
                
                // Method 2: window.ql or window.quotex
                if (window.ql && window.ql.token) return window.ql.token;
                if (window.ql && window.ql.sessionToken) return window.ql.sessionToken;
                if (window.quotex && window.quotex.token) return window.quotex.token;
                
                // Method 3: localStorage - try multiple keys
                const lsKeys = ['token', 'authToken', 'accessToken', 'sessionToken', 'jwtToken', 'sid', 'ssid', 'SSID'];
                for (const key of lsKeys) {
                    const val = localStorage.getItem(key);
                    if (val && val.length > 10) return val;
                }
                
                // Method 4: sessionStorage
                for (const key of lsKeys) {
                    const val = sessionStorage.getItem(key);
                    if (val && val.length > 10) return val;
                }
                
                // Method 5: Cookies - look for session/SSID cookies
                const cookies = document.cookie.split(';');
                for (const c of cookies) {
                    const [name, val] = c.split('=').map(s => s.trim());
                    if (name === 'SSID' || name === 'ssid' || name === 'sid' || name === 'token' || name.endsWith('Token')) {
                        if (val && val.length > 10) return val;
                    }
                }

                // Method 6: Parse window.__INITIAL_DATA__ or similar
                try {
                    if (window.__INITIAL_DATA__) return window.__INITIAL_DATA__.token || window.__INITIAL_DATA__.session;
                    if (window.__APP_DATA__) return window.__APP_DATA__.token || window.__APP_DATA__.session;
                    if (window.__PRELOADED_STATE__) return window.__PRELOADED_STATE__.auth?.token;
                } catch(e) {}

                return null;
            }""")
            if token:
                return str(token)
            
            # Wait a moment for page to fully load after PIN, then retry
            await page.wait_for_timeout(2000)
            token = await page.evaluate("""() => {
                // Retry after waiting
                if (window.settings && window.settings.token) return window.settings.token;
                if (window.ql && window.ql.token) return window.ql.token;
                
                // Check cookies again
                const cookies = document.cookie.split(';');
                for (const c of cookies) {
                    const [name, val] = c.split('=').map(s => s.trim());
                    if (name === 'SSID' || name === 'ssid' || name === 'sid') return val;
                }
                
                // Check localStorage for SSID
                const ssid = localStorage.getItem('SSID') || localStorage.getItem('ssid');
                if (ssid) return ssid;
                
                return null;
            }""")
            if token:
                return str(token)
             

            # Last resort: Try API endpoint directly
            self._log("info", "Token not found in page, trying API endpoint...")
            return await self._extract_token_from_api(page)
        except Exception as e:
            # Handle "Execution context was destroyed" - page is navigating
            err_msg = str(e).lower()
            if "execution context was destroyed" in err_msg or "navigation" in err_msg:
                self._log("warn", "Token extraction: page navigating, will retry...")
                return ""
            self._log("warn", f"Token extraction error: {e}")
            return ""

    async def _extract_token_from_api(self, page: Any) -> str:
        """Extract token from Quotex API directly using session cookies."""
        try:
            # Get cookies from the page context
            context = page.context
            cookies = await context.cookies()
            
            # Build cookie header
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # Try the main Quotex API endpoint
            api_endpoints = [
                "https://qxbroker.com/api/v2/user/",
                "https://quotex.com/api/v2/user/",
                "https://quotex-api.com/api/v2/user/",
            ]
            
            import aiohttp
            for endpoint in api_endpoints:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            endpoint,
                            headers={
                                "Cookie": cookie_str,
                                "User-Agent": await page.evaluate("() => navigator.userAgent"),
                                "Accept": "application/json",
                            },
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                # Check for token in API response
                                if isinstance(data, dict):
                                    # Try common token locations in API response
                                    for key in ["token", "accessToken", "authToken", "sessionToken"]:
                                        if key in data:
                                            token = str(data[key])
                                            if token and len(token) > 10:
                                                self._log("info", f"Token found from API endpoint: {endpoint}")
                                                return token
                                    # Check nested user object
                                    if "user" in data and isinstance(data["user"], dict):
                                        for key in ["token", "accessToken", "authToken"]:
                                            if key in data["user"]:
                                                token = str(data["user"][key])
                                                if token and len(token) > 10:
                                                    self._log("info", f"Token found from API user object")
                                                    return token
                except Exception:
                    continue
            
            return ""
        except Exception as e:
            self._log("warn", f"API token extraction error: {e}")
            return ""

    def _attach_ws_listener(self, ws: Any) -> None:
        """Attach listeners to intercepted WebSocket connections."""
        url = ws.url
        if self._session and not self._session.base_url:
             # This is a bit late to set base_url, but we can set ws_url
             pass
        if self._session:
            self._session.base_url = self._session.base_url or urlparse(url).netloc
        
        self._log("info", f"WebSocket detected: {url[:80]}")
        if self._session and not getattr(self._session, "captured_ws_url", None):
            self._session.captured_ws_url = url

        # Store the WS connection for later use - we'll subscribe after auth confirmation
        self._ws = ws
        # Use all 25 PREFERRED pairs with _otc suffix (same as live.py)
        self._pending_subscriptions = [
            "USDBDT_otc", "NZDCAD_otc", "USDEGP_otc", "NZDUSD_otc",
            "USDMXN_otc", "AUDCHF_otc", "USDCOP_otc", "USDINR_otc",
            "USDPKR_otc", "EURNZD_otc", "USDDZD_otc", "USDZAR_otc",
            "USDARS_otc", "CADCHF_otc", "AUDNZD_otc", "USDIDR_otc",
            "EURUSD_otc", "GBPUSD_otc", "AUDUSD_otc", "USDJPY_otc",
            "EURJPY_otc", "GBPJPY_otc", "USDCAD_otc", "USDCHF_otc",
            "EURGBP_otc",
        ]

        # Inject JS to expose the WebSocket for sending via page.evaluate
        page = getattr(self, '_page', None)
        if not page and self._session and self._session.page:
            page = self._session.page
        if page:
            try:
                # Store ws endpoint and create a way to send messages from JS
                asyncio.get_event_loop().create_task(
                    page.evaluate(f"""(wsUrl) => {{
                        // Find the Socket.IO connection that matches our URL
                        window._quotex_ws_found = false;
                        window._quotex_send_queue = [];
                        
                        // Hook into existing connections or intercept new ones
                        if (window.io && window.io.connect) {{
                            window._quotex_ws_found = true;
                        }}
                        
                        // Alternative: store URL for reference
                        window._quotex_ws_url = wsUrl;
                        return true;
                    }}""", url)
                )
            except Exception:
                pass

        def on_frame(payload: str) -> None:
            try:
                self._process_ws_frame(payload)
            except Exception:
                pass

        ws.on("framereceived", lambda data: on_frame(data))

        # IMMEDIATELY subscribe after WS opens - don't wait for instruments/list
        # This ensures we get prices even if auth event never fires
        def do_immediate_sub():
            try:
                self._log("info", "Immediate subscription to all OHLC pairs...")
                self._do_subscribe()
            except Exception as e:
                self._log("warn", f"Immediate sub failed: {e}")
        
        # Subscribe after small delay to ensure WS is ready
        import threading
        threading.Timer(2.0, do_immediate_sub).start()

    def _process_ws_frame(self, payload: str) -> None:
        """Process incoming WebSocket frame for market data."""
        if not isinstance(payload, str) or len(payload) < 3:
            return

        # Log ALL frames for debugging
        if len(payload) < 200:
            self._log("debug", f"WS frame: {payload[:150]}")
        else:
            self._log("debug", f"WS frame (truncated): {payload[:100]}...")

        # Handle Engine.IO pings: 451-["event", data]
        if payload.startswith("451-"):
            try:
                content = payload[3:]
                if content.startswith("["):
                    data = json.loads(content)
                    if isinstance(data, list) and len(data) >= 2:
                        event_name = data[0]
                        event_data = data[1]
                        
                        # Handle quotes/stream event - subscription acknowledgments come as {"_placeholder":true}
                        # But actual prices might come as array: ["asset_name", timestamp, price]
                        if event_name == "quotes/stream":
                            # If it's a placeholder, just acknowledge. If it's data, parse it.
                            if isinstance(event_data, dict) and event_data.get("_placeholder"):
                                self._log("debug", f"Quote stream subscribed: {event_name}")
                            elif isinstance(event_data, list):
                                self._handle_market_event(event_name, event_data)
                            elif isinstance(event_data, dict) and "price" in event_data:
                                # Real price data: {"symbol":..., "price":...} - call handler with dict
                                self._handle_market_event(event_name, event_data)
                        elif event_name == "depth/change":
                            if isinstance(event_data, dict) and event_data.get("_placeholder"):
                                self._log("debug", f"Depth stream subscribed: {event_name}")
                            elif isinstance(event_data, list):
                                self._handle_market_event(event_name, event_data)
                        elif event_name == "instruments/list":
                            # This confirms we're logged in
                            if not getattr(self, '_authenticated', False):
                                self._authenticated = True
                                self._log("info", "Authenticated! Receiving instruments list.")
                                # Now send subscription requests after auth confirmed
                                self._do_subscribe()
            except (json.JSONDecodeError, IndexError):
                pass
        
        # Handle Socket.IO messages: 42["event", data]
        if payload.startswith("42["):
            try:
                data = json.loads(payload[2:])
                if isinstance(data, list) and len(data) >= 2:
                    event_name = data[0]
                    event_data = data[1]

                    # Log event name
                    self._log("debug", f"WS event: {event_name}")
                    
                    # ALWAYS subscribe after receiving instruments list (regardless of auth flag)
                    if event_name == "instruments/list":
                        self._authenticated = True
                        self._log("info", "Received instruments list - proceeding with subscriptions!")
                        self._do_subscribe()
                    
                    # Also check for auth events 
                    if event_name in ("s_authorization", "authorization") and not getattr(self, '_authenticated', False):
                        self._authenticated = True
                        self._log("info", f"Authenticated via {event_name}!")
                        self._do_subscribe()
                    
                    # Handle market data events - route ALL events with list data
                    if event_name is None or event_name in ("tick", "ticks", "candles", "quotes", "quote", "price", "live_price", "asset_quote", "follow_candle", "chart_notification", "instruments/update", "depth/change", "quotes/stream"):
                        if event_data is not None:
                            self._handle_market_event(event_name, event_data)
                    # Also handle case where the whole data IS the tick data (no separate event/body)
                    if isinstance(event_data, list):
                        pass  # already handled above
            except (json.JSONDecodeError, IndexError):
                pass
        
        # Handle other Engine.IO frame types
        elif payload == "2":  # heartbeat pong (just a "2" without data)
            # Send pong "3" via JS injection since Playwright WS is read-only
            page = getattr(self, '_page', None)
            if not page and self._session and self._session.page:
                page = self._session.page
            if page:
                try:
                    asyncio.get_event_loop().create_task(
                        page.evaluate("""() => {
                            try {
                                let ws = null;
                                if (window.io && window.io.engine && window.io.engine.transport && window.io.engine.transport.ws) {
                                    ws = window.io.engine.transport.ws;
                                }
                                if (!ws) {
                                    for (const key of Object.keys(window)) {
                                        try {
                                            const obj = window[key];
                                            if (obj && obj instanceof WebSocket && obj.readyState === WebSocket.OPEN) {
                                                ws = obj; break;
                                            }
                                        } catch(e) {}
                                    }
                                }
                                if (ws) ws.send('3');
                                return true;
                            } catch(e) { return false; }
                        }""")
                    )
                except Exception:
                    pass

    def _do_subscribe(self) -> None:
        """Send subscription requests using JavaScript injection (Playwright WS is read-only)."""
        try:
            # Try self._page first, then fall back to session.page
            page = getattr(self, '_page', None)
            if not page and self._session and self._session.page:
                page = self._session.page
            
            if not page:
                self._log("warn", "No page available for WebSocket subscriptions")
                return
            
            if not hasattr(self, '_pending_subscriptions') or not self._pending_subscriptions:
                return
            
            subs = self._pending_subscriptions.copy()
            
            async def _send_via_js():
                try:
                    # Build subscription messages as Socket.IO packets
                    messages = []
                    for pair in subs:
                        pair_otc = pair if "_otc" in pair.lower() else f"{pair}_otc"
                        messages.append(f'42["instruments/update",{{"asset":"{pair_otc}","period":0}}]')
                    for pair in subs:
                        pair_otc = pair if "_otc" in pair.lower() else f"{pair}_otc"
                        messages.append(f'42["depth/follow","{pair_otc}"]')
                    messages.append('42["tick"]')
                    
                    # Use page.evaluate to find and send via the actual browser WebSocket
                    result = await page.evaluate("""(msgs) => {
                        try {
                            // Find the Socket.IO transport or WebSocket
                            let ws = null;
                            
                            // Method 1: Look for io.engine.transport.ws
                            if (window.io && window.io.engine && window.io.engine.transport && window.io.engine.transport.ws) {
                                ws = window.io.engine.transport.ws;
                            }
                            
                            // Method 2: Search all global properties for WebSocket
                            if (!ws) {
                                for (const key of Object.keys(window)) {
                                    try {
                                        const obj = window[key];
                                        if (obj && obj instanceof WebSocket && obj.readyState === WebSocket.OPEN) {
                                            ws = obj;
                                            break;
                                        }
                                    } catch(e) {}
                                }
                            }
                            
                            // Method 3: Hook io.connect to catch future connections
                            if (!ws && window.io) {
                                const origConnect = window.io.connect;
                                if (origConnect) {
                                    window.io.connect = function(...args) {
                                        const socket = origConnect.apply(this, args);
                                        socket.on('connect', function() {
                                            if (socket.io && socket.io.engine && socket.io.engine.transport) {
                                                const transport = socket.io.engine.transport;
                                                if (transport.ws) {
                                                    window._quotex_ws_hook = transport.ws;
                                                }
                                            }
                                        });
                                        return socket;
                                    };
                                }
                            }
                            
                            if (ws) {
                                let sent = 0;
                                for (const msg of msgs) {
                                    try {
                                        ws.send(msg);
                                        sent++;
                                    } catch(e) {}
                                }
                                return {success: true, sent: sent};
                            }
                            
                            // If we can't find WS, try using Socket.IO emit
                            if (window.io && window.io.sockets) {
                                const sockets = window.io.sockets;
                                for (const socketId in sockets) {
                                    const socket = sockets[socketId];
                                    if (socket && socket.connected) {
                                        for (const pair of msgs) {
                                            try {
                                                if (pair.includes('instruments/update')) {
                                                    const match = pair.match(/"asset":"([^"]+)"/);
                                                    if (match) socket.emit('instruments/update', {asset: match[1], period: 0});
                                                } else if (pair.includes('depth/follow')) {
                                                    const match = pair.match(/"([^"]+_otc)"/);
                                                    if (match) socket.emit('depth/follow', match[1]);
                                                } else if (pair.includes('tick')) {
                                                    socket.emit('tick');
                                                }
                                            } catch(e) {}
                                        }
                                        return {success: true, sent: msgs.length, method: 'emit'};
                                    }
                                }
                            }
                            
                            return {success: false, error: 'No WebSocket found'};
                        } catch(e) {
                            return {success: false, error: e.message};
                        }
                    }""", messages)
                    
                    if result and result.get('success'):
                        self._log("info", f"Subscribed to {len(subs)} pairs ({result.get('method', 'ws.send')}, sent={result.get('sent', 0)})")
                    else:
                        err = result.get('error', 'unknown') if result else 'no result'
                        self._log("warn", f"Subscription via JS failed: {err}")
                except Exception as e:
                    self._log("warn", f"JS subscription error: {e}")
            
            # Schedule the async JS injection
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_send_via_js())
            else:
                loop.run_until_complete(_send_via_js())
            
            self._pending_subscriptions = []
        except Exception as e:
            self._log("warn", f"_do_subscribe error: {e}")

    def _handle_market_event(self, event_name: str, data: Any) -> None:
        """Handle parsed market data events. Supports both flat and nested formats."""
        if data is None:
            return
        
        # Skip placeholder acknowledgments
        if isinstance(data, dict) and data.get("_placeholder"):
            return
        
        # Handle list format: [[symbol, timestamp, price], ...] or [symbol, timestamp, price, ...]
        if isinstance(data, list) and len(data) > 0:
            tick_items = []
            if isinstance(data[0], list):
                # Nested format: [[sym,ts,price], [sym,ts,price], ...]
                tick_items = [item for item in data if isinstance(item, list) and len(item) >= 3]
            elif len(data) >= 3 and not isinstance(data[0], (list, dict)):
                # Flat format: [sym, ts, price, ...]
                tick_items = [data]
            
            for item in tick_items:
                try:
                    symbol = str(item[0]).upper()
                    if "_OTC" not in symbol:
                        symbol = symbol + "_OTC"
                    
                    # Extract price - try different positions (usually index 2)
                    price = 0.0
                    for idx in range(1, min(len(item), 5)):
                        val = item[idx]
                        if isinstance(val, (int, float)) and val != 0 and not isinstance(val, bool):
                            if 0.00001 < val < 1000000:
                                price = float(val)
                                break
                    
                    if symbol and price > 0:
                        self._tick_history.setdefault(symbol, []).append({
                            "time": int(item[1]) if len(item) > 1 and isinstance(item[1], (int, float)) else int(time.time()),
                            "price": price,
                        })
                        if len(self._tick_history[symbol]) > 500:
                            self._tick_history[symbol] = self._tick_history[symbol][-500:]
                        # Log every 10th tick to avoid spam
                        if len(self._tick_history[symbol]) % 10 == 0:
                            self._log("info", f"TICK {symbol}: {price} (history={len(self._tick_history[symbol])})")
                except Exception:
                    pass
        
        # Handle dict format: {"symbol": ..., "price": ...} (fallback)
        elif isinstance(data, dict):
            symbol = str(
                data.get("symbol") or 
                data.get("asset") or 
                data.get("name") or 
                data.get("pair") or
                ""
            )
            if symbol:
                symbol = symbol.upper()
                if "_OTC" not in symbol:
                    symbol = symbol + "_OTC"
            
            price = float(data.get("price") or data.get("close") or data.get("last_price") or data.get("rate") or 0)
            
            if symbol and price > 0:
                self._log("info", f"PRICE {symbol} = {price}")
                self._tick_history.setdefault(symbol, []).append({
                    "time": int(time.time()),
                    "price": price,
                })
                if len(self._tick_history[symbol]) > 500:
                    self._tick_history[symbol] = self._tick_history[symbol][-500:]
            elif data and not data.get("_placeholder"):
                # Log unknown dict format for debugging
                keys = list(data.keys())
                self._log("debug", f"Unknown price dict format: keys={keys[:5]}, event={event_name}")

    def get_tick_history(self, symbol: str) -> list[dict]:
        """Get stored tick history for a symbol."""
        return list(self._tick_history.get(symbol, []))

    async def get_balance(self) -> float:
        """Extract account balance from the page."""
        if not self._session or not self._session.page:
            return 0.0
        page = self._session.page
        try:
            balance = await page.evaluate("""() => {
                // Try window.settings first
                if (window.settings && window.settings.balance) {
                    return parseFloat(window.settings.balance);
                }
                // Try localStorage
                const lsBalance = localStorage.getItem('balance');
                if (lsBalance) return parseFloat(lsBalance);
                // Try Quotex internal state
                const ql = window.ql || window.quotex || {};
                if (ql.balance) return parseFloat(ql.balance);
                if (ql.account && ql.account.balance) return parseFloat(ql.account.balance);
                // Try finding balance in DOM
                const balanceEl = document.querySelector('.account-balance, .balance-value, [class*="balance"]');
                if (balanceEl) {
                    const text = balanceEl.textContent || balanceEl.innerText;
                    const num = parseFloat(text.replace(/[^0-9.-]/g, ''));
                    if (!isNaN(num)) return num;
                }
                return 0;
            }""")
            if balance and balance > 0:
                self._log("info", f"Balance extracted: {balance}")
                return float(balance)
        except Exception as e:
            self._log("debug", f"Balance extraction error: {e}")
        return 0.0

    async def get_all_prices(self) -> dict:
        """Get ALL live prices - combines WebSocket ticks + DOM scraping."""
        prices = {}
        
        # 1. Get prices from WebSocket tick history
        tick_history = self.get_tick_history("")
        for symbol, ticks in tick_history.items():
            if ticks:
                latest = ticks[-1]
                if latest and latest.get("price", 0) > 0:
                    prices[symbol] = latest["price"]
        
        # 2. Also try DOM scraping for additional prices
        dom_prices = await self.get_current_prices()
        prices.update(dom_prices)
        
        if prices:
            self._log("debug", f"Total prices: {len(prices)}")
        return prices

    async def get_current_prices(self) -> dict:
        """Extract LIVE prices directly from the page DOM - this is the real data source!"""
        if not self._session or not self._session.page:
            return {}
        page = self._session.page
        prices = {}
        try:
            # Scrape prices directly from the trading page asset list
            price_data = await page.evaluate("""() => {
                const results = {};
                
                // Method 1: Try window.quotex or window.ql global store (PRIMARY)
                try {
                    const ql = window.ql || window.quotex || window._quotex || {};
                    // Try currencies object
                    if (ql.currencies) {
                        Object.values(ql.currencies).forEach(c => {
                            const name = c.name || c.asset || c.symbol || '';
                            const price = c.price || c.current || c.value || 0;
                            if (name && price) {
                                const sym = name.toUpperCase().replace('_OTC', '').replace('_otc', '');
                                results[sym + '_OTC'] = parseFloat(price);
                            }
                        });
                    }
                    // Try activeAsset price
                    if (ql.activeAsset && ql.activeAsset.price) {
                        const sym = ql.activeAsset.name?.toUpperCase() || 'CURRENT';
                        results[sym] = parseFloat(ql.activeAsset.price);
                    }
                    // Try assets list
                    if (ql.assets && Array.isArray(ql.assets)) {
                        ql.assets.forEach(a => {
                            if (a.name && a.price) {
                                const sym = a.name.toUpperCase().replace('_OTC', '').replace('_otc', '');
                                results[sym + '_OTC'] = parseFloat(a.price);
                            }
                        });
                    }
                } catch(e) {}
                
                // Method 2: Look for asset list in DOM - Quotex specific selectors
                const listSelectors = [
                    '.assets-list__item', 
                    '.assets-list-item',
                    '.assets-table__row',
                    '.pairs-list__item',
                    '.pair-item',
                    '[data-testid="asset-item"]',
                    '.instrument-row',
                    '.currency-item'
                ];
                
                for (const sel of listSelectors) {
                    const items = document.querySelectorAll(sel);
                    if (items.length > 0) {
                        items.forEach(item => {
                            // Find symbol - try multiple approaches
                            let symbol = '';
                            const nameEl = item.querySelector('.asset-name, .pair-name, .name, [class*="name"], .currency-name');
                            if (nameEl) {
                                symbol = (nameEl.textContent || nameEl.innerText || '').trim().split(' ')[0].toUpperCase();
                            }
                            if (!symbol) {
                                // Try data attribute
                                symbol = item.getAttribute('data-symbol') || item.dataset?.symbol || '';
                            }
                            
                            // Find price
                            let price = 0;
                            const priceEl = item.querySelector('.price-value, .price, .rate, .value, [class*="price"], .asset-price');
                            if (priceEl) {
                                const txt = (priceEl.textContent || priceEl.innerText || '').replace(/[^0-9.-]/g, '');
                                price = parseFloat(txt);
                            }
                            if (!price) {
                                // Try parsing from any number in the item
                                const txt = item.textContent || '';
                                const numMatch = txt.match(/\\d+\\.\\d+/);
                                if (numMatch) price = parseFloat(numMatch[0]);
                            }
                            
                            if (symbol && price > 0 && symbol.length < 15) {
                                if (!symbol.endsWith('_OTC')) symbol += '_OTC';
                                results[symbol] = price;
                            }
                        });
                        break; // Found items, stop looking
                    }
                }
                
                // Method 3: Try to find chart price display
                const chartSelectors = [
                    '.chart-panel__price',
                    '.current-price',
                    '#currentPrice',
                    '[data-testid="current-price"]',
                    '.price-display',
                    '.quotes-info__price'
                ];
                for (const sel of chartSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const txt = el.textContent || el.innerText || '';
                        const price = parseFloat(txt.replace(/[^0-9.-]/g, ''));
                        if (price > 0) {
                            results['CURRENT_CHART'] = price;
                        }
                        break;
                    }
                }
                
                return results;
            }""")
            if price_data:
                for sym, price in price_data.items():
                    if price and price > 0:
                        sym_clean = sym.replace('_OTC', '').replace('_otc', '')
                        if not sym_clean.endswith('_OTC'):
                            sym_clean = sym_clean + '_OTC'
                        prices[sym_clean] = price
                if prices:
                    self._log("info", f"Live prices extracted: {len(prices)} assets")
        except Exception as e:
            self._log("debug", f"Price extraction error: {e}")
        return prices

    async def get_instruments(self) -> list[dict]:
        """Scrape the asset list from the UI as a fallback."""
        if not self._session or not self._session.page:
            return []
        page = self._session.page
        try:
            assets = await page.evaluate("""() => {
                const results = [];
                // Try multiple selectors for asset items
                const selectors = [
                    '.assets-table__item',
                    '.asset-item',
                    '.assets-list__item',
                    '.pair-item',
                    '[data-testid="asset-item"]',
                    '.instrument-row',
                ];
                let items = [];
                for (const sel of selectors) {
                    items = document.querySelectorAll(sel);
                    if (items.length > 0) break;
                }
                // If no specific classes, try rows in asset tables
                if (items.length === 0) {
                    const tables = document.querySelectorAll('table, .assets-table, .pairs-table');
                    for (const table of tables) {
                        const rows = table.querySelectorAll('tr, li');
                        items = Array.from(rows).slice(1); // Skip header
                        if (items.length > 0) break;
                    }
                }
                // Fallback: scan all list items with text content
                if (items.length === 0) {
                    items = document.querySelectorAll('.col-sm-3, .asset-cell, .pair-name');
                }
                items.forEach(item => {
                    const nameEl = item.querySelector('.asset-name, .name, .pair-name, [class*="name"]') || item;
                    const name = nameEl.textContent?.trim() || '';
                    const payoutEl = item.querySelector('.asset-percent, .payout, .percent, [class*="percent"]');
                    let payout = payoutEl?.textContent?.trim() || '80%';
                    if (name && name.length > 2 && name.length < 20) {
                        results.push({
                            "symbol": name.replace(/[^A-Z0-9]/g, '').toUpperCase(),
                            "payout": payout.replace(/[^0-9]/g, '') || "80",
                            "isOpen": true
                        });
                    }
                });
                return results;
            }""")
            return assets
        except Exception as e:
            self._log("warn", f"get_instruments error: {e}")
            return []

    async def place_trade(self, symbol: str, direction: str, amount: float, duration: int) -> dict:
        """Place a trade via Playwright browser."""
        if not self._session or not self._session.page:
            return {"ok": False, "error": "No active session"}
        
        page = self._session.page
        direction = str(direction).lower().strip()
        is_call = direction in ("call", "higher", "up", "buy", "long")
        
        try:
            # First, select the asset if not already selected
            await page.evaluate(f"""(sym) => {{
                const items = document.querySelectorAll('.asset-item, .pair-item, .assets-table__item, tr');
                for (const item of items) {{
                    const nameEl = item.querySelector('.asset-name, .name, .pair-name');
                    if (nameEl && nameEl.textContent.includes(sym)) {{
                        item.click();
                        return;
                    }}
                }}
            }}""", symbol.replace("_otc", ""))
            await page.wait_for_timeout(500)
            
            # Set amount
            amount_input = page.locator('input[type="number"], input[name="amount"], .amount-input').first
            if await amount_input.count() > 0:
                await amount_input.fill(str(amount))
            await page.wait_for_timeout(300)
            
            # Set duration (expiration)
            duration_input = page.locator('input[name="duration"], input[data-testid="duration"]').first
            if await duration_input.count() > 0:
                await duration_input.fill(str(duration))
            await page.wait_for_timeout(300)
            
            # Click the trade button
            button_text = "Higher" if is_call else "Lower"
            button_selectors = [
                f'button:has-text("{button_text}")',
                f'button:has-text("{button_text.upper()}")',
                f'[data-direction="{direction}"]',
                f'.trade-button.{direction}',
            ]
            
            for sel in button_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        # Check for success indicator
                        confirm = page.locator('.trade-success, .confirm-message, [class*="success"]').first
                        if await confirm.count() > 0:
                            return {"ok": True, "trade_id": f"pw_{int(time.time())}"}
                        return {"ok": True, "trade_id": f"pw_{int(time.time())}"}
                except Exception:
                    continue
            
            return {"ok": False, "error": "Trade button not found"}
            
        except Exception as e:
            self._log("warn", f"place_trade error: {e}")
            return {"ok": False, "error": str(e)}

    async def get_balance(self) -> float:
        """Get account balance from the UI."""
        if not self._session or not self._session.page:
            return 0.0
        try:
            balance = await self._session.page.evaluate("""() => {
                const selectors = [
                    '[class*="balance"]',
                    '[data-role="balance"]',
                    '.account-balance',
                    '.wallet-balance',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = el.textContent || '';
                        const match = text.replace(/,/g, '').match(/\\d+(?:\\.\\d+)?/);
                        if (match) return parseFloat(match[0]);
                    }
                }
                return 0;
            }""")
            return float(balance or 0)
        except Exception:
            return 0.0

    async def get_candles(self, symbol: str, interval: int = 60, count: int = 10) -> list[dict]:
        """Get candle data. For now, returns intercepted data from ticks."""
        history = self.get_tick_history(symbol)
        if not history:
            return []
        # Return last N ticks as 'candles' for the engine to work
        return history[-count:]

    async def close(self) -> None:
        """Clean up Playwright resources."""
        self._running = False
        if self._session:
            try:
                if self._session.page:
                    await self._session.page.close()
            except Exception:
                pass
            try:
                if self._session.context:
                    await self._session.context.close()
            except Exception:
                pass
            try:
                if self._session.browser:
                    await self._session.browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._session = None
        self._playwright = None
        self._log("info", "Playwright bridge closed.")
