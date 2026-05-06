"""Professional chart renderer using ONLY PIL/Pillow -- no matplotlib.

Produces dark-theme candlestick PNGs that match the Quotex platform style:
  - Green/red candles with visible wicks
  - Direction box (CALL=green / PUT=red) in the top-left
  - Date centred at the top  (e.g. "April 9")
  - Symbol + time + timeframe in the top-right  (e.g. "USD/ARS 19:50:25 M1")
  - Price labels on the right axis
  - Time labels along the bottom
  - Large semi-transparent "ETERNAL AI BOT" watermark in the centre
  - Subtle horizontal grid lines

Public API
----------
render_signal_chart(...) -> str
    Full chart with signal overlays.

capture_chart_image(...) -> str
    Quick chart-only image (no signal box).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from eternal_quotex_bot.models import Candle
from eternal_quotex_bot.paths import runtime_dir

# ---------------------------------------------------------------------------
# Colour palette  (dark trading theme matching Quotex style)
# ---------------------------------------------------------------------------
BG_PRIMARY    = (13, 17, 23)       # #0d1117  page background
BG_SECONDARY  = (22, 27, 34)       # #161b22  chart area
BG_TOPBAR     = (19, 23, 30)       # slightly lighter bar behind header text
GRID_COLOR    = (33, 38, 45)       # #21262d  subtle grid lines
TEXT_PRIMARY  = (201, 209, 217)    # #c9d1d9
TEXT_SECONDARY= (139, 148, 158)    # #8b949e
TEXT_BRIGHT   = (240, 246, 252)    # #f0f6fc
TEXT_WHITE    = (255, 255, 255)

CANDLE_GREEN  = (0, 200, 100)      # bullish body
CANDLE_RED    = (230, 50, 60)      # bearish body
WICK_GREEN    = (0, 238, 130)      # bullish wick (slightly brighter)
WICK_RED      = (255, 70, 80)      # bearish wick

CALL_GREEN    = (0, 180, 90)       # top-left box for CALL
PUT_RED       = (210, 40, 55)      # top-left box for PUT

EMA_COLORS    = [
    (0, 204, 255),                 # cyan  EMA 5
    (255, 153, 0),                 # orange EMA 13
    (153, 102, 255),               # purple EMA 21
]
ENTRY_COLOR   = (255, 204, 0)      # dashed entry line

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
CHART_W = 1200
CHART_H = 675

MARGIN_LEFT   = 10
MARGIN_RIGHT  = 85     # room for price labels on the right
MARGIN_TOP    = 55     # room for header bar
MARGIN_BOTTOM = 45     # room for time labels

HEADER_H      = 38     # pixel height of the header strip

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return the best available TrueType font, cached."""
    key = ("bold" if bold else "normal", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    preferred_bold = ["seguisb.ttf", "arialbd.ttf", "calibrib.ttf"]
    preferred_normal = ["segoeui.ttf", "arial.ttf", "calibri.ttf"]
    preferred = preferred_bold if bold else preferred_normal

    font_dirs: list[str] = []
    windir = os.environ.get("WINDIR", "")
    if windir:
        font_dirs.append(os.path.join(windir, "Fonts"))
    font_dirs.extend(["/usr/share/fonts/truetype", "/usr/share/fonts"])

    for font_dir in font_dirs:
        if not os.path.isdir(font_dir):
            continue
        for fname in preferred:
            fpath = os.path.join(font_dir, fname)
            if os.path.isfile(fpath):
                try:
                    font = ImageFont.truetype(fpath, size)
                    _FONT_CACHE[key] = font
                    return font
                except (IOError, OSError):
                    continue

    fallback = ImageFont.load_default()
    _FONT_CACHE[key] = fallback
    return fallback


def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) of *text* drawn at (0, 0)."""
    return draw.textbbox((0, 0), text, font=font)


def _text_wh(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bb = _text_bbox(draw, text, font)
    return bb[2] - bb[0], bb[3] - bb[1]


# ---------------------------------------------------------------------------
# EMA helper
# ---------------------------------------------------------------------------

def _compute_ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append((v - out[-1]) * k + out[-1])
    return out


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _round_rect(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int,
                fill: tuple[int, ...], radius: int = 8) -> None:
    """Rounded rectangle via overlapping rectangle + corner ellipses."""
    # Ensure RGBA for alpha support
    if len(fill) == 3:
        fill = (*fill, 255)
    # central cross (covers everything except corners)
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    # four corner quarters
    draw.pieslice([x1, y1, x1 + 2 * radius, y1 + 2 * radius], 180, 270, fill=fill)
    draw.pieslice([x2 - 2 * radius, y1, x2, y1 + 2 * radius], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - 2 * radius, x1 + 2 * radius, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - 2 * radius, y2 - 2 * radius, x2, y2], 0, 90, fill=fill)


def _draw_centered_text(draw: ImageDraw.ImageDraw, text: str,
                        cx: int, cy: int, fill: tuple[int, ...], font) -> None:
    w, h = _text_wh(draw, text, font)
    draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)


def _dashed_line(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int,
                 fill: tuple[int, ...], width: int = 1,
                 dash: int = 6, gap: int = 4) -> None:
    x = x1
    while x < x2:
        end = min(x + dash, x2)
        draw.line([(x, y), (end, y)], fill=fill, width=width)
        x = end + gap


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_signal_chart(
    candles: list[Candle],
    signal_action: str = "HOLD",
    confidence: float = 0.0,
    symbol: str = "",
    entry_price: float | None = None,
    ema_fast: list[float] | None = None,
    ema_slow: list[float] | None = None,
    ema_periods: list[int] | None = None,
    ema_colors: list[tuple[int, ...]] | None = None,
    output_path: str | Path | None = None,
    width: int = CHART_W,
    height: int = CHART_H,
    timeframe_label: str = "M1",
) -> str:
    """Render a professional candlestick chart with optional signal overlays.

    Returns the absolute path to the saved PNG.
    """

    # ---- ensure we have enough candles -----------------------------------
    if not candles or len(candles) < 2:
        candles = [
            Candle(timestamp=int(datetime.now(timezone.utc).timestamp()) - 120,
                    open=100.0, high=101.0, low=99.5, close=100.3),
            Candle(timestamp=int(datetime.now(timezone.utc).timestamp()) - 60,
                    open=100.3, high=101.5, low=99.8, close=101.0),
        ]

    candles = list(candles[-120:])          # keep at most 120
    n = len(candles)

    if ema_periods is None:
        ema_periods = [5, 13, 21]
    if ema_colors is None:
        ema_colors = list(EMA_COLORS)
    if entry_price is None:
        entry_price = candles[-1].close

    # ---- layout rects ----------------------------------------------------
    hdr_top   = 0
    hdr_bottom = HEADER_H
    chart_top  = MARGIN_TOP
    chart_bottom = height - MARGIN_BOTTOM
    chart_left = MARGIN_LEFT
    chart_right = width - MARGIN_RIGHT
    chart_w    = chart_right - chart_left
    chart_h    = chart_bottom - chart_top

    # ---- create image ----------------------------------------------------
    img = Image.new("RGBA", (width, height), (*BG_PRIMARY, 255))
    draw = ImageDraw.Draw(img)

    # header strip
    draw.rectangle([0, hdr_top, width, hdr_bottom], fill=(*BG_TOPBAR, 255))

    # chart area
    draw.rectangle([chart_left, chart_top, chart_right, chart_bottom], fill=(*BG_SECONDARY, 255))

    # ---- price range -----------------------------------------------------
    p_high = max(c.high for c in candles)
    p_low  = min(c.low  for c in candles)
    prange = p_high - p_low or 1e-6
    pad = prange * 0.06
    pmin = p_low - pad
    pmax = p_high + pad

    def _y(price: float) -> int:
        return chart_top + int(chart_h * (1.0 - (price - pmin) / (pmax - pmin)))

    def _x(idx: int) -> int:
        if n <= 1:
            return chart_left + chart_w // 2
        return chart_left + int((idx / (n - 1)) * chart_w)

    # ---- fonts -----------------------------------------------------------
    f_tiny   = _get_font(8)
    f_small  = _get_font(9)
    f_norm   = _get_font(11)
    f_med    = _get_font(13)
    f_big    = _get_font(16)
    f_water  = _get_font(52, bold=True)

    # ---- grid lines + right-axis price labels ----------------------------
    n_grid = 8
    step = (pmax - pmin) / n_grid
    for i in range(n_grid + 1):
        price = pmin + i * step
        yy = _y(price)
        # subtle horizontal grid
        draw.line([(chart_left, yy), (chart_right, yy)], fill=GRID_COLOR, width=1)
        # price label on the right
        if abs(price) >= 1000:
            lbl = f"{price:.1f}"
        elif abs(price) >= 1:
            lbl = f"{price:.4f}"
        else:
            lbl = f"{price:.5f}"
        draw.text((chart_right + 6, yy - 6), lbl, fill=TEXT_SECONDARY, font=f_small)

    # subtle vertical lines
    v_step = max(1, n // 6)
    for i in range(0, n, v_step):
        xx = _x(i)
        draw.line([(xx, chart_top), (xx, chart_bottom)], fill=GRID_COLOR, width=1)

    # ---- candlesticks ----------------------------------------------------
    spacing = max(4, chart_w // n)
    body_w  = max(2, int(spacing * 0.6))

    for i, c in enumerate(candles):
        xx = _x(i)
        bullish = c.close >= c.open
        # _y() inverts: higher price => smaller Y (higher on screen)
        # body_top must be the smaller Y (higher price), body_bot the larger Y (lower price)
        y_open  = _y(c.open)
        y_close = _y(c.close)
        body_top  = min(y_open, y_close)
        body_bot  = max(y_open, y_close)
        high_y    = _y(c.high)
        low_y     = _y(c.low)

        wick_col  = WICK_GREEN if bullish else WICK_RED
        body_col  = CANDLE_GREEN if bullish else CANDLE_RED

        # wick line from high to low
        draw.line([(xx, high_y), (xx, low_y)], fill=wick_col, width=1)

        # body rectangle -- guarantee at least 1 pixel tall
        if body_bot - body_top < 1:
            body_bot = body_top + 1
        hw = body_w // 2
        draw.rectangle([xx - hw, body_top, xx + hw, body_bot], fill=body_col)

    # ---- EMA lines -------------------------------------------------------
    closes = [c.close for c in candles]
    ema_map: dict[int, list[float]] = {}
    for idx, period in enumerate(ema_periods):
        if idx == 0 and ema_fast and len(ema_fast) == n:
            ema_map[period] = ema_fast
        elif idx == 1 and ema_slow and len(ema_slow) == n:
            ema_map[period] = ema_slow
        else:
            ema_map[period] = _compute_ema(closes, period)

    for idx, period in enumerate(ema_periods):
        vals = ema_map.get(period)
        if not vals or len(vals) != n:
            continue
        col = ema_colors[idx] if idx < len(ema_colors) else TEXT_SECONDARY
        for j in range(1, n):
            draw.line([(_x(j-1), _y(vals[j-1])), (_x(j), _y(vals[j]))], fill=col, width=2)

    # EMA legend (inside chart, upper-right)
    ema_labels = []
    for idx, period in enumerate(ema_periods):
        if ema_map.get(period):
            ema_labels.append((f"EMA{period}", ema_colors[idx] if idx < len(ema_colors) else TEXT_SECONDARY))
    if ema_labels:
        lx = chart_right - 10
        ly = chart_top + 6
        max_lw = max(_text_wh(draw, lab, f_tiny)[0] for lab, _ in ema_labels)
        bw = max_lw + 38
        bh = len(ema_labels) * 14 + 6
        draw.rectangle([lx - bw, ly, lx, ly + bh], fill=(26, 26, 26, 240))
        for k, (lab, col) in enumerate(ema_labels):
            yy = ly + 3 + k * 14
            draw.rectangle([lx - bw + 5, yy + 2, lx - bw + 18, yy + 9], fill=col)
            draw.text((lx - bw + 22, yy), lab, fill=TEXT_SECONDARY, font=f_tiny)

    # ---- entry price dashed line -----------------------------------------
    ey = _y(entry_price)
    if chart_top <= ey <= chart_bottom:
        _dashed_line(draw, chart_left, ey, chart_right, fill=ENTRY_COLOR, width=2)
        lbl = f"Entry {entry_price:.4f}"
        lw, lh = _text_wh(draw, lbl, f_tiny)
        lx = chart_right - lw - 8
        ly = ey - lh - 6
        draw.rectangle([lx - 3, ly - 2, lx + lw + 3, ly + lh + 2], fill=(28, 28, 28, 240))
        draw.text((lx, ly), lbl, fill=ENTRY_COLOR, font=f_tiny)

    # ---- header text -----------------------------------------------------
    # Date at top centre  (e.g. "April 9")
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %-d") if os.name != "nt" else now.strftime("%B %#d")
    _draw_centered_text(draw, date_str, width // 2, HEADER_H // 2 + 1, TEXT_BRIGHT, f_big)

    # Symbol + time + timeframe at top-right
    time_str = now.strftime("%H:%M:%S")
    sym_display = symbol.replace("_otc", "").upper() if symbol else ""
    # Try to make it look like "USD/ARS"
    if "/" not in sym_display and len(sym_display) >= 6:
        sym_display = sym_display[:3] + "/" + sym_display[3:]
    header_right_text = f"{sym_display}  {time_str}  {timeframe_label}"
    hr_w, hr_h = _text_wh(draw, header_right_text, f_med)
    draw.text((chart_right - hr_w - 10, HEADER_H // 2 - hr_h // 2 + 1),
              header_right_text, fill=TEXT_PRIMARY, font=f_med)

    # ---- direction box  (top-left, outside chart area in header) ---------
    if signal_action in ("CALL", "PUT"):
        is_call = signal_action == "CALL"
        box_col = CALL_GREEN if is_call else PUT_RED
        box_x, box_y = 10, 6
        box_w, box_h = 148, 44

        _round_rect(draw, box_x, box_y, box_x + box_w, box_y + box_h, box_col, radius=8)
        _draw_centered_text(draw, signal_action,
                            box_x + box_w // 2, box_y + 15, TEXT_WHITE, f_med)
        _draw_centered_text(draw, f"{confidence:.0f}% Confidence",
                            box_x + box_w // 2, box_y + 33, TEXT_WHITE, f_small)

    # ---- watermark  (centre of chart, semi-transparent) ------------------
    wm_text = "ETERNAL AI BOT"
    wm_w, wm_h = _text_wh(draw, wm_text, f_water)
    wm_x = (chart_left + chart_right) // 2 - wm_w // 2
    wm_y = (chart_top + chart_bottom) // 2 - wm_h // 2
    # Use a temporary RGBA overlay for semi-transparency
    wm_overlay = Image.new("RGBA", (wm_w + 20, wm_h + 10), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(wm_overlay)
    wm_draw.rounded_rectangle([0, 0, wm_w + 19, wm_h + 9], radius=12, fill=(20, 25, 35, 100))
    wm_draw.text((10, 5), wm_text, fill=(60, 70, 85, 120), font=f_water)
    img.paste(wm_overlay, (wm_x - 10, wm_y - 5), wm_overlay)

    # ---- time labels along bottom ----------------------------------------
    t_step = max(1, n // 7)
    for i in range(0, n, t_step):
        c = candles[i]
        dt = datetime.fromtimestamp(c.timestamp, tz=timezone.utc) if isinstance(c.timestamp, (int, float)) else datetime.now(timezone.utc)
        lbl = dt.strftime("%H:%M")
        lw, lh = _text_wh(draw, lbl, f_small)
        draw.text((_x(i) - lw // 2, chart_bottom + 6), lbl, fill=TEXT_SECONDARY, font=f_small)

    # ---- save ------------------------------------------------------------
    if output_path is None:
        reports = runtime_dir() / "telegram_reports"
        reports.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(prefix="chart_", suffix=".png",
                                           dir=str(reports), delete=False)
        output_path = tmp.name
        tmp.close()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Convert to RGB for clean PNG save
    img_rgb = img.convert("RGB")
    img_rgb.save(str(out), "PNG", optimize=True)

    return str(out.resolve())


def capture_chart_image(
    candles: list[Candle],
    symbol: str = "",
    output_path: str | Path | None = None,
    width: int = CHART_W,
    height: int = CHART_H,
    ema_periods: list[int] | None = None,
    ema_colors: list[tuple[int, ...]] | None = None,
    timeframe_label: str = "M1",
) -> str:
    """Quick chart capture without signal overlays."""
    return render_signal_chart(
        candles=candles,
        signal_action="HOLD",
        confidence=0.0,
        symbol=symbol,
        entry_price=candles[-1].close if candles else None,
        ema_fast=None,
        ema_slow=None,
        ema_periods=ema_periods,
        ema_colors=ema_colors,
        output_path=output_path,
        width=width,
        height=height,
        timeframe_label=timeframe_label,
    )
