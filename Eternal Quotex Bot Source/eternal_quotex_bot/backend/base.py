from __future__ import annotations

from abc import ABC, abstractmethod

from eternal_quotex_bot.models import AccountSnapshot, AssetInfo, Candle, ConnectionProfile, TradeTicket


class TradingBackend(ABC):
    name = "backend"

    @abstractmethod
    async def connect(self, profile: ConnectionProfile) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def fetch_assets(self) -> list[AssetInfo]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_balance(self) -> float:
        raise NotImplementedError

    @abstractmethod
    async def fetch_candles(self, asset: str, period_seconds: int, count: int = 80) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    async def place_trade(self, asset: str, action: str, amount: float, duration: int) -> TradeTicket:
        raise NotImplementedError

    @abstractmethod
    async def check_trade_result(self, ticket: TradeTicket) -> TradeTicket:
        raise NotImplementedError

