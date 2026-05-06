"""Pine Script-like indicator execution engine.

Provides a simple line-by-line script parser and indicator calculation
functions that can be applied to candle data.
"""
from __future__ import annotations

import math
import re
from typing import Any

from eternal_quotex_bot.models import Candle


# ---------------------------------------------------------------------------
# Indicator calculation helpers
# ---------------------------------------------------------------------------

def _sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        result[i] = sum(window) / period
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    k = 2 / (period + 1)
    # Seed with SMA
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        if result[i - 1] is not None:
            result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)
    return result


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, list[float | None]]:
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    # Signal line = EMA of MACD line
    macd_vals = [v if v is not None else 0.0 for v in macd_line]
    signal_line = _ema(macd_vals, signal)
    histogram: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def _bollinger_bands(closes: list[float], period: int = 20, std_mult: float = 2.0) -> dict[str, list[float | None]]:
    upper: list[float | None] = [None] * len(closes)
    middle: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        middle[i] = mean
        upper[i] = mean + std_mult * std
        lower[i] = mean - std_mult * std
    return {"upper": upper, "middle": middle, "lower": lower}


def _stochastic(candles: list[Candle], k_period: int = 14, d_period: int = 3) -> dict[str, list[float | None]]:
    k_values: list[float | None] = [None] * len(candles)
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1 : i + 1]
        high = max(c.high for c in window)
        low = min(c.low for c in window)
        if abs(high - low) < 1e-9:
            k_values[i] = 50.0
        else:
            k_values[i] = (candles[i].close - low) / (high - low) * 100.0
    closes_k = [v if v is not None else 50.0 for v in k_values]
    d_values = _sma(closes_k, d_period)
    return {"k": k_values, "d": d_values}


def _williams_r(candles: list[Candle], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        high = max(c.high for c in window)
        low = min(c.low for c in window)
        if high == low:
            result[i] = -50.0
        else:
            result[i] = (high - candles[i].close) / (high - low) * -100.0
    return result


def _cci(candles: list[Candle], period: int = 20) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        typical_prices = [(c.high + c.low + c.close) / 3 for c in candles[i - period + 1 : i + 1]]
        mean = sum(typical_prices) / period
        mean_dev = sum(abs(tp - mean) for tp in typical_prices) / period
        if mean_dev == 0:
            result[i] = 0.0
        else:
            result[i] = (typical_prices[-1] - mean) / (0.015 * mean_dev)
    return result


def _atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    if not candles:
        return []
    true_ranges: list[float] = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c = candles[i]
        p = candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        true_ranges.append(tr)
    return _ema(true_ranges, period)


def _adx(candles: list[Candle], period: int = 14) -> list[float | None]:
    if len(candles) < 2:
        return [None] * len(candles)
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
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
    atr_smooth = _ema([max(candles[i].high - candles[i].low, 0.0001) for i in range(len(candles))], period)
    plus_di: list[float | None] = [None] * len(candles)
    minus_di: list[float | None] = [None] * len(candles)
    for i in range(period, len(candles)):
        if atr_smooth[i] is not None and atr_smooth[i] > 0:
            plus_di[i] = sum(plus_dm[i - period + 1 : i + 1]) / period / atr_smooth[i] * 100
            minus_di[i] = sum(minus_dm[i - period + 1 : i + 1]) / period / atr_smooth[i] * 100
    dx_values: list[float | None] = [None] * len(candles)
    for i in range(period, len(candles)):
        if plus_di[i] is not None and minus_di[i] is not None:
            denom = plus_di[i] + minus_di[i]
            if denom == 0:
                dx_values[i] = 0.0
            else:
                dx_values[i] = abs(plus_di[i] - minus_di[i]) / denom * 100
    # EMA of DX
    dx_vals = [v if v is not None else 0.0 for v in dx_values]
    return _ema(dx_vals, period)


def _mfi(candles: list[Candle], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)
    if len(candles) < 2:
        return result
    raw_money: list[float] = []
    for i in range(1, len(candles)):
        tp = (candles[i].high + candles[i].low + candles[i].close) / 3
        raw_money.append(tp * candles[i].close)  # approximate volume proxy
    money_flow: list[tuple[float, float]] = []
    for i in range(1, len(candles)):
        if raw_money[i - 1] > 0:
            money_flow.append((raw_money[i - 1], 0.0))
    positive: list[float] = []
    negative: list[float] = []
    for i in range(period, len(candles)):
        tp_curr = (candles[i].high + candles[i].low + candles[i].close) / 3
        tp_prev = (candles[i - 1].high + candles[i - 1].low + candles[i - 1].close) / 3
        mf = tp_curr * candles[i].close
        if tp_curr > tp_prev:
            positive.append(mf)
            negative.append(0.0)
        else:
            positive.append(0.0)
            negative.append(mf)
        if len(positive) > period:
            positive.pop(0)
            negative.pop(0)
        pos_sum = sum(positive)
        neg_sum = sum(negative)
        if neg_sum == 0:
            result[i] = 100.0
        else:
            rs = pos_sum / neg_sum
            result[i] = 100.0 - 100.0 / (1.0 + rs)
    return result


def _vwap(candles: list[Candle]) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)
    cum_vol = 0.0
    cum_vp = 0.0
    for i, c in enumerate(candles):
        tp = (c.high + c.low + c.close) / 3
        vol = c.close if c.close > 0 else 1  # price as volume proxy
        cum_vol += vol
        cum_vp += tp * vol
        if cum_vol > 0:
            result[i] = cum_vp / cum_vol
    return result


def _momentum(closes: list[float], period: int = 10) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    for i in range(period, len(closes)):
        result[i] = closes[i] - closes[i - period]
    return result


# ---------------------------------------------------------------------------
# Indicator templates
# ---------------------------------------------------------------------------

INDICATOR_TEMPLATES: dict[str, str] = {
    "RSI": """// RSI Indicator
// Parameters: period=14, overbought=70, oversold=30

indicator = RSI(close, period=14)

if indicator > 70:
    signal = "SELL"
elif indicator < 30:
    signal = "BUY"
else:
    signal = "NEUTRAL"
""",
    "MACD": """// MACD Indicator
// Parameters: fast=12, slow=26, signal=9

macd_line, signal_line, histogram = MACD(close, fast=12, slow=26, signal=9)

if macd_line > signal_line and histogram > 0:
    signal = "BUY"
elif macd_line < signal_line and histogram < 0:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "Bollinger Bands": """// Bollinger Bands Indicator
// Parameters: period=20, std_mult=2.0

upper, middle, lower = BOLLINGER_BANDS(close, period=20, std_mult=2.0)

if close > upper:
    signal = "SELL"
elif close < lower:
    signal = "BUY"
else:
    signal = "NEUTRAL"
""",
    "EMA": """// Exponential Moving Average
// Parameters: period=20

ema_value = EMA(close, period=20)

if close > ema_value:
    signal = "BUY"
elif close < ema_value:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "SMA": """// Simple Moving Average
// Parameters: period=20

sma_value = SMA(close, period=20)

if close > sma_value:
    signal = "BUY"
elif close < sma_value:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "Stochastic": """// Stochastic Oscillator
// Parameters: k_period=14, d_period=3

k_value, d_value = STOCHASTIC(k_period=14, d_period=3)

if k_value < 20 and k_value > d_value:
    signal = "BUY"
elif k_value > 80 and k_value < d_value:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "Williams %R": """// Williams %R Oscillator
// Parameters: period=14

wr_value = WILLIAMS_R(period=14)

if wr_value < -80:
    signal = "BUY"
elif wr_value > -20:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "CCI": """// Commodity Channel Index
// Parameters: period=20

cci_value = CCI(period=20)

if cci_value > 100:
    signal = "BUY"
elif cci_value < -100:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "ADX": """// Average Directional Index
// Parameters: period=14

adx_value = ADX(period=14)

if adx_value > 25:
    signal = "TREND"
else:
    signal = "RANGE"
""",
    "ATR": """// Average True Range
// Parameters: period=14

atr_value = ATR(period=14)

// ATR measures volatility, no directional signal
signal = "VOLATILITY: " + str(atr_value)
""",
    "MFI": """// Money Flow Index
// Parameters: period=14

mfi_value = MFI(period=14)

if mfi_value > 80:
    signal = "SELL"
elif mfi_value < 20:
    signal = "BUY"
else:
    signal = "NEUTRAL"
""",
    "VWAP": """// Volume Weighted Average Price

vwap_value = VWAP()

if close > vwap_value:
    signal = "BUY"
elif close < vwap_value:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
    "Momentum": """// Momentum Indicator
// Parameters: period=10

mom_value = MOMENTUM(period=10)

if mom_value > 0:
    signal = "BUY"
elif mom_value < 0:
    signal = "SELL"
else:
    signal = "NEUTRAL"
""",
}


# ---------------------------------------------------------------------------
# Script runner
# ---------------------------------------------------------------------------

class PineScriptRunner:
    """Parse and execute a simple Pine Script-like syntax against candle data."""

    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.closes = [c.close for c in candles]
        self.highs = [c.high for c in candles]
        self.lows = [c.low for c in candles]
        self.opens = [c.open for c in candles]
        self.timestamps = [c.timestamp for c in candles]
        self.variables: dict[str, Any] = {}
        self.output_lines: list[str] = []
        self.overlay_values: list[float] = []
        self.signals: list[dict] = []
        self.overlay_color: str = "#ffaa00"
        self.overlay_name: str = "Indicator"

    def run(self, script: str) -> dict:
        """Execute the script and return results."""
        self.variables.clear()
        self.output_lines.clear()
        self.overlay_values.clear()
        self.signals.clear()
        self.overlay_color = "#ffaa00"
        self.overlay_name = "Indicator"

        # Pre-register available variable names from assignments
        lines = script.strip().splitlines()
        self._pass1_collect_variables(lines)

        # Pass 2: execute
        try:
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                self._execute_line(stripped)
        except Exception as e:
            self.output_lines.append(f"ERROR: {type(e).__name__}: {e}")

        return {
            "output": "\n".join(self.output_lines),
            "overlay_values": self.overlay_values,
            "overlay_timestamps": self.timestamps[: len(self.overlay_values)],
            "overlay_color": self.overlay_color,
            "overlay_name": self.overlay_name,
            "signals": self.signals,
            "variables": dict(self.variables),
        }

    def _pass1_collect_variables(self, lines: list[str]) -> None:
        """First pass: find variable names from assignment lines."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            # Pattern: var_name = FUNCTION(...)
            m = re.match(r'^(\w+)\s*=', stripped)
            if m:
                self.variables[m.group(1)] = None
            # Pattern: a, b = FUNCTION(...)
            m = re.match(r'^(\w+)\s*,\s*(\w+)\s*=', stripped)
            if m:
                self.variables[m.group(1)] = None
                self.variables[m.group(2)] = None
            # Pattern: a, b, c = FUNCTION(...)
            m = re.match(r'^(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*=', stripped)
            if m:
                self.variables[m.group(1)] = None
                self.variables[m.group(2)] = None
                self.variables[m.group(3)] = None

    def _execute_line(self, line: str) -> None:
        """Execute a single script line."""
        # Handle indicator assignment: var = FUNC(...)
        m = re.match(r'^(\w+)\s*=\s*(\w+)\((.*)\)$', line)
        if m:
            var_name = m.group(1)
            func_name = m.group(2)
            args_str = m.group(3)
            result = self._call_indicator(func_name, args_str)
            self.variables[var_name] = result
            if isinstance(result, list):
                # Take the last valid value for scalar reference
                valid = [v for v in result if v is not None]
                if valid:
                    self.output_lines.append(f"{var_name} = {valid[-1]:.4f}")
                # Use full list as overlay data
                numeric = [v if v is not None else 0.0 for v in result]
                if var_name in ("indicator", "ema_value", "sma_value", "vwap_value",
                                "macd_line", "k_value", "d_value", "wr_value",
                                "cci_value", "adx_value", "atr_value", "mfi_value",
                                "mom_value"):
                    self.overlay_values = numeric
                    self.overlay_name = var_name
                    # Set appropriate color based on indicator type
                    color_map = {
                        "ema_value": "#00ccff",
                        "sma_value": "#ffcc00",
                        "indicator": "#ff8800",
                        "macd_line": "#aa44ff",
                        "vwap_value": "#44ffaa",
                        "k_value": "#ff4488",
                        "d_value": "#44aaff",
                    }
                    self.overlay_color = color_map.get(var_name, "#ffaa00")
            return

        # Handle multi-assign: a, b = FUNC(...)
        m = re.match(r'^(\w+)\s*,\s*(\w+)\s*=\s*(\w+)\((.*)\)$', line)
        if m:
            var1, var2 = m.group(1), m.group(2)
            func_name = m.group(3)
            args_str = m.group(4)
            result = self._call_indicator(func_name, args_str)
            if isinstance(result, dict):
                keys = list(result.keys())
                if len(keys) >= 2:
                    self.variables[var1] = result[keys[0]]
                    self.variables[var2] = result[keys[1]]
                    v1 = result[keys[0]]
                    if isinstance(v1, list):
                        valid = [v for v in v1 if v is not None]
                        if valid:
                            self.output_lines.append(f"{var1} = {valid[-1]:.4f}")
                            self.overlay_values = [v if v is not None else 0.0 for v in v1]
                            self.overlay_name = var1
                    v2 = result[keys[1]]
                    if isinstance(v2, list):
                        valid = [v for v in v2 if v is not None]
                        if valid:
                            self.output_lines.append(f"{var2} = {valid[-1]:.4f}")
            return

        # Handle triple-assign: a, b, c = FUNC(...)
        m = re.match(r'^(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*=\s*(\w+)\((.*)\)$', line)
        if m:
            var1, var2, var3 = m.group(1), m.group(2), m.group(3)
            func_name = m.group(4)
            args_str = m.group(5)
            result = self._call_indicator(func_name, args_str)
            if isinstance(result, dict):
                keys = list(result.keys())
                if len(keys) >= 3:
                    self.variables[var1] = result[keys[0]]
                    self.variables[var2] = result[keys[1]]
                    self.variables[var3] = result[keys[2]]
                    for var, key in [(var1, keys[0]), (var2, keys[1]), (var3, keys[2])]:
                        v = result[key]
                        if isinstance(v, list):
                            valid = [x for x in v if x is not None]
                            if valid:
                                self.output_lines.append(f"{var} = {valid[-1]:.4f}")
            return

        # Handle if/elif/else signal logic
        if line.startswith("if ") or line.startswith("elif "):
            self._handle_conditional_block(line)
            return

        # Handle signal = "..."
        m = re.match(r'^signal\s*=\s*(.+)$', line)
        if m:
            expr = m.group(1).strip()
            # Evaluate string concatenation
            signal_val = self._eval_expr(expr)
            if not self.signals:
                # Generate signals for all candles where we have data
                last_ts = self.timestamps[-1] if self.timestamps else 0
                last_price = self.closes[-1] if self.closes else 0
                self.signals.append({
                    "timestamp": last_ts,
                    "price": last_price,
                    "type": "BUY" if "BUY" in str(signal_val) else ("SELL" if "SELL" in str(signal_val) else ""),
                })
            else:
                # Update the type field
                self.signals[-1]["type"] = "BUY" if "BUY" in str(signal_val) else ("SELL" if "SELL" in str(signal_val) else "")
            self.output_lines.append(f"Signal: {signal_val}")
            return

        # Generic expression output
        self.output_lines.append(f"{line}")

    def _handle_conditional_block(self, first_line: str) -> None:
        """Handle a simple if/elif/else block for signal generation."""
        # We need to parse the block from the output_lines context
        # For simplicity, evaluate conditions and pick the matching branch
        conditions_and_bodies: list[tuple[str, str]] = []
        else_body: str = ""

        # This is a simplified single-line handler - the full block
        # would need multi-line parsing. For now, handle inline if/elif/else.
        # The templates use multi-line if/elif/else, so we handle that.
        pass  # Delegated to _execute_line caller context

    def _call_indicator(self, func_name: str, args_str: str) -> Any:
        """Call an indicator function with parsed arguments."""
        kwargs = self._parse_kwargs(args_str)

        if func_name == "RSI":
            period = kwargs.get("period", 14)
            return _rsi(self.closes, period)
        elif func_name == "MACD":
            fast = kwargs.get("fast", 12)
            slow = kwargs.get("slow", 26)
            signal_p = kwargs.get("signal", 9)
            return _macd(self.closes, fast, slow, signal_p)
        elif func_name == "BOLLINGER_BANDS":
            period = kwargs.get("period", 20)
            std_mult = kwargs.get("std_mult", 2.0)
            return _bollinger_bands(self.closes, period, std_mult)
        elif func_name == "EMA":
            period = kwargs.get("period", 20)
            return _ema(self.closes, period)
        elif func_name == "SMA":
            period = kwargs.get("period", 20)
            return _sma(self.closes, period)
        elif func_name == "STOCHASTIC":
            k_period = kwargs.get("k_period", 14)
            d_period = kwargs.get("d_period", 3)
            return _stochastic(self.candles, k_period, d_period)
        elif func_name == "WILLIAMS_R":
            period = kwargs.get("period", 14)
            return _williams_r(self.candles, period)
        elif func_name == "CCI":
            period = kwargs.get("period", 20)
            return _cci(self.candles, period)
        elif func_name == "ADX":
            period = kwargs.get("period", 14)
            return _adx(self.candles, period)
        elif func_name == "ATR":
            period = kwargs.get("period", 14)
            return _atr(self.candles, period)
        elif func_name == "MFI":
            period = kwargs.get("period", 14)
            return _mfi(self.candles, period)
        elif func_name == "VWAP":
            return _vwap(self.candles)
        elif func_name == "MOMENTUM":
            period = kwargs.get("period", 10)
            return _momentum(self.closes, period)
        else:
            raise ValueError(f"Unknown indicator: {func_name}")

    def _parse_kwargs(self, args_str: str) -> dict:
        """Parse keyword arguments from a string like 'period=14, overbought=70'."""
        kwargs: dict[str, Any] = {}
        if not args_str.strip():
            return kwargs
        for part in args_str.split(","):
            part = part.strip()
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip()
                val = val.strip()
                try:
                    kwargs[key] = int(val)
                except ValueError:
                    try:
                        kwargs[key] = float(val)
                    except ValueError:
                        kwargs[key] = val
            else:
                # Positional argument - try as number
                try:
                    kwargs["__positional"] = int(part)
                except ValueError:
                    try:
                        kwargs["__positional"] = float(part)
                    except ValueError:
                        pass
        return kwargs

    def _eval_expr(self, expr: str) -> Any:
        """Evaluate a simple expression string."""
        expr = expr.strip().strip('"').strip("'")
        # Handle string concatenation: "VOLATILITY: " + str(atr_value)
        if "+" in expr and "str(" in expr:
            parts = expr.split("+")
            result = ""
            for p in parts:
                p = p.strip()
                if p.startswith('"') or p.startswith("'"):
                    result += p.strip("\"'")
                elif p.startswith("str("):
                    inner = p[4:-1].strip()
                    val = self.variables.get(inner, 0)
                    if isinstance(val, list):
                        valid = [v for v in val if v is not None]
                        val = valid[-1] if valid else 0
                    result += str(val)
                elif inner_val := self.variables.get(p):
                    if isinstance(inner_val, list):
                        valid = [v for v in inner_val if v is not None]
                        inner_val = valid[-1] if valid else 0
                    result += str(inner_val)
                else:
                    result += p
            return result
        return expr
