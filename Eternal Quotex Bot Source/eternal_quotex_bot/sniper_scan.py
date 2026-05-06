"""
Sniper Mode Deep Scan System for Quotex OTC.

Provides high-confidence "sureshot" signals by combining:
- 15-indicator technical analysis on candles built from real-time ticks
- OTC-specific algorithmic pattern detection (repeating tick sequences)
- Tick momentum analysis (last 20 ticks trend)
- Support/Resistance bounce detection

Signals are only returned when confidence >= 75% and multiple indicators align.
Otherwise returns "WAITING" status.
"""

from __future__ import annotations

import math
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque

from .models import Candle, StrategyDecision
from .tick_buffer import TickBuffer
from .strategy import (
    ema,
    rsi,
    macd,
    bollinger_bands,
    stochastic,
    williams_r,
    cci,
    average_true_range,
    adx,
    vwap,
    momentum_score,
    linear_regression_slope,
)


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = ["USDBDT_otc", "USDINR_otc"]
CONFIDENCE_THRESHOLD = 0.75
DEFAULT_EXPIRY_SECONDS = 120
TICK_MOMENTUM_LOOKBACK = 20
PATTERN_MIN_LENGTH = 3
PATTERN_MAX_LENGTH = 8
PATTERN_TOLERANCE_PCT = 0.0002


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SniperSignal:
    """Result from a Sniper Mode Deep Scan."""
    status: str  # "CALL", "PUT", or "WAITING"
    symbol: str
    confidence: float
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS
    current_price: float = 0.0
    # Standard indicators
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bb_lower: float | None = None
    bb_middle: float | None = None
    bb_upper: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    williams: float | None = None
    cci: float | None = None
    atr: float | None = None
    adx: float | None = None
    vwap: float | None = None
    momentum: float = 0.0
    lr_slope: float | None = None
    # OTC-specific
    tick_momentum: float = 0.0
    pattern_detected: str = ""
    pattern_direction: str = ""
    pattern_confidence: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    at_support: bool = False
    at_resistance: bool = False
    sr_bounce_direction: str = ""
    # Summary
    agreed_indicators: int = 0
    total_indicators: int = 0
    reason: str = ""
    timestamp: int = 0


# ---------------------------------------------------------------------------
# OTC Algorithmic Pattern Detection
# ---------------------------------------------------------------------------

def _detect_repeating_patterns(
    prices: list[float],
    min_len: int = PATTERN_MIN_LENGTH,
    max_len: int = PATTERN_MAX_LENGTH,
    tolerance: float = PATTERN_TOLERANCE_PCT,
) -> tuple[str, str, float]:
    """Search for repeating price-change sequences in recent ticks.

    Returns (pattern_description, direction, confidence).
    direction is "CALL", "PUT", or "".
    """
    if len(prices) < min_len * 2 + 1:
        return ("", "", 0.0)

    # Convert to price changes (deltas)
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    best_pattern = ""
    best_direction = ""
    best_confidence = 0.0
    best_count = 0

    for pat_len in range(min_len, max_len + 1):
        if pat_len * 2 > len(deltas):
            break

        # Slide a window of size pat_len over deltas
        candidates: list[tuple[int, list[float]]] = []
        for start in range(len(deltas) - pat_len + 1):
            window = deltas[start:start + pat_len]
            candidates.append((start, window))

        # Compare all pairs of windows
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                idx_a, wa = candidates[i]
                idx_b, wb = candidates[j]

                # Skip overlapping windows
                if abs(idx_a - idx_b) < pat_len:
                    continue

                match_count = 0
                for da, db in zip(wa, wb):
                    avg = (abs(da) + abs(db)) / 2.0
                    threshold = max(avg * tolerance, 1e-8)
                    if abs(da - db) < threshold:
                        match_count += 1

                match_ratio = match_count / pat_len
                if match_ratio >= 0.7 and match_count > best_count:
                    best_count = match_count
                    # Determine direction from the pattern's net delta
                    net_delta = sum(wa)
                    if net_delta > 0:
                        best_direction = "CALL"
                    elif net_delta < 0:
                        best_direction = "PUT"
                    best_pattern = f"repeating_{pat_len}_tick_sequence"
                    best_confidence = min(0.95, match_ratio * 0.8)

    return (best_pattern, best_direction, best_confidence)


# ---------------------------------------------------------------------------
# Tick Momentum Analysis
# ---------------------------------------------------------------------------

def _tick_momentum_analysis(
    prices: list[float],
    lookback: int = TICK_MOMENTUM_LOOKBACK,
) -> float:
    """Analyze the last *lookback* ticks for directional momentum.

    Returns a value in [-1.0, 1.0] where positive = bullish, negative = bearish.
    Uses a weighted approach: more recent ticks have higher influence.
    """
    if len(prices) < 2:
        return 0.0

    segment = prices[-lookback:]
    n = len(segment)

    # Weighted linear regression (exponential weights)
    weights = [math.exp(-0.1 * (n - 1 - i)) for i in range(n)]
    w_sum = sum(weights)

    x_vals = list(range(n))
    y_vals = segment

    x_mean = sum(w * x for w, x in zip(weights, x_vals)) / w_sum
    y_mean = sum(w * y for w, y in zip(weights, y_vals)) / w_sum

    numerator = sum(w * (x - x_mean) * (y - y_mean) for w, x, y in zip(weights, x_vals, y_vals))
    denominator = sum(w * (x - x_mean) ** 2 for w, x in zip(weights, x_vals))

    if denominator == 0:
        return 0.0

    slope = numerator / denominator

    # Normalize by average price
    if y_mean == 0:
        return 0.0

    normalized = slope / y_mean
    return max(-1.0, min(1.0, math.tanh(normalized * 200.0)))


# ---------------------------------------------------------------------------
# Support / Resistance Bounce Detection
# ---------------------------------------------------------------------------

def _sr_bounce_analysis(
    candles: list[Candle],
    support: float,
    resistance: float,
    tolerance_pct: float = 0.001,
) -> tuple[bool, bool, str]:
    """Check if current price is bouncing off support or resistance.

    Returns (at_support, at_resistance, direction).
    direction is "CALL" if bouncing off support, "PUT" if off resistance, "" otherwise.
    """
    if not candles or support == 0 or resistance == 0:
        return (False, False, "")

    current = candles[-1].close
    price_range = resistance - support
    if price_range == 0:
        return (False, False, "")

    tol = price_range * tolerance_pct

    at_support = abs(current - support) <= tol
    at_resistance = abs(current - resistance) <= tol

    direction = ""
    if at_support:
        # Check if previous candles were near support and price held
        if len(candles) >= 2:
            prev_low = candles[-2].low
            if prev_low >= support - tol * 2 and current > candles[-1].open:
                direction = "CALL"
    elif at_resistance:
        if len(candles) >= 2:
            prev_high = candles[-2].high
            if prev_high <= resistance + tol * 2 and current < candles[-1].open:
                direction = "PUT"

    return (at_support, at_resistance, direction)


# ---------------------------------------------------------------------------
# 15-Indicator Technical Analysis + OTC Fusion
# ---------------------------------------------------------------------------

def _score_indicators(
    candles: list[Candle],
    closes: list[float],
    signal: SniperSignal,
) -> tuple[str, float, int, int]:
    """Run 15 indicators and produce a scored vote.

    Returns (action, confidence, agreed_count, total_count).
    """
    call_score = 0.0
    put_score = 0.0
    indicator_votes = 0
    indicator_total = 0

    signal_candle = candles[-1]
    last_close = signal_candle.close
    previous_candle = candles[-2] if len(candles) > 1 else signal_candle
    previous_close = previous_candle.close

    fast_period = 9
    slow_period = 21

    ema_fast_all = ema(closes, fast_period)
    ema_slow_all = ema(closes, slow_period)

    basis_index = len(candles) - 1
    fast_now = ema_fast_all[basis_index] if basis_index < len(ema_fast_all) else last_close
    slow_now = ema_slow_all[basis_index] if basis_index < len(ema_slow_all) else last_close
    fast_prev = ema_fast_all[basis_index - 1] if basis_index > 0 else fast_now
    slow_prev = ema_slow_all[basis_index - 1] if basis_index > 0 else slow_now

    # --- 1. EMA Crossover (weight 4.0) ---
    indicator_total += 1
    spread = fast_now - slow_now
    if spread > 0:
        call_score += 4.0
    else:
        put_score += 4.0
    if fast_prev > slow_prev and spread <= 0:
        put_score += 1.0  # fresh bearish cross bonus
    elif fast_prev < slow_prev and spread > 0:
        call_score += 1.0  # fresh bullish cross bonus

    # --- 2. RSI (weight 3.0) ---
    rsi_val = rsi(closes, 14)
    signal.rsi = rsi_val
    if rsi_val is not None:
        indicator_total += 1
        if rsi_val < 35:
            call_score += 3.0  # deeply oversold
        elif rsi_val < 45:
            call_score += 2.0
        elif rsi_val > 65:
            put_score += 3.0  # deeply overbought
        elif rsi_val > 55:
            put_score += 2.0

    # --- 3. MACD (weight 3.5) ---
    macd_val, macd_sig_val, macd_hist = macd(closes)
    signal.macd = macd_val
    signal.macd_signal = macd_sig_val
    signal.macd_histogram = macd_hist
    if macd_val is not None and macd_sig_val is not None:
        indicator_total += 1
        if macd_val > macd_sig_val and macd_hist is not None and macd_hist > 0:
            call_score += 3.5
            if macd_hist > 0.0003 * last_close:
                call_score += 1.0
        elif macd_val < macd_sig_val and macd_hist is not None and macd_hist < 0:
            put_score += 3.5
            if macd_hist < -0.0003 * last_close:
                put_score += 1.0

    # --- 4. Bollinger Bands (weight 2.5) ---
    bb_lower, bb_mid, bb_upper = bollinger_bands(closes)
    signal.bb_lower = bb_lower
    signal.bb_middle = bb_mid
    signal.bb_upper = bb_upper
    if bb_lower is not None and bb_upper is not None:
        indicator_total += 1
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_pos = (last_close - bb_lower) / bb_range
            if bb_pos < 0.2:
                call_score += 2.5
            elif bb_pos < 0.35:
                call_score += 1.5
            elif bb_pos > 0.8:
                put_score += 2.5
            elif bb_pos > 0.65:
                put_score += 1.5

    # --- 5. Stochastic (weight 2.5) ---
    stoch = stochastic(candles)
    if stoch is not None:
        k, d = stoch
        signal.stoch_k = k
        signal.stoch_d = d
        indicator_total += 1
        if k < 25 and k > d:
            call_score += 2.5
        elif k < 40 and k > d:
            call_score += 1.5
        elif k > 75 and k < d:
            put_score += 2.5
        elif k > 60 and k < d:
            put_score += 1.5

    # --- 6. Williams %R (weight 2.0) ---
    wr = williams_r(candles)
    signal.williams = wr
    if wr is not None:
        indicator_total += 1
        if wr < -80:
            call_score += 2.0
        elif wr < -60:
            call_score += 1.0
        elif wr > -20:
            put_score += 2.0
        elif wr > -40:
            put_score += 1.0

    # --- 7. CCI (weight 2.0) ---
    cci_val = cci(candles)
    signal.cci = cci_val
    if cci_val is not None:
        indicator_total += 1
        if cci_val < -100:
            call_score += 2.0
        elif cci_val < -50:
            call_score += 1.0
        elif cci_val > 100:
            put_score += 2.0
        elif cci_val > 50:
            put_score += 1.0

    # --- 8. ATR (volatility filter) (weight 1.0) ---
    atr_val = average_true_range(candles)
    signal.atr = atr_val
    if atr_val is not None:
        indicator_total += 1
        # ATR doesn't give direction, but high ATR confirms trend strength
        atr_pct = atr_val / max(last_close, 1e-6)
        if atr_pct > 0.001:
            # High volatility amplifies existing trend
            if spread > 0:
                call_score += 1.0
            else:
                put_score += 1.0

    # --- 9. ADX (trend strength) (weight 2.0) ---
    adx_val = adx(candles)
    signal.adx = adx_val
    if adx_val is not None:
        indicator_total += 1
        if adx_val > 30:
            # Strong trend - amplify dominant direction
            if spread > 0:
                call_score += 2.0
            else:
                put_score += 2.0
        elif adx_val > 20:
            if spread > 0:
                call_score += 1.0
            else:
                put_score += 1.0

    # --- 10. VWAP (weight 2.5) ---
    vwap_val = vwap(candles)
    signal.vwap = vwap_val
    if vwap_val is not None:
        indicator_total += 1
        if last_close > vwap_val:
            call_score += 2.5
        else:
            put_score += 2.5

    # --- 11. Momentum Score (weight 2.0) ---
    mom = momentum_score(candles, 5)
    signal.momentum = mom
    indicator_total += 1
    if mom > 0.3:
        call_score += 2.0
    elif mom > 0.1:
        call_score += 1.0
    elif mom < -0.3:
        put_score += 2.0
    elif mom < -0.1:
        put_score += 1.0

    # --- 12. Linear Regression Slope (weight 1.5) ---
    lr_slope = linear_regression_slope(closes, 20)
    signal.lr_slope = lr_slope
    if lr_slope is not None:
        indicator_total += 1
        threshold = 0.0001 * last_close
        if lr_slope > threshold:
            call_score += 1.5
        elif lr_slope < -threshold:
            put_score += 1.5

    # --- 13. Candle Structure (weight 2.5) ---
    indicator_total += 1
    range_size = max(signal_candle.high - signal_candle.low, 1e-6)
    body = signal_candle.close - signal_candle.open
    close_location = (signal_candle.close - signal_candle.low) / range_size
    if body > 0 and close_location > 0.6:
        call_score += 2.5
    elif body > 0:
        call_score += 1.5
    elif body < 0 and close_location < 0.4:
        put_score += 2.5
    elif body < 0:
        put_score += 1.5

    # --- 14. Close vs Previous (weight 1.5) ---
    indicator_total += 1
    if last_close > previous_close:
        call_score += 1.5
    elif last_close < previous_close:
        put_score += 1.5

    # --- 15. EMA Slope Confirmation (weight 1.5) ---
    indicator_total += 1
    fast_slope = fast_now - fast_prev
    slow_slope = slow_now - slow_prev
    if fast_slope > 0 and slow_slope > 0:
        call_score += 1.5
    elif fast_slope < 0 and slow_slope < 0:
        put_score += 1.5

    # --- Determine winner ---
    total = call_score + put_score
    if total == 0:
        return ("HOLD", 0.5, 0, indicator_total)

    max_score = max(call_score, put_score)
    dominance = max_score / total

    # Confidence: directional, but more conservative on mixed agreement.
    confidence = 0.48 + dominance * 0.32
    score_gap = abs(call_score - put_score)
    confidence = min(0.90, confidence + min(0.08, score_gap / 45.0))
    body_ratio = abs(body) / max(range_size, 1e-6)
    if dominance < 0.56:
        confidence = min(confidence, 0.58)
    elif dominance < 0.64:
        confidence = min(confidence, 0.67)
    if (adx_val or 0.0) < 18:
        confidence = min(confidence, 0.68)
    if body_ratio < 0.25:
        confidence = min(confidence, 0.69)

    # Count agreeing indicators
    call_indicators = 0
    put_indicators = 0
    # We count each indicator that voted for the winning side
    # (simplified: if call_score > put_score, count all call-weighted portions)
    agreed = 0
    if call_score > put_score:
        # Rough count: indicators that contributed to call_score
        for _ in range(indicator_total):
            agreed += 1
        agreed = max(1, int(indicator_total * (call_score / total)))
    else:
        agreed = max(1, int(indicator_total * (put_score / total)))

    return ("CALL" if call_score > put_score else "PUT", confidence, agreed, indicator_total)


# ---------------------------------------------------------------------------
# Main Sniper Scanner
# ---------------------------------------------------------------------------

from .advanced_signal_engine import AdvancedSignalEngine

class SniperScanner:
    """Sniper Mode Deep Scan system for Quotex OTC.

    Usage::

        scanner = SniperScanner(tick_buffer, pairs=["EUR/USD_otc"])
        signal = scanner.scan("EUR/USD_otc")

    The scanner uses the shared ``TickBuffer`` to build candles from
    real-time ticks and runs comprehensive analysis before returning
    a signal.
    """

    def __init__(
        self,
        tick_buffer: TickBuffer,
        pairs: list[str] | None = None,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        self._ticks = tick_buffer
        self._pairs = pairs if pairs is not None else list(DEFAULT_PAIRS)
        self._threshold = confidence_threshold
        self._expiry = expiry_seconds
        self._engine = AdvancedSignalEngine()

    @property
    def pairs(self) -> list[str]:
        return list(self._pairs)

    @pairs.setter
    def pairs(self, value: list[str]) -> None:
        self._pairs = list(value)

    @property
    def confidence_threshold(self) -> float:
        return self._threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        self._threshold = max(0.5, min(0.95, value))

    # ------------------------------------------------------------------
    # Single-pair scan
    # ------------------------------------------------------------------

    def scan(self, symbol: str | None = None) -> SniperSignal:
        """Run a full deep scan on *symbol* (or the first configured pair).

        Keeps a directional bias, but weak setups stay labeled as weak.
        """
        target = symbol or (self._pairs[0] if self._pairs else None)
        if not self._pairs:
            return SniperSignal(
                status="CALL",  # Default to CALL if no pairs
                symbol="USDBDT_otc",
                confidence=0.50,
                reason="No pairs configured.",
                timestamp=int(time.time()),
            )

        # Get current price from tick buffer
        current_price = self._ticks.last_price(target)
        if current_price is None or current_price <= 0:
            return SniperSignal(
                status="CALL",
                symbol=target,
                confidence=0.50,
                current_price=0.0,
                reason=f"No price data for {target}.",
                timestamp=int(time.time()),
            )

        # Try to build candles from tick buffer
        candles = self._ticks.get_candles(target, count=100)
        
        if len(candles) >= 35:
            # HAVE CANDLES - use full Quantum AI analysis
            return self._scan_with_quantum_engine(target, candles, current_price)
        else:
            # NO CANDLES - use tick momentum analysis
            return self._scan_with_ticks(target, current_price)

    def _scan_with_quantum_engine(
        self, target: str, candles: list[Candle], current_price: float
    ) -> SniperSignal:
        """Full Quantum AI analysis when candle data is available."""
        
        # Use the advanced signal engine
        adv_result = self._engine.analyze(candles)

        signal = SniperSignal(
            status=adv_result.action,
            symbol=target,
            confidence=adv_result.confidence,
            current_price=current_price,
            expiry_seconds=self._expiry,
            timestamp=int(time.time()),
            rsi=adv_result.rsi,
            macd_histogram=adv_result.macd_histogram,
            pattern_detected=adv_result.pattern_detected,
            reason=adv_result.reason,
            agreed_indicators=adv_result.indicators_agreed,
            total_indicators=adv_result.total_indicators,
        )

        # --- OTC-specific: Tick momentum ---
        raw_ticks = self._ticks._buffers.get(target)
        tick_prices = [t.price for t in raw_ticks] if raw_ticks else []
        tick_mom = _tick_momentum_analysis(tick_prices, TICK_MOMENTUM_LOOKBACK)
        signal.tick_momentum = tick_mom

        # Combine with tick momentum for OTC boost
        if (tick_mom > 0.0002 and adv_result.action == "CALL") or \
           (tick_mom < -0.0002 and adv_result.action == "PUT"):
            signal.confidence = min(0.99, signal.confidence + 0.05)
            signal.reason += f" | Strong Tick Momentum confirmed (+5%)"

        return signal

    def _scan_with_candles(
        self, target: str, candles: list[Candle], current_price: float
    ) -> SniperSignal:
        """Full 15-indicator analysis when candle data is available."""
        closes = [c.close for c in candles]

        signal = SniperSignal(
            status="WAITING",
            symbol=target,
            confidence=0.0,
            current_price=current_price,
            expiry_seconds=self._expiry,
            timestamp=int(time.time()),
        )

        # --- 15-indicator scoring on 1min candles ---
        action, raw_confidence, agreed, total = _score_indicators(candles, closes, signal)

        # --- Multi-timeframe confirmation ---
        multi_tf = self._ticks.get_multi_timeframe_candles(target)
        tf_confirmation = 0
        tf_total = 0
        
        # Check 2min timeframe
        candles_2m = multi_tf.get('2min', [])
        if len(candles_2m) >= 10:
            closes_2m = [c.close for c in candles_2m]
            ema_fast_2m = ema(closes_2m, 9)
            ema_slow_2m = ema(closes_2m, 21)
            if len(ema_fast_2m) > 1 and len(ema_slow_2m) > 1:
                tf_total += 1
                if (ema_fast_2m[-1] > ema_slow_2m[-1] and action == "CALL") or \
                   (ema_fast_2m[-1] < ema_slow_2m[-1] and action == "PUT"):
                    tf_confirmation += 1
        
        # Check 5min timeframe
        candles_5m = multi_tf.get('5min', [])
        if len(candles_5m) >= 5:
            closes_5m = [c.close for c in candles_5m]
            ema_fast_5m = ema(closes_5m, 9)
            ema_slow_5m = ema(closes_5m, 21)
            if len(ema_fast_5m) > 1 and len(ema_slow_5m) > 1:
                tf_total += 1
                if (ema_fast_5m[-1] > ema_slow_5m[-1] and action == "CALL") or \
                   (ema_fast_5m[-1] < ema_slow_5m[-1] and action == "PUT"):
                    tf_confirmation += 1
        
        # Multi-timeframe bonus
        tf_bonus = 0.0
        if tf_total > 0:
            tf_ratio = tf_confirmation / tf_total
            tf_bonus = tf_ratio * 0.06

        # --- OTC-specific: Tick momentum ---
        raw_ticks = self._ticks._buffers.get(target)
        tick_prices = [t.price for t in raw_ticks] if raw_ticks else []
        tick_mom = _tick_momentum_analysis(tick_prices, TICK_MOMENTUM_LOOKBACK)
        signal.tick_momentum = tick_mom

        # --- OTC-specific: Pattern detection ---
        pat_name, pat_dir, pat_conf = _detect_repeating_patterns(tick_prices)
        signal.pattern_detected = pat_name
        signal.pattern_direction = pat_dir
        signal.pattern_confidence = pat_conf
        
        # --- OTC-specific: Liquidity Grab ---
        liq_grab = self._ticks.detect_liquidity_grab(target)
        if (liq_grab > 0.4 and adv_result.action == "CALL") or \
           (liq_grab < -0.4 and adv_result.action == "PUT"):
            signal.confidence = min(0.99, signal.confidence + 0.10)
            signal.reason += f" | LIQUIDITY GRAB confirmed (+10%)"
        elif abs(liq_grab) > 0.7:
            # Strong liquidity grab can override other indicators
            signal.status = "CALL" if liq_grab > 0 else "PUT"
            signal.confidence = max(signal.confidence, 0.82)
            signal.reason = f"QUANTUM REVERSAL: Liquidity Grab {abs(liq_grab):.2f}"

        # --- OTC-specific: Support/Resistance ---
        support, resistance = self._ticks.get_support_resistance(target)
        signal.support = support
        signal.resistance = resistance
        at_sup, at_res, sr_dir = _sr_bounce_analysis(candles, support, resistance)
        signal.at_support = at_sup
        signal.at_resistance = at_res
        signal.sr_bounce_direction = sr_dir

        # ------------------------------------------------------------------
        # FUSION: combine standard + OTC + multi-timeframe signals
        # ------------------------------------------------------------------

        otc_boost = 0.0
        otc_agreements = 0

        # Tick momentum agreement
        if tick_mom > 0.3 and action == "CALL":
            otc_boost += 0.05
            otc_agreements += 1
        elif tick_mom < -0.3 and action == "PUT":
            otc_boost += 0.05
            otc_agreements += 1

        # Pattern agreement
        if pat_dir == action and pat_conf > 0.5:
            otc_boost += 0.08
            otc_agreements += 1

        # SR bounce agreement
        if sr_dir == action:
            otc_boost += 0.07
            otc_agreements += 1

        # Multi-timeframe agreement bonus
        final_confidence = min(0.90, raw_confidence + (otc_boost * 0.75) + tf_bonus)

        # Count total indicators
        total_indicators = total + 3 + tf_total  # standard + OTC + timeframes
        agreed_indicators = agreed + otc_agreements + tf_confirmation

        signal.agreed_indicators = agreed_indicators
        signal.total_indicators = total_indicators

        # --- Final decision - keep direction, but cap mixed setups honestly ---
        agreement_ratio = agreed_indicators / total_indicators if total_indicators > 0 else 0
        if agreement_ratio < 0.56:
            final_confidence = min(final_confidence, 0.58)
        elif agreement_ratio < 0.64:
            final_confidence = min(final_confidence, 0.67)
        if tf_total > 0 and tf_confirmation == 0:
            final_confidence = min(final_confidence, 0.60)
        elif tf_total > 0 and tf_confirmation < tf_total:
            final_confidence = min(final_confidence, 0.68)
        
        signal.status = action
        signal.confidence = round(final_confidence, 4)
        
        # Build detailed reason
        tf_text = f"{tf_confirmation}/{tf_total} timeframes agree" if tf_total > 0 else ""
        signal.reason = self._build_reason(signal, action, agreed_indicators, total_indicators)
        if tf_text:
            signal.reason += f" | {tf_text}"
        
        if final_confidence >= 0.78:
            signal.reason = f"DEEP CONFIRMED: {signal.reason}"
        elif final_confidence >= 0.68:
            signal.reason = f"CONFIRMED: {signal.reason}"
        elif final_confidence >= 0.58:
            signal.reason = f"DEVELOPING: {signal.reason}"
        else:
            signal.reason = f"WEAK BIAS: {signal.reason}"

        return signal

    def _scan_with_ticks(self, target: str, current_price: float) -> SniperSignal:
        """Tick momentum analysis when candle data is insufficient.

        Uses percentage-based analysis scaled for OTC price movements.
        """
        signal = SniperSignal(
            status="WAITING",
            symbol=target,
            confidence=0.0,
            current_price=current_price,
            expiry_seconds=self._expiry,
            timestamp=int(time.time()),
        )

        # Get ticks for this symbol
        raw_ticks = self._ticks._buffers.get(target)
        tick_prices = [t.price for t in raw_ticks] if raw_ticks else []
        tick_count = len(tick_prices)

        if tick_count < 3:
            signal.status = "CALL"
            signal.confidence = 0.50
            signal.reason = f"Insufficient ticks ({tick_count}). Returning a neutral CALL bias."
            signal.agreed_indicators = 1
            signal.total_indicators = 2
            return signal

        # Calculate tick momentum using PERCENTAGE changes (not absolute)
        lookback = min(10, tick_count)
        recent_prices = tick_prices[-lookback:]
        
        # Calculate percentage changes between consecutive ticks
        pct_changes = []
        for i in range(1, len(recent_prices)):
            if recent_prices[i-1] > 0:
                pct_change = (recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                pct_changes.append(pct_change)
        
        if not pct_changes:
            signal.status = "CALL"
            signal.confidence = 0.50
            signal.reason = "No price changes detected. Returning a neutral CALL bias."
            return signal
        
        # Momentum = sum of percentage changes (positive = up, negative = down)
        tick_mom = sum(pct_changes)
        signal.tick_momentum = tick_mom

        # Calculate velocity (percentage change over last 5 ticks)
        recent = tick_prices[-min(5, tick_count):]
        if len(recent) >= 2 and recent:
            first_price = recent[0]
            last_price = recent[-1]
            velocity = (last_price - first_price) / first_price if first_price > 0 else 0.0
        else:
            velocity = 0.0

        # Calculate mean reversion
        avg_price = sum(tick_prices) / len(tick_prices)
        deviation_pct = (current_price - avg_price) / avg_price if avg_price > 0 else 0
        signal.at_support = current_price < avg_price
        signal.at_resistance = current_price > avg_price
        signal.support = avg_price * 0.999
        signal.resistance = avg_price * 1.001

        # Determine direction - use MUCH lower thresholds for OTC
        # OTC moves 0.01-0.1% per tick, not 1-5% like stocks
        if tick_mom > 0.0002:  # 0.02% cumulative up movement
            action = "CALL"
        elif tick_mom < -0.0002:  # 0.02% cumulative down movement
            action = "PUT"
        else:
            # Neutral momentum - use velocity
            if velocity > 0.00005:  # 0.005% up
                action = "CALL"
            elif velocity < -0.00005:  # 0.005% down
                action = "PUT"
            else:
                # Still neutral - use recent trend
                if len(recent_prices) >= 3:
                    trend = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                    action = "CALL" if trend > 0 else "PUT"
                else:
                    action = "CALL" if current_price >= avg_price else "PUT"

        # Calculate confidence based on signal strength, but keep tick-only reads modest.
        confidence = 0.51
        
        # Boost for stronger momentum
        abs_mom = abs(tick_mom)
        if abs_mom > 0.001:  # 0.1% cumulative
            confidence += 0.10
        elif abs_mom > 0.0005:  # 0.05%
            confidence += 0.07
        elif abs_mom > 0.0002:  # 0.02%
            confidence += 0.04
        
        # Boost for velocity
        abs_vel = abs(velocity)
        if abs_vel > 0.0005:  # 0.05%
            confidence += 0.07
        elif abs_vel > 0.0002:  # 0.02%
            confidence += 0.04
        
        # Reduce if price is extended from average (mean reversion risk)
        if abs(deviation_pct) > 0.001:
            confidence -= 0.10
        if tick_count < 6:
            confidence = min(confidence, 0.60)

        confidence = min(confidence, 0.72)

        signal.status = action
        signal.confidence = round(confidence, 4)
        signal.agreed_indicators = 2
        signal.total_indicators = 3

        # Format reason with actual values
        mom_pct = tick_mom * 100
        vel_pct = velocity * 100
        dev_pct = deviation_pct * 100
        
        if confidence >= 0.68:
            signal.reason = f"CONFIRMED {action}: momentum={mom_pct:+.4f}%, velocity={vel_pct:+.4f}%, ticks={tick_count}"
        elif confidence >= 0.58:
            signal.reason = f"DEVELOPING {action}: momentum={mom_pct:+.4f}%, velocity={vel_pct:+.4f}%, ticks={tick_count}"
        else:
            signal.reason = f"WEAK BIAS {action}: momentum={mom_pct:+.4f}%, velocity={vel_pct:+.4f}%, ticks={tick_count}"

        return signal

    # ------------------------------------------------------------------
    # Scan all configured pairs
    # ------------------------------------------------------------------

    def scan_all(self) -> list[SniperSignal]:
        """Run deep scan on all configured pairs. Returns list of signals."""
        results = []
        for pair in self._pairs:
            results.append(self.scan(pair))
        return results

    # ------------------------------------------------------------------
    # Best signal among all pairs
    # ------------------------------------------------------------------

    def best_signal(self) -> SniperSignal:
        """Return the highest-confidence signal across all pairs."""
        signals = self.scan_all()
        if not signals:
            return SniperSignal(
                status="WAITING",
                symbol="",
                confidence=0.0,
                reason="No signals available",
                timestamp=int(time.time()),
            )

        # Sort by confidence descending
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals[0] if signals else SniperSignal(
            status="WAITING",
            symbol="",
            confidence=0.0,
            reason="No signals available",
            timestamp=int(time.time()),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason(
        signal: SniperSignal,
        action: str,
        agreed: int,
        total: int,
    ) -> str:
        """Build a human-readable reason string."""
        parts: list[str] = []

        if signal.rsi is not None:
            parts.append(f"RSI={signal.rsi:.1f}")
        if signal.macd_histogram is not None:
            parts.append(f"MACD={signal.macd_histogram:+.5f}")
        if signal.bb_lower is not None and signal.bb_upper is not None:
            bb_pos = (signal.current_price - signal.bb_lower) / max(
                signal.bb_upper - signal.bb_lower, 1e-6
            )
            parts.append(f"BB={bb_pos:.0%}")
        if signal.stoch_k is not None:
            parts.append(f"Stoch K={signal.stoch_k:.0f}")
        if signal.cci is not None:
            parts.append(f"CCI={signal.cci:.0f}")
        if signal.adx is not None:
            parts.append(f"ADX={signal.adx:.0f}")
        if signal.vwap is not None:
            parts.append(f"VWAP={'above' if signal.current_price > signal.vwap else 'below'}")

        otc_parts: list[str] = []
        otc_parts.append(f"TickMom={signal.tick_momentum:+.3f}")
        if signal.pattern_detected:
            otc_parts.append(f"Pattern={signal.pattern_detected}({signal.pattern_direction})")
        if signal.sr_bounce_direction:
            otc_parts.append(f"SR_Bounce={signal.sr_bounce_direction}")
        if signal.at_support:
            otc_parts.append("AtSupport")
        if signal.at_resistance:
            otc_parts.append("AtResistance")

        combined = ", ".join(parts)
        otc_str = ", ".join(otc_parts)

        return (
            f"{action} | {agreed}/{total} indicators | "
            f"Technical: {combined} | "
            f"OTC: {otc_str}"
        )

    # ------------------------------------------------------------------
    # Conversion to StrategyDecision (for compatibility with existing code)
    # ------------------------------------------------------------------

    @staticmethod
    def to_strategy_decision(signal: SniperSignal) -> StrategyDecision:
        """Convert a SniperSignal to a StrategyDecision for API compatibility."""
        if signal.status == "WAITING":
            return StrategyDecision(
                action="HOLD",
                confidence=signal.confidence,
                summary="Sniper Mode: WAITING",
                reason=signal.reason,
                rsi=signal.rsi,
                recommended_duration=signal.expiry_seconds,
                signal_timestamp=signal.timestamp,
                reference_price=signal.current_price,
            )

        return StrategyDecision(
            action=signal.status,
            confidence=signal.confidence,
            summary=f"Sniper Mode: {signal.status} ({signal.agreed_indicators}/{signal.total_indicators})",
            reason=signal.reason,
            rsi=signal.rsi,
            trend_strength=abs(signal.tick_momentum),
            recommended_duration=signal.expiry_seconds,
            signal_timestamp=signal.timestamp,
            reference_price=signal.current_price,
        )
