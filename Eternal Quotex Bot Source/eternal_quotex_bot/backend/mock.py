from __future__ import annotations

import asyncio
import random
import time
import uuid

from eternal_quotex_bot.backend.base import TradingBackend
from eternal_quotex_bot.models import AccountSnapshot, AssetInfo, Candle, ConnectionProfile, TradeTicket


DEFAULT_MOCK_ASSETS: dict[str, dict[str, float]] = {
    "EURUSD": {"price": 1.0812, "payout": 82.0},
    "GBPUSD": {"price": 1.2644, "payout": 79.0},
    "USDJPY": {"price": 153.72, "payout": 77.0},
    "XAUUSD": {"price": 2284.4, "payout": 84.0},
    "EURUSD_otc": {"price": 1.0791, "payout": 89.0},
}


def default_mock_assets() -> list[AssetInfo]:
    return [
        AssetInfo(
            symbol=symbol,
            payout=spec["payout"],
            is_open=True,
            category="mock",
            last_price=spec["price"],
        )
        for symbol, spec in sorted(DEFAULT_MOCK_ASSETS.items())
    ]


class MockQuotexBackend(TradingBackend):
    name = "Mock Sandbox"

    def __init__(self) -> None:
        self.connected = False
        self.balance = 1_000.0
        self.profile = ConnectionProfile()
        self.random = random.Random(17)
        self.assets = {symbol: dict(spec) for symbol, spec in DEFAULT_MOCK_ASSETS.items()}
        self.history: dict[str, list[Candle]] = {}
        self.open_trades: dict[str, TradeTicket] = {}
        for symbol in self.assets:
            self.history[symbol] = self._seed_candles(symbol)

    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        await asyncio.sleep(0.15)
        self.connected = True
        self.profile = profile
        return AccountSnapshot(balance=self.balance, mode=profile.account_mode.upper(), backend_name=self.name)

    async def disconnect(self) -> None:
        self.connected = False
        self.open_trades.clear()

    async def fetch_assets(self) -> list[AssetInfo]:
        await asyncio.sleep(0.05)
        return [
            AssetInfo(
                symbol=symbol,
                payout=data["payout"],
                is_open=True,
                category="mock",
                last_price=self.history[symbol][-1].close,
            )
            for symbol, data in sorted(self.assets.items())
        ]

    async def fetch_balance(self) -> float:
        await asyncio.sleep(0.03)
        return self.balance

    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        await asyncio.sleep(0.08)
        candles = self.history.setdefault(asset, self._seed_candles(asset))
        self._nudge_live_price(asset)
        self._extend_history(asset, period_seconds)
        return candles[-count:]

    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        await asyncio.sleep(0.08)
        payout = self.assets.get(asset, {}).get("payout", 80.0)
        ticket = TradeTicket(
            id=uuid.uuid4().hex[:10],
            asset=asset,
            action=action.upper(),
            amount=float(amount),
            duration=int(duration),
            opened_at=time.time(),
            expiry_time=time.time() + duration,
            estimated_payout=float(payout),
            is_demo=True,
            accepted=True,
            raw={"provider": self.name},
        )
        self.open_trades[ticket.id] = ticket
        return ticket

    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        await asyncio.sleep(min(2.0, max(ticket.duration / 60, 1.0)))
        candles = self.history[ticket.asset]
        drift = candles[-1].close - candles[-3].close
        weighted = 0.55 if drift > 0 else 0.45
        if ticket.action == "PUT":
            weighted = 1 - weighted
        ticket.result = self.random.random() < weighted
        ticket.profit = ticket.amount * (ticket.estimated_payout / 100) if ticket.result else -ticket.amount
        self.balance += ticket.profit
        self.open_trades.pop(ticket.id, None)
        return ticket

    def _seed_candles(self, asset: str) -> list[Candle]:
        start_price = self.assets.get(asset, {}).get("price", 1.2)
        candles: list[Candle] = []
        timestamp = int(time.time()) - 120 * 60
        price = start_price
        bias = self._bias_for_asset(asset)
        for _ in range(120):
            price = max(0.1, price + bias + self.random.uniform(-abs(bias) * 0.65, abs(bias) * 0.35))
            high = price + self.random.uniform(abs(bias) * 0.25, abs(bias) * 1.8)
            low = price - self.random.uniform(abs(bias) * 0.25, abs(bias) * 1.8)
            close = price + self.random.uniform(-abs(bias) * 0.45, abs(bias) * 0.75)
            candles.append(
                Candle(
                    timestamp=timestamp,
                    open=round(price, 5),
                    high=round(max(high, close), 5),
                    low=round(min(low, close), 5),
                    close=round(close, 5),
                    volume=self.random.uniform(50, 200),
                )
            )
            price = close
            timestamp += 60
        return candles

    def _extend_history(self, asset: str, period_seconds: int) -> None:
        candles = self.history[asset]
        last = candles[-1]
        now = int(time.time())
        if now - last.timestamp < period_seconds:
            return
        base = last.close
        bias = self._bias_for_asset(asset)
        high = base + self.random.uniform(abs(bias) * 0.2, abs(bias) * 1.6)
        low = base - self.random.uniform(abs(bias) * 0.2, abs(bias) * 1.4)
        close = base + bias + self.random.uniform(-abs(bias) * 0.5, abs(bias) * 0.8)
        candles.append(
            Candle(
                timestamp=last.timestamp + period_seconds,
                open=round(base, 5),
                high=round(max(high, close), 5),
                low=round(min(low, close), 5),
                close=round(close, 5),
                volume=self.random.uniform(60, 180),
            )
        )
        self.assets[asset]["price"] = close

    def _nudge_live_price(self, asset: str) -> None:
        candles = self.history[asset]
        last = candles[-1]
        bias = self._bias_for_asset(asset)
        drift = bias * 0.35 + self.random.uniform(-abs(bias) * 0.45, abs(bias) * 0.45)
        close = max(0.1, last.close + drift)
        high = max(last.high, close)
        low = min(last.low, close)
        candles[-1] = Candle(
            timestamp=last.timestamp,
            open=last.open,
            high=round(high, 5),
            low=round(low, 5),
            close=round(close, 5),
            volume=last.volume + self.random.uniform(1, 10),
        )
        self.assets[asset]["price"] = close

    def _bias_for_asset(self, asset: str) -> float:
        if "JPY" in asset:
            base = 0.035
        elif asset.startswith("XAU"):
            base = 1.1
        else:
            base = 0.00075
        direction = 1 if asset in {"EURUSD", "EURUSD_otc", "XAUUSD"} else -1
        return base * direction
