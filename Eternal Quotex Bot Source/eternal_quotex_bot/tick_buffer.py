"""
Tick History Buffer system for real-time price analysis on Quotex OTC.

Stores real-time price ticks, builds micro-candles (1-minute OHLC), and provides
analytical methods for momentum, volatility, and support/resistance detection.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

from .models import Candle


# Maximum ticks retained per symbol (~25 minutes at 3-second intervals)
MAX_TICKS_PER_SYMBOL = 500

# Micro-candle periods in seconds (multi-timeframe)
CANDLE_PERIODS = {
    '1min': 60,
    '2min': 120,
    '5min': 300,
}


@dataclass(slots=True)
class TickRecord:
    timestamp: int
    price: float


class TickBuffer:
    """Per-symbol tick buffer with micro-candle construction and analytics."""

    def __init__(self, max_ticks: int = MAX_TICKS_PER_SYMBOL) -> None:
        self._max_ticks = max_ticks
        # symbol -> deque of TickRecord
        self._buffers: dict[str, Deque[TickRecord]] = defaultdict(
            lambda: deque(maxlen=self._max_ticks)
        )

    # ------------------------------------------------------------------
    # Core tick ingestion
    # ------------------------------------------------------------------

    def add_tick(self, symbol: str, price: float, timestamp: int | None = None) -> None:
        """Record a single price tick for *symbol*.

        If *timestamp* is omitted the current wall-clock time (seconds) is used.
        """
        if timestamp is None:
            timestamp = int(time.time())

        buf = self._buffers[symbol]
        buf.append(TickRecord(timestamp=timestamp, price=price))

    # ------------------------------------------------------------------
    # Candle building
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str, count: int = 80, period: str = '1min') -> list[Candle]:
        """Return up to *count* OHLC candles built from stored ticks.

        Args:
            symbol: Pair symbol
            count: Number of candles to return
            period: Candle timeframe ('1min', '2min', or '5min')
            
        Ticks are grouped into buckets aligned to period boundaries.
        Incomplete (still-forming) candles at the trailing edge are excluded.
        """
        candle_period = CANDLE_PERIODS.get(period, 60)
        
        buf = self._buffers.get(symbol)
        if not buf:
            return []

        ticks = list(buf)
        if not ticks:
            return []

        # Build OHLCV buckets
        buckets: dict[int, list[float]] = {}

        for tick in ticks:
            bucket_ts = (tick.timestamp // candle_period) * candle_period
            price = tick.price

            if bucket_ts not in buckets:
                buckets[bucket_ts] = [price, price, price, price, 0.0]
            else:
                ohlcv = buckets[bucket_ts]
                ohlcv[1] = max(ohlcv[1], price)
                ohlcv[2] = min(ohlcv[2], price)
                ohlcv[3] = price
                ohlcv[4] += 1.0

        sorted_keys = sorted(buckets.keys())

        # Exclude currently forming candle
        current_bucket = (int(time.time()) // candle_period) * candle_period
        if sorted_keys and sorted_keys[-1] >= current_bucket:
            sorted_keys.pop()

        selected_keys = sorted_keys[-count:]

        candles: list[Candle] = []
        for bucket_ts in selected_keys:
            ohlcv = buckets[bucket_ts]
            candles.append(
                Candle(
                    timestamp=bucket_ts,
                    open=ohlcv[0],
                    high=ohlcv[1],
                    low=ohlcv[2],
                    close=ohlcv[3],
                    volume=ohlcv[4],
                )
            )

        return candles

    def get_multi_timeframe_candles(self, symbol: str) -> dict[str, list[Candle]]:
        """Get candles for ALL timeframes (1min, 2min, 5min) from same tick buffer.
        
        Returns dict with keys '1min', '2min', '5min' each containing candle list.
        Used for cross-timeframe confirmation analysis.
        """
        return {
            '1min': self.get_candles(symbol, count=80, period='1min'),
            '2min': self.get_candles(symbol, count=40, period='2min'),
            '5min': self.get_candles(symbol, count=16, period='5min'),
        }

    # ------------------------------------------------------------------
    # Momentum analysis
    # ------------------------------------------------------------------

    def get_momentum(self, symbol: str, lookback: int = 20) -> float:
        """Return a normalized trend direction in the range [-1.0, 1.0].

        Computed from the slope of a linear regression over the last
        *lookback* tick prices. Positive = up-trend, negative = down-trend.
        """
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < 2:
            return 0.0

        prices = [t.price for t in buf][-lookback:]
        n = len(prices)
        if n < 2:
            return 0.0

        # Simple linear regression: y = a + b*x
        # x = index (0..n-1), y = price
        sum_x = (n - 1) * n / 2.0
        sum_y = sum(prices)
        sum_xy = sum(i * p for i, p in enumerate(prices))
        sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denom

        # Normalize by average price to get a unitless rate.
        avg_price = sum_y / n
        if avg_price == 0:
            return 0.0

        normalized_slope = slope / avg_price

        # Map to [-1, 1] using tanh for smooth saturation.
        # A slope of 0.01 per tick (~1% per tick) should be near max.
        momentum = math.tanh(normalized_slope * 100.0)
        return max(-1.0, min(1.0, momentum))

    # ------------------------------------------------------------------
    # Volatility measurement
    # ------------------------------------------------------------------

    def get_volatility(self, symbol: str, lookback: int = 50) -> float:
        """Return the average absolute percent price change between consecutive ticks.

        Result is expressed as a percentage (e.g. 0.15 means 0.15% average move).
        """
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < 2:
            return 0.0

        prices = [t.price for t in buf][-lookback:]
        changes: list[float] = []

        for i in range(1, len(prices)):
            prev = prices[i - 1]
            curr = prices[i]
            if prev == 0:
                continue
            changes.append(abs((curr - prev) / prev) * 100.0)

        if not changes:
            return 0.0

        return sum(changes) / len(changes)

    # ------------------------------------------------------------------
    # Support / Resistance detection
    # ------------------------------------------------------------------

    def get_support_resistance(
        self, symbol: str, lookback: int = 100
    ) -> tuple[float, float]:
        """Return ``(support, resistance)`` estimated from recent tick extremes.

        Uses a percentile-based approach:
        - Support = 5th percentile of low prices
        - Resistance = 95th percentile of high prices

        When only raw ticks are available, price is used for both.
        """
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < 2:
            return (0.0, 0.0)

        prices = [t.price for t in buf][-lookback:]
        if not prices:
            return (0.0, 0.0)

        sorted_prices = sorted(prices)
        n = len(sorted_prices)

        support_idx = max(0, int(n * 0.05))
        resistance_idx = min(n - 1, int(n * 0.95))

        support = sorted_prices[support_idx]
        resistance = sorted_prices[resistance_idx]

        return (support, resistance)

    # ------------------------------------------------------------------
    # Utility / housekeeping
    # ------------------------------------------------------------------

    def tick_count(self, symbol: str) -> int:
        """Return the number of ticks currently stored for *symbol*."""
        return len(self._buffers.get(symbol, []))

    def symbols(self) -> list[str]:
        """Return a list of symbols that have at least one tick."""
        return [sym for sym, buf in self._buffers.items() if buf]

    def last_price(self, symbol: str) -> float | None:
        """Return the most recent tick price for *symbol*, or ``None``."""
        buf = self._buffers.get(symbol)
        if buf:
            return buf[-1].price
        return None

    def clear(self, symbol: str | None = None) -> None:
        """Clear tick history. If *symbol* is None, clear all buffers."""
        if symbol is None:
            self._buffers.clear()
        else:
            self._buffers.pop(symbol, None)

    def age_seconds(self, symbol: str) -> float:
        """Return the time span (in seconds) covered by ticks for *symbol*."""
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < 2:
            return 0.0
        return buf[-1].timestamp - buf[0].timestamp

    # ------------------------------------------------------------------
    # Advanced OTC Analytics
    # ------------------------------------------------------------------

    def detect_liquidity_grab(self, symbol: str, lookback: int = 30) -> float:
        """
        Detect a 'Liquidity Grab' (V-shape or inverted V recovery) in ticks.
        Returns a score from -1.0 (bearish grab/rejection) to 1.0 (bullish grab/rejection).
        """
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < 10:
            return 0.0
        
        prices = [t.price for t in buf][-lookback:]
        n = len(prices)
        
        # Bullish Liquidity Grab: Price drops fast then recovers fast
        # Find local low in the middle
        low_idx = prices.index(min(prices))
        if 2 < low_idx < n - 3:
            pre_drop = prices[0] - prices[low_idx]
            post_recovery = prices[-1] - prices[low_idx]
            if pre_drop > 0 and post_recovery > 0:
                # Strong V-shape
                score = min(pre_drop, post_recovery) / max(prices) * 1000
                return min(1.0, score * 5.0)

        # Bearish Liquidity Grab (Inverted V)
        high_idx = prices.index(max(prices))
        if 2 < high_idx < n - 3:
            pre_rise = prices[high_idx] - prices[0]
            post_drop = prices[high_idx] - prices[-1]
            if pre_rise > 0 and post_drop > 0:
                score = min(pre_rise, post_drop) / max(prices) * 1000
                return -min(1.0, score * 5.0)

        return 0.0

    def detect_volume_spike(self, symbol: str, lookback: int = 15) -> bool:
        """Detect if the tick frequency (proxy for volume) has recently spiked."""
        buf = self._buffers.get(symbol)
        if not buf or len(buf) < lookback * 2:
            return False
            
        recent_ticks = list(buf)[-lookback:]
        prev_ticks = list(buf)[-lookback*2:-lookback]
        
        recent_span = recent_ticks[-1].timestamp - recent_ticks[0].timestamp
        prev_span = prev_ticks[-1].timestamp - prev_ticks[0].timestamp
        
        if recent_span > 0 and prev_span > 0:
            # If recent ticks arrived much faster than previous ticks
            if recent_span < prev_span * 0.5:
                return True
        
        return False
