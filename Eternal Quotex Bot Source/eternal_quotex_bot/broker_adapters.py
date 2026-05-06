from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .models import Candle


@dataclass(slots=True)
class BrokerSignalSnapshot:
    broker: str
    symbol: str
    candles: list[Candle]
    screenshot_path: Path | None = None


def _playwright_chrome_launch_kwargs(*, headless: bool = True) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {
        "headless": bool(headless),
        "args": [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-popup-blocking",
        ],
    }
    try:
        import undetected_chromedriver as uc

        browser_path = uc.find_chrome_executable()
    except Exception:
        browser_path = None

    if browser_path and Path(browser_path).exists():
        launch_kwargs["executable_path"] = str(browser_path)
        return launch_kwargs

    launch_kwargs["channel"] = "chrome"
    return launch_kwargs


async def _stealth_context(browser_type, *, headless: bool = True):
    browser = await browser_type.launch(**_playwright_chrome_launch_kwargs(headless=headless))
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    await context.add_init_script(
        """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
        """
    )
    return browser, context


class QuotexPlaywrightAdapter:
    def __init__(self, *, email: str, password: str, headless: bool = True) -> None:
        self.email = email
        self.password = password
        self.headless = headless

    async def capture_chart(self, *, symbol: str, output_path: Path, url: str = "https://market-qx.trade/en/trade") -> Path:
        from playwright.async_api import async_playwright

        page = None
        async with async_playwright() as playwright:
            browser, context = await _stealth_context(playwright.chromium, headless=self.headless)
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                email_selectors = [
                    "input[type='email']",
                    "input[name='email']",
                    "input[id='email']",
                    "input[autocomplete='email']",
                ]
                password_selectors = [
                    "input[type='password']",
                    "input[name='password']",
                    "input[id='password']",
                ]
                for sel in email_selectors:
                    if await page.locator(sel).count() > 0:
                        await page.wait_for_selector(sel, timeout=10000)
                        await page.locator(sel).fill(self.email)
                        break
                for sel in password_selectors:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).fill(self.password)
                        break
                await page.wait_for_timeout(2500)
                chart = page.locator(".chart-container")
                await chart.screenshot(path=str(output_path))
                return output_path
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()


class PocketOptionPlaywrightAdapter:
    def __init__(self, *, email: str, password: str, headless: bool = True) -> None:
        self.email = email
        self.password = password
        self.headless = headless

    async def capture_chart(self, *, symbol: str, output_path: Path, url: str = "https://pocketoption.com") -> Path:
        from playwright.async_api import async_playwright

        page = None
        async with async_playwright() as playwright:
            browser, context = await _stealth_context(playwright.chromium, headless=self.headless)
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_selector("iframe", timeout=10000)
                frame = page.frame_locator("iframe")
                chart = frame.locator(".chart-container")
                await chart.screenshot(path=str(output_path))
                return output_path
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()


class IQOptionPlaywrightAdapter:
    def __init__(self, *, email: str, password: str, headless: bool = True) -> None:
        self.email = email
        self.password = password
        self.headless = headless

    async def capture_chart(self, *, symbol: str, output_path: Path, url: str = "https://iqoption.com/en/traderoom") -> Path:
        from playwright.async_api import async_playwright

        page = None
        async with async_playwright() as playwright:
            browser, context = await _stealth_context(playwright.chromium, headless=self.headless)
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_selector("input[type='email'], input[name='email'], input[name='identifier']", timeout=10000)
                try:
                    await page.locator("input[type='email'], input[name='email'], input[name='identifier']").first.fill(self.email)
                    await page.locator("input[type='password'], input[name='password']").first.fill(self.password)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)
                chart = page.locator(".chart-container, [class*='chart'], canvas").first
                await chart.screenshot(path=str(output_path))
                return output_path
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()


def _validated_mt5_login(raw_value: str) -> int:
    text = str(raw_value or "").strip()
    if not text or not text.strip():
        raise ValueError("Exness login is required.")
    if not text.isdigit():
        raise ValueError("Exness login must be the numeric MT5 account login, not an email or username.")
    return int(text)


def _normalize_twelve_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper().replace("/", "").replace("-", "")
    text = text.replace("(OTC)", "").replace("_OTC", "").replace(" ", "")
    if text.endswith("OTC"):
        text = text[:-3]
    if len(text) == 6 and text.isalpha():
        return f"{text[:3]}/{text[3:]}"
    return str(symbol or "").strip().upper()


def _parse_twelve_datetime(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        with suppress(ValueError):
            return int(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp())
    return 0


class TwelveDataForexAdapter:
    def __init__(self, *, api_key: str = "", login: str = "", password: str = "", server: str = "") -> None:
        self.login = login
        self.password = password
        self.server = server
        self.api_key = api_key

    def _api_key(self) -> str:
        key = str(self.api_key or self.server or "").strip()
        return key

    def initialize(self) -> Any:
        return {"provider": "twelve_data", "apikey": self._api_key()}

    def fetch_candles(self, *, symbol: str, timeframe: int, count: int = 120) -> list[Candle]:
        if not self._api_key():
            raise RuntimeError("Forex Market feed key required before Telegram forex analysis can run.")
        interval = "1min" if timeframe <= 1 else "5min"
        request_symbol = _normalize_twelve_symbol(symbol)
        query = urlencode(
            {
                "symbol": request_symbol,
                "interval": interval,
                "outputsize": max(30, min(int(count), 5000)),
                "order": "asc",
                "timezone": "UTC",
                "apikey": self._api_key(),
            }
        )
        url = f"https://api.twelvedata.com/time_series?{query}"
        payload = None
        for attempt in range(2):
            try:
                with urlopen(url, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except Exception as e:
                if attempt == 1:
                    raise
                asyncio.sleep(1.0)
        if payload is None:
            raise RuntimeError("Failed to fetch candle data after retries.")
        if str(payload.get("status") or "").lower() == "error":
            raise RuntimeError(str(payload.get("message") or payload))
        values = payload.get("values") or []
        candles: list[Candle] = []
        for row in values:
            timestamp = _parse_twelve_datetime(str(row.get("datetime") or ""))
            candles.append(
                Candle(
                    timestamp=timestamp or 0,
                    open=float(row.get("open") or 0.0),
                    high=float(row.get("high") or 0.0),
                    low=float(row.get("low") or 0.0),
                    close=float(row.get("close") or 0.0),
                    volume=float(row.get("volume") or 0.0),
                )
            )
        if not candles:
            raise RuntimeError(f"Forex Market did not return candle data for {request_symbol}.")
        return candles

    def calculate_lot_size(self, *, balance: float, stop_loss_points: float, point_value: float = 1.0) -> float:
        risk_amount = max(1.0, float(balance) * 0.01)
        denominator = max(0.0001, float(stop_loss_points) * float(point_value))
        return round(risk_amount / denominator, 2)

    def send_order(self, *, symbol: str, action: str, lot_size: float, stop_loss: float, take_profit: float) -> Any:
        raise RuntimeError("Forex Market does not support direct trade execution.")


ExnessMt5Adapter = TwelveDataForexAdapter


def run_async_broker_capture(coroutine):
    return asyncio.run(coroutine)
