from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .models import Candle, StrategyDecision


@dataclass(slots=True)
class ApexVoteResult:
    decision: StrategyDecision
    votes: dict[str, str]


def _as_dataframe(candles: list[Candle]) -> pd.DataFrame:
    # Validate candle data before creating DataFrame
    valid_candles = [
        c for c in candles
        if c is not None and 
           isinstance(c.open, (int, float)) and 
           isinstance(c.high, (int, float)) and 
           isinstance(c.low, (int, float)) and 
           isinstance(c.close, (int, float)) and
           c.open > 0 and c.high > 0 and c.low > 0 and c.close > 0
    ]
    if len(valid_candles) < 30:
        return pd.DataFrame()  # Return empty DataFrame if not enough valid data
    
    rows = [
        {
            "timestamp": int(candle.timestamp),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": float(candle.volume),
        }
        for candle in valid_candles
    ]
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    frame = frame.set_index("timestamp")
    return frame


def _rsi_calc(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _macd_calc(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = series.ewm(span=12, adjust=False).mean()
    slow = series.ewm(span=26, adjust=False).mean()
    macd_line = fast - slow
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    return macd_line, signal, histogram


def _bbands_calc(series: pd.Series, length: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(length).mean()
    std = series.rolling(length).std(ddof=0)
    upper = mid + (std * 2)
    lower = mid - (std * 2)
    return lower, mid, upper


def _stoch_calc(frame: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> tuple[float, float]:
    lows = frame["low"].rolling(k_period).min()
    highs = frame["high"].rolling(k_period).max()
    rng = highs - lows
    k_raw = ((frame["close"] - lows) / rng.replace(0, pd.NA)) * 100
    k = k_raw.rolling(d_period).mean()
    d = k.rolling(d_period).mean()
    k_val = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50.0
    d_val = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50.0
    return k_val, d_val


def _atr_calc(frame: pd.DataFrame, period: int = 14) -> float:
    high = frame["high"]
    low = frame["low"]
    prev_close = frame["close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0


def _williams_r_calc(frame: pd.DataFrame, period: int = 14) -> float:
    lows = frame["low"].rolling(period).min()
    highs = frame["high"].rolling(period).max()
    rng = highs - lows
    wr = ((highs - frame["close"]) / rng.replace(0, pd.NA)) * -100
    return float(wr.iloc[-1]) if not pd.isna(wr.iloc[-1]) else -50.0


def _cci_calc(frame: pd.DataFrame, period: int = 20) -> float:
    tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    mean = tp.rolling(period).mean()
    md = tp.rolling(period).apply(lambda x: abs(x - x.mean()).mean(), raw=False)
    cci = (tp - mean) / (0.015 * md.replace(0, pd.NA))
    return float(cci.iloc[-1]) if not pd.isna(cci.iloc[-1]) else 0.0


def _vwap_calc(frame: pd.DataFrame) -> float:
    tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    vol = frame["volume"].clip(lower=1.0)
    cum_vp = (tp * vol).cumsum()
    cum_vol = vol.cumsum()
    vwap = cum_vp / cum_vol
    return float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else float(frame["close"].iloc[-1])


def _momentum_calc(closes: pd.Series, lookback: int = 5) -> float:
    if len(closes) < lookback + 1:
        return 0.0
    recent = closes.iloc[-(lookback + 1):]
    up = sum(1 for i in range(1, len(recent)) if recent.iloc[i] > recent.iloc[i - 1])
    down = len(recent) - 1 - up
    total = max(1, up + down)
    return (up - down) / total


def _adx_calc(frame: pd.DataFrame, period: int = 14) -> float:
    high = frame["high"]
    low = frame["low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = frame["close"].shift(1)
    plus_dm = ((high - prev_high).clip(lower=0)).where(high - prev_high > prev_low - low, 0)
    minus_dm = ((prev_low - low).clip(lower=0)).where(prev_low - low > high - prev_high, 0)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = (plus_dm.rolling(period).sum() / atr.replace(0, pd.NA)) * 100
    minus_di = (minus_dm.rolling(period).sum() / atr.replace(0, pd.NA)) * 100
    di_sum = plus_di + minus_di
    dx = ((plus_di - minus_di).abs() / di_sum.replace(0, pd.NA)) * 100
    return float(dx.iloc[-1]) if not pd.isna(dx.iloc[-1]) else 30.0


def evaluate_apex_signal(candles: list[Candle]) -> ApexVoteResult:
    minimum = 60
    if not candles:
        return ApexVoteResult(
            decision=StrategyDecision(
                action="HOLD",
                confidence=0.50,
                summary="Apex Engine: no candles",
                reason="Empty candle list provided.",
            ),
            votes={},
        )
    if len(candles) < minimum:
        if not candles:
            return ApexVoteResult(
                decision=StrategyDecision(
                    action="HOLD",
                    confidence=0.50,
                    summary="Apex Engine: no candles",
                    reason="Empty candle list.",
                ),
                votes={},
            )
        return ApexVoteResult(
            decision=StrategyDecision(
                action="CALL" if candles[-1].close > candles[0].close else "PUT",
                confidence=0.55,
                summary="Apex Engine limited data",
                reason=f"Only {len(candles)} candles. Using price direction bias.",
            ),
            votes={},
        )

    basis = candles[:-1] if len(candles) > minimum else candles
    signal_candle = basis[-1]
    frame = _as_dataframe(basis)
    
    # Validate DataFrame has valid numeric data
    if frame.empty or "close" not in frame.columns:
        return ApexVoteResult(
            decision=StrategyDecision(
                action="CALL" if signal_candle.close > signal_candle.open else "PUT",
                confidence=0.52,
                summary="Apex Engine: insufficient valid data",
                reason="Pair has no valid candle data. Using basic candle direction.",
            ),
            votes={},
        )
    
    # Verify close column has numeric data
    if not pd.api.types.is_numeric_dtype(frame["close"]):
        return ApexVoteResult(
            decision=StrategyDecision(
                action="CALL" if signal_candle.close > signal_candle.open else "PUT",
                confidence=0.52,
                summary="Apex Engine: non-numeric candle data",
                reason="Candle data contains non-numeric values. Using basic candle direction.",
            ),
            votes={},
        )
    
    close = frame["close"]

    # Calculate all 12 indicators
    rsi_series = _rsi_calc(close, period=14)
    lower, mid, upper = _bbands_calc(close, length=20)
    macd_line, macd_signal, macd_hist = _macd_calc(close)
    k_val, d_val = _stoch_calc(frame)
    atr_val = _atr_calc(frame)
    wr_val = _williams_r_calc(frame)
    cci_val = _cci_calc(frame)
    vwap_val = _vwap_calc(frame)
    momentum = _momentum_calc(close, 5)
    adx_val = _adx_calc(frame)

    ema_fast = close.ewm(span=20, adjust=False).mean()
    ema_slow = close.ewm(span=50, adjust=False).mean()

    current_rsi = float(rsi_series.iloc[-1])
    lower_band = float(lower.iloc[-1])
    middle_band = float(mid.iloc[-1])
    upper_band = float(upper.iloc[-1])
    macd_value = float(macd_line.iloc[-1])
    macd_signal_value = float(macd_signal.iloc[-1])
    macd_hist_value = float(macd_hist.iloc[-1])
    ema_fast_value = float(ema_fast.iloc[-1])
    ema_slow_value = float(ema_slow.iloc[-1])

    range_size = max(signal_candle.high - signal_candle.low, 1e-6)
    body = signal_candle.close - signal_candle.open
    body_ratio = min(1.0, abs(body) / range_size)
    close_location = (signal_candle.close - signal_candle.low) / range_size
    band_span = max(upper_band - lower_band, 1e-6)
    band_position = (signal_candle.close - lower_band) / band_span

    # ================================================================
    # APEX VOTING: 12 indicators, weighted voting
    # ================================================================
    votes: dict[str, str] = {}
    call_votes = 0
    put_votes = 0

    # 1. RSI (weight: 2)
    if current_rsi > 55:
        votes["RSI"] = "CALL"
        call_votes += 2
    elif current_rsi < 45:
        votes["RSI"] = "PUT"
        put_votes += 2
    else:
        votes["RSI"] = "HOLD"

    # 2. Bollinger Bands (weight: 2)
    if band_position < 0.25:
        votes["Bollinger"] = "CALL"
        call_votes += 2
    elif band_position > 0.75:
        votes["Bollinger"] = "PUT"
        put_votes += 2
    else:
        votes["Bollinger"] = "HOLD"

    # 3. MACD (weight: 3)
    if macd_value > macd_signal_value and macd_hist_value > 0:
        votes["MACD"] = "CALL"
        call_votes += 3
    elif macd_value < macd_signal_value and macd_hist_value < 0:
        votes["MACD"] = "PUT"
        put_votes += 3
    else:
        votes["MACD"] = "HOLD"

    # 4. EMA Trend (weight: 2)
    if ema_fast_value > ema_slow_value:
        votes["EMA Trend"] = "CALL"
        call_votes += 2
    elif ema_fast_value < ema_slow_value:
        votes["EMA Trend"] = "PUT"
        put_votes += 2
    else:
        votes["EMA Trend"] = "HOLD"

    # 5. Stochastic (weight: 2)
    if k_val < 30 and k_val > d_val:
        votes["Stochastic"] = "CALL"
        call_votes += 2
    elif k_val > 70 and k_val < d_val:
        votes["Stochastic"] = "PUT"
        put_votes += 2
    else:
        votes["Stochastic"] = "HOLD"

    # 6. Williams %R (weight: 1.5)
    if wr_val < -80:
        votes["Williams %R"] = "CALL"
        call_votes += 1.5
    elif wr_val > -20:
        votes["Williams %R"] = "PUT"
        put_votes += 1.5
    else:
        votes["Williams %R"] = "HOLD"

    # 7. CCI (weight: 1.5)
    if cci_val < -100:
        votes["CCI"] = "CALL"
        call_votes += 1.5
    elif cci_val > 100:
        votes["CCI"] = "PUT"
        put_votes += 1.5
    else:
        votes["CCI"] = "HOLD"

    # 8. VWAP (weight: 1.5)
    if signal_candle.close > vwap_val:
        votes["VWAP"] = "CALL"
        call_votes += 1.5
    elif signal_candle.close < vwap_val:
        votes["VWAP"] = "PUT"
        put_votes += 1.5
    else:
        votes["VWAP"] = "HOLD"

    # 9. Momentum (weight: 1.5)
    if momentum > 0.2:
        votes["Momentum"] = "CALL"
        call_votes += 1.5
    elif momentum < -0.2:
        votes["Momentum"] = "PUT"
        put_votes += 1.5
    else:
        votes["Momentum"] = "HOLD"

    # 10. Candle Structure (weight: 1.5)
    if body > 0 and close_location > 0.55 and body_ratio >= 0.15:
        votes["Candle"] = "CALL"
        call_votes += 1.5
    elif body < 0 and close_location < 0.45 and body_ratio >= 0.15:
        votes["Candle"] = "PUT"
        put_votes += 1.5
    else:
        votes["Candle"] = "HOLD"

    # 11. ADX Trend Strength (weight: 1)
    if adx_val > 25:
        if ema_fast_value > ema_slow_value:
            votes["ADX"] = "CALL"
            call_votes += 1
        else:
            votes["ADX"] = "PUT"
            put_votes += 1
    else:
        votes["ADX"] = "HOLD"

    # 12. ATR Volatility (weight: 0.5 bonus)
    if atr_val > 0:
        atr_pct = atr_val / signal_candle.close
        if atr_pct > 0.005:
            if call_votes > put_votes:
                call_votes += 0.5
            elif put_votes > call_votes:
                put_votes += 0.5

    # ================================================================
    # CONFIDENCE CALCULATION
    # ================================================================
    total_weight = 18.5  # max possible
    confidence = min(
        0.96,
        0.40
        + max(call_votes, put_votes) / total_weight * 0.50
        + min(abs(current_rsi - 50) / 100.0, 0.10)
        + min(abs(macd_hist_value) / max(abs(signal_candle.close), 1e-6) * 500, 0.08)
        + body_ratio * 0.06
        + abs(momentum) * 0.04,
    )

    # Recommended duration
    recommended_duration = 120
    if max(call_votes, put_votes) >= 8 and body_ratio >= 0.25:
        recommended_duration = 60
    if confidence >= 0.70 and adx_val > 25:
        recommended_duration = 60

    # ALWAYS RETURN DIRECTIONAL
    if call_votes > put_votes:
        action = "CALL"
        summary = f"Apex CALL consensus ({call_votes:.1f}/{total_weight})"
        reason = (
            f"RSI={current_rsi:.1f}, BB pos={band_position:.2f}, MACD hist={macd_hist_value:.5f}, "
            f"EMA20/50 {'bullish' if ema_fast_value > ema_slow_value else 'bearish'}, "
            f"Stoch K={k_val:.1f}/D={d_val:.1f}, Momentum={momentum:.2f}, "
            f"CCI={cci_val:.0f}, WR={wr_val:.0f}, ADX={adx_val:.0f}, ATR={atr_val:.4f}."
        )
    else:
        action = "PUT"
        summary = f"Apex PUT consensus ({put_votes:.1f}/{total_weight})"
        reason = (
            f"RSI={current_rsi:.1f}, BB pos={band_position:.2f}, MACD hist={macd_hist_value:.5f}, "
            f"EMA20/50 {'bullish' if ema_fast_value > ema_slow_value else 'bearish'}, "
            f"Stoch K={k_val:.1f}/D={d_val:.1f}, Momentum={momentum:.2f}, "
            f"CCI={cci_val:.0f}, WR={wr_val:.0f}, ADX={adx_val:.0f}, ATR={atr_val:.4f}."
        )

    decision = StrategyDecision(
        action=action,
        confidence=round(confidence, 2),
        summary=summary,
        reason=reason,
        rsi=round(current_rsi, 2),
        trend_strength=round(abs(ema_fast_value - ema_slow_value) / max(abs(signal_candle.close), 1e-6), 6),
        recommended_duration=recommended_duration,
        signal_timestamp=signal_candle.timestamp,
        reference_price=signal_candle.close,
    )

    return ApexVoteResult(decision=decision, votes=votes)
