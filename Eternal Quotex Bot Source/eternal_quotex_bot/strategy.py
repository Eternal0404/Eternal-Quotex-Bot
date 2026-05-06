from __future__ import annotations

import math
from collections import deque

from .models import Candle, StrategyDecision, StrategySettings


# ============================================================
# CORE INDICATORS
# ============================================================

def ema(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    multiplier = 2.0 / (period + 1.0)
    output = [values[0]]
    for value in values[1:]:
        output.append((value - output[-1]) * multiplier + output[-1])
    return output


def sma(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    result = [sum(values[:period]) / period]
    for i in range(period, len(values)):
        result.append(result[-1] + (values[i] - values[i - period]) / period)
    return result


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, curr in zip(closes, closes[1:]):
        delta = curr - prev
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if abs(avg_loss) < 1e-10:
        return 100.0
    for g, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + g) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if abs(avg_loss) < 1e-10:
            return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9):
    if len(closes) < slow + signal_period:
        return None, None, None
    ema_fast_vals = ema(closes, fast)
    ema_slow_vals = ema(closes, slow)
    offset = slow - fast
    macd_line = [f - s for f, s in zip(ema_fast_vals[offset:], ema_slow_vals)]
    if len(macd_line) < signal_period:
        return None, None, None
    signal_line = ema(macd_line, signal_period)
    histogram = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
    return macd_line[-1], signal_line[-1], histogram[-1]


def bollinger_bands(closes: list[float], period: int = 20, std_mult: float = 2.0):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((x - middle) ** 2 for x in recent) / period
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    upper = middle + std_mult * std_dev
    lower = middle - std_mult * std_dev
    return lower, middle, upper


def stochastic(candles: list[Candle], k_period: int = 14, d_period: int = 3) -> tuple[float, float] | None:
    if len(candles) < k_period + 1:
        return None
    k_values: list[float] = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1:i + 1]
        if not window:
            continue
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        rng = highest - lowest
        if abs(rng) < 1e-10:
            k_values.append(50.0)
        else:
            k_values.append(((candles[i].close - lowest) / rng) * 100.0)
    if len(k_values) < d_period:
        return None
    k = sum(k_values[-d_period:]) / d_period
    d_vals = []
    for j in range(d_period - 1, len(k_values)):
        start = max(0, j - d_period + 1)
        d_vals.append(sum(k_values[start:j + 1]) / (j - start + 1))
    d = d_vals[-1] if d_vals else k
    return k, d


def williams_r(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period:
        return None
    window = candles[-period:]
    highest = max(c.high for c in window)
    lowest = min(c.low for c in window)
    rng = highest - lowest
    if abs(rng) < 1e-10:
        return -50.0
    return ((highest - candles[-1].close) / rng) * -100.0


def cci(candles: list[Candle], period: int = 20) -> float | None:
    if len(candles) < period:
        return None
    typical_prices = [(c.high + c.low + c.close) / 3.0 for c in candles[-period:]]
    mean = sum(typical_prices) / len(typical_prices)
    deviation = sum(abs(tp - mean) for tp in typical_prices) / len(typical_prices)
    if abs(deviation) < 1e-10:
        return 0.0
    current_tp = typical_prices[-1]
    return (current_tp - mean) / (0.015 * deviation)


def average_true_range(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / period


def adx(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period * 2 + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high_diff = candles[i].high - candles[i - 1].high
        low_diff = candles[i - 1].low - candles[i].low
        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0.0)
        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0.0)
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    atr = sum(true_ranges[-period:]) / period
    if atr == 0:
        return 50.0
    plus_di = (sum(plus_dm[-period:]) / atr) * 100
    minus_di = (sum(minus_dm[-period:]) / atr) * 100
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 50.0
    dx = abs(plus_di - minus_di) / di_sum * 100
    return dx


def vwap(candles: list[Candle]) -> float | None:
    if not candles:
        return None
    cum_vol_price = 0.0
    cum_vol = 0.0
    for c in candles[-60:]:
        vol = max(c.volume, 1.0)
        tp = (c.high + c.low + c.close) / 3.0
        cum_vol_price += tp * vol
        cum_vol += vol
    if cum_vol == 0:
        return None
    return cum_vol_price / cum_vol


def momentum_score(candles: list[Candle], lookback: int = 5) -> float:
    if len(candles) < lookback + 1:
        return 0.0
    closes = [c.close for c in candles[-(lookback + 1):]]
    up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    down_count = len(closes) - 1 - up_count
    total = max(1, up_count + down_count)
    return (up_count - down_count) / total


def linear_regression_slope(closes: list[float], period: int = 20) -> float | None:
    if len(closes) < period:
        return None
    recent = closes[-period:]
    x_mean = (period - 1) / 2.0
    y_mean = sum(recent) / period
    numerator = sum((i - x_mean) * (recent[i] - y_mean) for i in range(period))
    denominator = sum((i - x_mean) ** 2 for i in range(period))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _signal_basis_candles(candles: list[Candle], minimum: int) -> list[Candle]:
    if len(candles) > minimum + 1:
        return candles[:-1]
    return candles


# ============================================================
# MULTI-INDICATOR FUSION ENGINE
# ============================================================

def evaluate_signal(candles: list[Candle], settings: StrategySettings) -> StrategyDecision:
    minimum = max(settings.slow_ema + 1, settings.rsi_period + 2)
    if len(candles) < minimum:
        return StrategyDecision(
            action="HOLD",
            confidence=0.50,
            summary="Insufficient data",
            reason=f"Only {len(candles)} candles available. Need {minimum}.",
            rsi=None,
            trend_strength=0.0,
            recommended_duration=120,
            signal_timestamp=candles[-1].timestamp if candles else 0,
            reference_price=candles[-1].close if candles else 0.0,
            ema_fast=[],
            ema_slow=[],
        )

    chart_closes = [c.close for c in candles]
    ema_fast_all = ema(chart_closes, settings.fast_ema)
    ema_slow_all = ema(chart_closes, settings.slow_ema)

    basis_candles = _signal_basis_candles(candles, minimum)
    basis_closes = [c.close for c in basis_candles]

    # Calculate all indicators
    current_rsi = rsi(basis_closes, settings.rsi_period) or 50.0
    macd_val, macd_sig, macd_hist = macd(basis_closes)
    bb_lower, bb_mid, bb_upper = bollinger_bands(basis_closes)
    stoch = stochastic(basis_candles)
    wr = williams_r(basis_candles) or -50.0
    cci_val = cci(basis_candles) or 0.0
    atr_val = average_true_range(basis_candles)
    adx_val = adx(basis_candles) or 30.0
    vwap_val = vwap(basis_candles)
    lr_slope = linear_regression_slope(basis_closes, 20) or 0.0
    momentum = momentum_score(basis_candles, 5)

    signal_candle = basis_candles[-1]
    previous_candle = basis_candles[-2] if len(basis_candles) > 1 else basis_candles[0]
    basis_index = len(basis_candles) - 1
    fast_now = ema_fast_all[basis_index] if basis_index < len(ema_fast_all) else basis_closes[-1]
    slow_now = ema_slow_all[basis_index] if basis_index < len(ema_slow_all) else basis_closes[-1]
    fast_prev = ema_fast_all[basis_index - 1] if basis_index > 0 else fast_now
    slow_prev = ema_slow_all[basis_index - 1] if basis_index > 0 else slow_now

    last_close = signal_candle.close
    previous_close = previous_candle.close
    spread = fast_now - slow_now
    fast_slope = fast_now - fast_prev
    slow_slope = slow_now - slow_prev
    range_size = max(signal_candle.high - signal_candle.low, 1e-6)
    candle_body = abs(signal_candle.close - signal_candle.open)
    body_ratio = min(1.0, candle_body / range_size)
    close_location = (signal_candle.close - signal_candle.low) / range_size

    # ================================================================
    # SCORING ENGINE: 15 indicators vote independently
    # ================================================================
    call_score = 0.0
    put_score = 0.0

    # 1. EMA Trend Direction + Crossover
    if spread > 0:
        call_score += 3.0
    elif spread < 0:
        put_score += 3.0
    if fast_slope > slow_slope:
        call_score += 2.0
    elif fast_slope < slow_slope:
        put_score += 2.0
    if fast_slope > 0 and slow_slope > 0:
        call_score += 1.0
    elif fast_slope < 0 and slow_slope < 0:
        put_score += 1.0

    # 2. RSI Position
    if current_rsi > 55:
        call_score += 2.5
    elif current_rsi > 60:
        call_score += 1.0  # bonus
    elif current_rsi < 45:
        put_score += 2.5
    elif current_rsi < 40:
        put_score += 1.0  # bonus

    # 3. MACD Signal + Histogram
    if macd_val is not None and macd_sig is not None and macd_hist is not None:
        if macd_val > macd_sig and macd_hist > 0:
            call_score += 3.0
            if macd_hist > 0.0005 * last_close:
                call_score += 1.0
        elif macd_val < macd_sig and macd_hist < 0:
            put_score += 3.0
            if macd_hist < -0.0005 * last_close:
                put_score += 1.0

    # 4. Bollinger Bands Position
    if bb_lower is not None and bb_upper is not None and bb_mid is not None:
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_pos = (last_close - bb_lower) / bb_range
            if bb_pos < 0.2:
                call_score += 3.0  # oversold bounce zone
            elif bb_pos < 0.35:
                call_score += 1.5
            elif bb_pos > 0.8:
                put_score += 3.0  # overbought reversal zone
            elif bb_pos > 0.65:
                put_score += 1.5

    # 5. Stochastic Oscillator
    if stoch is not None:
        k, d = stoch
        if k < 20 and k > d:
            call_score += 2.5  # oversold + bullish cross
        elif k < 30 and k > d:
            call_score += 1.5
        elif k > 80 and k < d:
            put_score += 2.5  # overbought + bearish cross
        elif k > 70 and k < d:
            put_score += 1.5

    # 6. Williams %R
    if wr > -20:
        put_score += 1.5  # overbought
    elif wr < -80:
        call_score += 1.5  # oversold

    # 7. CCI
    if cci_val > 100:
        put_score += 1.5  # overbought
    elif cci_val < -100:
        call_score += 1.5  # oversold
    if cci_val > 0:
        call_score += 0.5
    else:
        put_score += 0.5

    # 8. VWAP
    if vwap_val is not None:
        if last_close > vwap_val:
            call_score += 1.5
        elif last_close < vwap_val:
            put_score += 1.5

    # 9. Linear Regression Slope
    if lr_slope > 0.0001 * last_close:
        call_score += 1.5
    elif lr_slope < -0.0001 * last_close:
        put_score += 1.5

    # 10. Momentum
    if momentum > 0.2:
        call_score += 2.0 * abs(momentum)
    elif momentum < -0.2:
        put_score += 2.0 * abs(momentum)

    # 11. Candle Structure
    if signal_candle.close > signal_candle.open:
        call_score += 1.5
        if close_location > 0.7:
            call_score += 1.0
    elif signal_candle.close < signal_candle.open:
        put_score += 1.5
        if close_location < 0.3:
            put_score += 1.0

    # 12. Close vs Previous
    if last_close > previous_close:
        call_score += 1.0
    elif last_close < previous_close:
        put_score += 1.0

    # 13. ADX Trend Strength
    if adx_val > 25:
        if spread > 0:
            call_score += 1.5 * min(1.0, adx_val / 50.0)
        elif spread < 0:
            put_score += 1.5 * min(1.0, adx_val / 50.0)

    # ================================================================
    # CONFIDENCE CALCULATION
    # ================================================================
    total_score = call_score + put_score
    max_score = max(call_score, put_score)
    winner = "CALL" if call_score > put_score else "PUT"
    winner_score = call_score if call_score > put_score else put_score
    loser_score = put_score if call_score > put_score else call_score
    score_diff = abs(call_score - put_score)

    # Base confidence from dominance, with weaker optimism on mixed setups.
    if total_score > 0:
        confidence = 0.48 + (winner_score / total_score) * 0.32
    else:
        confidence = 0.51

    confidence = min(0.92, confidence + min(0.08, score_diff / 40.0))

    # Boost for strong indicators agreeing
    indicators_agreeing = 0
    if (spread > 0 and winner == "CALL") or (spread < 0 and winner == "PUT"):
        indicators_agreeing += 1
    if (current_rsi > 55 and winner == "CALL") or (current_rsi < 45 and winner == "PUT"):
        indicators_agreeing += 1
    if macd_val is not None:
        if (macd_val > macd_sig and winner == "CALL") or (macd_val < macd_sig and winner == "PUT"):
            indicators_agreeing += 1
    if bb_lower is not None and bb_upper is not None:
        bb_pos = (last_close - bb_lower) / max(bb_upper - bb_lower, 1e-6)
        if (bb_pos < 0.35 and winner == "CALL") or (bb_pos > 0.65 and winner == "PUT"):
            indicators_agreeing += 1

    confidence = min(0.92, confidence + indicators_agreeing * 0.02)

    # Cap mixed or low-quality setups so they stay labeled honestly.
    if score_diff < 2.0:
        confidence = min(confidence, 0.58)
    elif score_diff < 4.0:
        confidence = min(confidence, 0.66)
    if indicators_agreeing <= 1:
        confidence = min(confidence, 0.60)
    if adx_val < 18:
        confidence = min(confidence, 0.67)
    if body_ratio < 0.20:
        confidence = min(confidence, 0.67)

    # Keep binary trades on the 2 minute default.
    recommended_duration = 120
    preferred_expiry = int(settings.preferred_expiry_seconds or 120)
    if preferred_expiry in {60, 120, 300}:
        recommended_duration = preferred_expiry

    # ================================================================
    # DIRECTIONAL DECISION - HOLD when too mixed
    # ================================================================
    if score_diff < 1.0:
        action = "HOLD"
        confidence = 0.50
        summary = "Indicators mixed - HOLD"
        reason = "Indicator votes too evenly split."
    elif call_score > put_score:
        action = "CALL"
        parts = [f"RSI={current_rsi:.1f}"]
        if macd_val is not None and macd_hist is not None:
            parts.append(f"MACD={macd_hist:+.4f}")
        if bb_lower is not None:
            bb_pos_pct = (last_close - bb_lower) / max(bb_upper - bb_lower, 1e-6) * 100
            parts.append(f"BB pos={bb_pos_pct:.0f}%")
        if stoch:
            parts.append(f"Stoch K={stoch[0]:.0f}/D={stoch[1]:.0f}")
        parts.append(f"CCI={cci_val:.0f}")
        parts.append(f"ADX={adx_val:.0f}")
        if vwap_val is not None:
            parts.append(f"VWAP {'above' if last_close > vwap_val else 'below'}")
        parts.append(f"Momentum={momentum:+.2f}")
        reason = f"Indicators: {', '.join(parts)}."
    else:
        action = "PUT"
        parts = [f"RSI={current_rsi:.1f}"]
        if macd_val is not None and macd_hist is not None:
            parts.append(f"MACD={macd_hist:+.4f}")
        if bb_lower is not None:
            bb_pos_pct = (last_close - bb_lower) / max(bb_upper - bb_lower, 1e-6) * 100
            parts.append(f"BB pos={bb_pos_pct:.0f}%")
        if stoch:
            parts.append(f"Stoch K={stoch[0]:.0f}/D={stoch[1]:.0f}")
        parts.append(f"CCI={cci_val:.0f}")
        parts.append(f"ADX={adx_val:.0f}")
        if vwap_val is not None:
            parts.append(f"VWAP {'above' if last_close > vwap_val else 'below'}")
        parts.append(f"Momentum={momentum:+.2f}")
        reason = f"Indicators: {', '.join(parts)}."

    if confidence >= 0.78 and action != "HOLD":
        summary = f"Deep confirmed {action.lower()}"
    elif confidence >= 0.68 and action != "HOLD":
        summary = f"Confirmed {action.lower()}"
    elif confidence >= 0.58 and action != "HOLD":
        summary = f"Developing {action.lower()}"
    elif action == "HOLD":
        pass  # summary already set above
    else:
        summary = f"Weak {action.lower()} bias"

    return StrategyDecision(
        action=action,
        confidence=round(confidence, 2),
        summary=summary,
        reason=reason,
        rsi=round(current_rsi, 2),
        trend_strength=round(abs(spread) / max(abs(last_close), 1e-6), 6),
        recommended_duration=recommended_duration,
        signal_timestamp=signal_candle.timestamp,
        reference_price=signal_candle.close,
        ema_fast=ema_fast_all,
        ema_slow=ema_slow_all,
    )
