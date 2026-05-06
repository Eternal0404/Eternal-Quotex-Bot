from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Candle, StrategyDecision
from .paths import runtime_dir

# ---------------------------------------------------------------------------
# Colour palette (matches Quotex dark theme)
# ---------------------------------------------------------------------------
BG_PRIMARY     = (8, 17, 32)        # page background
BG_SECONDARY   = (13, 24, 43)       # chart area
GRID_COLOR     = (28, 42, 64, 255)  # subtle grid lines
TEXT_PRIMARY   = (201, 209, 217)    # standard text
TEXT_SECONDARY = (139, 148, 158)    # muted text
TEXT_BRIGHT    = (240, 246, 252)    # bright text
TEXT_WHITE     = (255, 255, 255)

CANDLE_GREEN   = (33, 208, 122)     # bullish body
CANDLE_RED     = (255, 92, 92)      # bearish body
WICK_GREEN     = (15, 230, 90)      # bullish wick
WICK_RED       = (255, 50, 60)      # bearish wick

CALL_GREEN     = (29, 189, 108)     # direction box CALL
PUT_RED        = (227, 85, 85)      # direction box PUT

ENTRY_COLOR    = (255, 211, 87)     # entry price line

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
IMG_W = 1200
IMG_H = 675

MARGIN_LEFT   = 60
MARGIN_RIGHT  = 80
MARGIN_TOP    = 120
MARGIN_BOTTOM = 50

HEADER_H       = 50

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return the best available TrueType font, cached."""
    key = ("bold" if bold else "normal", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    # Try Windows fonts first, then system defaults
    preferred_bold = ["seguisb.ttf", "arialbd.ttf", "calibrib.ttf"]
    preferred_normal = ["segoeui.ttf", "arial.ttf", "calibri.ttf"]
    preferred = preferred_bold if bold else preferred_normal

    font_dirs: list[str] = []
    windir = os.environ.get("WINDIR", "")
    if windir:
        font_dirs.append(os.path.join(windir, "Fonts"))
    # Also try common Linux paths
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

    # Graceful fallback
    fallback = ImageFont.load_default()
    _FONT_CACHE[key] = fallback
    return fallback


def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) of *text* drawn at (0, 0)."""
    return draw.textbbox((0, 0), text, font=font)


def _text_wh(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bb = _text_bbox(draw, text, font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _draw_centered_text(draw: ImageDraw.ImageDraw, text: str,
                        cx: int, cy: int, fill: tuple[int, ...], font) -> None:
    w, h = _text_wh(draw, text, font)
    draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)


# ---------------------------------------------------------------------------
# Price / coordinate helpers
# ---------------------------------------------------------------------------

def _price_y(price: float, price_min: float, price_max: float, top: int, bottom: int) -> int:
    span = max(price_max - price_min, 1e-6)
    normalized = (price_max - price) / span
    return int(top + normalized * max(1, bottom - top))


def _candle_x(index: int, total: int, left: int, right: int) -> int:
    usable = max(1, right - left)
    if total <= 1:
        return left + usable // 2
    return int(left + (usable * index) / max(1, total - 1))


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def _draw_grid(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int) -> None:
    for step in range(6):
        y = int(top + ((bottom - top) * step / 5))
        draw.line((left, y, right, y), fill=GRID_COLOR, width=1)
    for step in range(8):
        x = int(left + ((right - left) * step / 7))
        draw.line((x, top, x, bottom), fill=GRID_COLOR, width=1)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_signal_image(
    *,
    symbol: str,
    candles: list[Candle],
    decision: StrategyDecision,
    broker_name: str = "Quotex",
    output_path: Path | None = None,
) -> Path:
    """Render a professional signal chart image with candlestick overlay.

    Returns the Path to the saved PNG.
    """
    reports_dir = runtime_dir() / "telegram_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        temp = tempfile.NamedTemporaryFile(prefix="signal_", suffix=".png", dir=str(reports_dir), delete=False)
        output_path = Path(temp.name)
        temp.close()

    # Ensure we have candles to render
    series = list(candles[-120:] or [])
    if not series:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        series = [
            Candle(timestamp=now_ts - 120, open=1.0, high=1.01, low=0.99, close=1.0),
            Candle(timestamp=now_ts - 60, open=1.0, high=1.02, low=0.995, close=1.01),
        ]

    n = len(series)

    # ---- create image (RGBA for transparency support) --------------------
    width, height = IMG_W, IMG_H
    image = Image.new("RGBA", (width, height), (*BG_PRIMARY, 255))
    draw = ImageDraw.Draw(image, "RGBA")

    # ---- fonts -----------------------------------------------------------
    title_font   = _load_font(22, bold=True)
    body_font    = _load_font(16)
    small_font   = _load_font(13)
    tiny_font    = _load_font(11)
    axis_font    = _load_font(12)
    watermark_f  = _load_font(52, bold=True)

    # ---- layout ----------------------------------------------------------
    chart_left   = MARGIN_LEFT
    chart_top    = MARGIN_TOP
    chart_right  = width - MARGIN_RIGHT
    chart_bottom = height - MARGIN_BOTTOM
    chart_w      = chart_right - chart_left
    chart_h      = chart_bottom - chart_top

    # outer frame
    draw.rounded_rectangle((10, 8, width - 10, height - 10), radius=16,
                           fill=(10, 18, 33, 255), outline=(24, 42, 68, 255), width=2)
    # chart area
    draw.rounded_rectangle((chart_left - 10, chart_top - 12, chart_right + 10, chart_bottom + 10),
                           radius=12, fill=(*BG_SECONDARY, 255), outline=(31, 52, 79, 255), width=1)
    _draw_grid(draw, chart_left, chart_top, chart_right, chart_bottom)

    # ---- signal direction box (top-left) ----------------------------------
    action = decision.action if decision.action in {"CALL", "PUT"} else "HOLD"
    conf_pct = int(round((decision.confidence or 0.0) * 100))

    if action in ("CALL", "PUT"):
        is_call = action == "CALL"
        box_fill = (*CALL_GREEN, 235) if is_call else (*PUT_RED, 235)
        box_x, box_y, box_w, box_h = 28, 18, 170, 54
        draw.rounded_rectangle((box_x, box_y, box_x + box_w, box_y + box_h),
                               radius=12, fill=box_fill)
        # "CALL" or "PUT" text
        _draw_centered_text(draw, f"{action}",
                            box_x + box_w // 2, box_y + 18, TEXT_WHITE, title_font)
        # confidence
        _draw_centered_text(draw, f"{conf_pct}%",
                            box_x + box_w // 2, box_y + 40, TEXT_WHITE, body_font)
    else:
        box_fill = (66, 120, 200, 235)
        box_x, box_y, box_w, box_h = 28, 18, 170, 54
        draw.rounded_rectangle((box_x, box_y, box_x + box_w, box_y + box_h),
                               radius=12, fill=box_fill)
        _draw_centered_text(draw, "HOLD",
                            box_x + box_w // 2, box_y + 27, TEXT_WHITE, title_font)

    # ---- date stamp (top centre) -----------------------------------------
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %-d") if os.name != "nt" else now.strftime("%B %#d")
    _draw_centered_text(draw, date_str, width // 2, HEADER_H + 4, TEXT_BRIGHT, _load_font(18, bold=True))

    # ---- symbol + timeframe + broker (top-right) -------------------------
    timeframe_min = max(1, int(decision.recommended_duration or 60) // 60)
    tf_label = f"M{timeframe_min}"
    sym_display = symbol.replace("_otc", "").upper().replace("_", "/") if symbol else "UNKNOWN"
    # Try to format as pair like "USD/ARS"
    if "/" not in sym_display and len(sym_display) >= 6:
        sym_display = sym_display[:3] + "/" + sym_display[3:]
    time_str = now.strftime("%H:%M:%S")
    header_right = f"{sym_display}  {time_str}  {tf_label}"
    hr_w, hr_h = _text_wh(draw, header_right, body_font)
    draw.text((chart_right - hr_w, HEADER_H + 2), header_right, fill=TEXT_PRIMARY, font=body_font)

    # ---- caption line under header ---------------------------------------
    caption = f"{symbol} | {broker_name} | {tf_label} | Confidence {conf_pct}%"
    draw.text((chart_left, chart_top - 28), caption, fill=TEXT_SECONDARY, font=small_font)

    # ---- price range -----------------------------------------------------
    prices_high = [float(c.high) for c in series]
    prices_low  = [float(c.low) for c in series]
    price_max = max(prices_high)
    price_min = min(prices_low)
    span = max(price_max - price_min, 1e-6)
    price_max += span * 0.06
    price_min -= span * 0.06

    def _y(price: float) -> int:
        return _price_y(price, price_min, price_max, chart_top, chart_bottom)

    # ---- candle width / spacing (prevent overlap / green blocks) ----------
    usable_width = chart_right - chart_left
    if n <= 1:
        body_w = max(6, usable_width // 8)
    else:
        spacing = usable_width // n
        body_w = max(2, int(spacing * 0.55))
        body_w = min(body_w, max(4, spacing - 3))  # always leave gap

    # ---- draw candlesticks -----------------------------------------------
    for idx, candle in enumerate(series):
        x = _candle_x(idx, n, chart_left, chart_right)

        y_high = _y(candle.high)
        y_low  = _y(candle.low)
        y_open = _y(candle.open)
        y_close = _y(candle.close)

        bullish = candle.close >= candle.open
        body_col = (*CANDLE_GREEN, 255) if bullish else (*CANDLE_RED, 255)
        wick_col = (*WICK_GREEN, 255) if bullish else (*WICK_RED, 255)

        # Wick line (high to low)
        draw.line([(x, y_high), (x, y_low)], fill=wick_col, width=1)

        # Body rectangle -- min 1 px tall
        body_top    = min(y_open, y_close)
        body_bottom = max(y_open, y_close)
        if body_bottom - body_top < 1:
            body_bottom = body_top + 1

        half_w = body_w // 2
        draw.rectangle([x - half_w, body_top, x + half_w, body_bottom], fill=body_col)

    # ---- price axis labels (right side) ----------------------------------
    n_price_labels = 8
    for i in range(n_price_labels + 1):
        price = price_min + (price_max - price_min) * i / n_price_labels
        yy = _y(price)
        if abs(price) >= 1000:
            lbl = f"{price:.1f}"
        elif abs(price) >= 1:
            lbl = f"{price:.4f}"
        else:
            lbl = f"{price:.5f}"
        lbl_w, _ = _text_wh(draw, lbl, tiny_font)
        draw.text((chart_right + 6, yy - 6), lbl, fill=TEXT_SECONDARY, font=tiny_font)

    # ---- time axis labels (bottom) ---------------------------------------
    t_step = max(1, n // 7)
    for i in range(0, n, t_step):
        c = series[i]
        dt = datetime.fromtimestamp(c.timestamp, tz=timezone.utc) if isinstance(c.timestamp, (int, float)) else now
        lbl = dt.strftime("%H:%M")
        lw, lh = _text_wh(draw, lbl, axis_font)
        draw.text((_candle_x(i, n, chart_left, chart_right) - lw // 2, chart_bottom + 8),
                  lbl, fill=TEXT_SECONDARY, font=axis_font)

    # ---- watermark (centre of chart, semi-transparent) --------------------
    wm_text = "ETERNAL AI BOT"
    wm_w, wm_h = _text_wh(draw, wm_text, watermark_f)
    wm_x = (chart_left + chart_right) // 2 - wm_w // 2
    wm_y = (chart_top + chart_bottom) // 2 - wm_h // 2
    # Semi-transparent overlay
    wm_overlay = Image.new("RGBA", (wm_w + 24, wm_h + 14), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(wm_overlay)
    wm_draw.rounded_rectangle([0, 0, wm_w + 23, wm_h + 13], radius=14, fill=(15, 22, 35, 110))
    wm_draw.text((12, 7), wm_text, fill=(55, 65, 80, 130), font=watermark_f)
    image.paste(wm_overlay, (wm_x - 12, wm_y - 7), wm_overlay)

    # ---- entry price dashed line -----------------------------------------
    entry_price = float(decision.reference_price or series[-1].close)
    entry_y = _y(entry_price)
    if chart_top <= entry_y <= chart_bottom:
        # Draw dashed line
        dash_len, gap_len = 8, 5
        dx = chart_left
        while dx < chart_right:
            end_x = min(dx + dash_len, chart_right)
            draw.line([(dx, entry_y), (end_x, entry_y)], fill=(*ENTRY_COLOR, 200), width=2)
            dx = end_x + gap_len
        # Label
        entry_lbl = f"Entry {entry_price:.5f}"
        elw, elh = _text_wh(draw, entry_lbl, tiny_font)
        elx = chart_right - elw - 8
        ely = entry_y - elh - 6
        draw.rounded_rectangle((elx - 4, ely - 2, elx + elw + 4, ely + elh + 2),
                               radius=6, fill=(18, 28, 48, 235))
        draw.text((elx, ely), entry_lbl, fill=(*ENTRY_COLOR, 255), font=tiny_font)

    # ---- latest price badge ----------------------------------------------
    latest_price = float(series[-1].close)
    latest_y = _y(latest_price)
    if chart_top <= latest_y <= chart_bottom:
        price_fill = (*CALL_GREEN, 230) if action == "CALL" else (*PUT_RED, 230) if action == "PUT" else (69, 120, 198, 230)
        price_lbl = f"{latest_price:.5f}"
        plw, plh = _text_wh(draw, price_lbl, small_font)
        px = chart_right + 2
        py = latest_y - plh // 2 - 4
        draw.rounded_rectangle((px, py, px + plw + 10, py + plh + 8),
                               radius=8, fill=price_fill)
        draw.text((px + 5, py + 4), price_lbl, fill=TEXT_WHITE, font=small_font)

    # ---- reason text (bottom) --------------------------------------------
    reason_text = decision.reason or decision.summary or "Waiting for a cleaner setup."
    draw.text((chart_left, chart_bottom + 28), reason_text[:150], fill=TEXT_SECONDARY, font=small_font)

    # ---- save ------------------------------------------------------------
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rgb = image.convert("RGB")
    rgb.save(str(out), "PNG", optimize=True)
    return out


def build_boxed_caption(*, title: str, symbol: str, decision: StrategyDecision, broker_name: str, owner: str = "Eternal AI Bot") -> str:
    action_icon = "\U0001F7E2" if decision.action == "CALL" else "\U0001F534" if decision.action == "PUT" else "\U0001F7E1"
    confidence_pct = int(round((decision.confidence or 0.0) * 100))
    expiry = max(1, int(decision.recommended_duration or 60) // 60)
    lines = [
        f"\u250c\u2500 {title}",
        f"\u2502 Broker: {broker_name}",
        f"\u2502 Asset: {symbol}",
        f"\u2502 Signal: {action_icon} {decision.action}",
        f"\u2502 Confidence: {confidence_pct}%",
        f"\u2502 Expiry: {expiry}m",
        f"\u2502 Owner: {owner}",
        "\u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\u2502 {decision.summary}",
        f"\u2502 {decision.reason}",
        "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
    ]
    return "\n".join(lines)
