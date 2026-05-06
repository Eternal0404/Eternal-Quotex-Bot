from __future__ import annotations

from PySide6.QtCharts import QCandlestickSeries, QCandlestickSet, QChart, QChartView, QDateTimeAxis, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import QDateTime, QMargins, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy

from eternal_quotex_bot.models import Candle


class CandleChartWidget(QChartView):
    def __init__(self, *, minimum_height: int = 100) -> None:
        super().__init__()
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setRubberBand(QChartView.NoRubberBand)
        self.setInteractive(True)
        self.setViewportUpdateMode(QChartView.BoundingRectViewportUpdate)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("background: transparent; border: 0;")
        self._last_signature = None
        self._chart = None
        self._axis_x = None
        self._axis_y = None
        self._candle_series = None
        self._candle_sets: list[QCandlestickSet] = []
        self._guide_series = None
        self._set_empty_chart()

    def _ensure_chart(self) -> QChart:
        if self._chart is not None and self._axis_x is not None and self._axis_y is not None:
            return self._chart
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setBackgroundBrush(QColor("#08111f"))
        chart.setPlotAreaBackgroundVisible(True)
        chart.setPlotAreaBackgroundBrush(QColor("#17233d"))
        chart.legend().hide()
        chart.setTitle("")
        chart.setTitleBrush(QColor("#d7e5fb"))
        chart.setMargins(QMargins(8, 8, 58, 22))
        chart.setBackgroundRoundness(0)
        chart.setAnimationOptions(QChart.NoAnimation)
        chart.layout().setContentsMargins(0, 0, 0, 0)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("HH:mm")
        axis_x.setTickCount(6)
        axis_x.setLabelsColor(QColor("#8da3c8"))
        axis_x.setGridLineColor(QColor(76, 96, 140, 54))
        axis_x.setLinePen(QPen(QColor("#20314b"), 1))

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.5f")
        axis_y.setLabelsColor(QColor("#a6bbda"))
        axis_y.setGridLineColor(QColor(76, 96, 140, 58))
        axis_y.setLinePen(QPen(QColor("#20314b"), 1))
        axis_y.setTickCount(7)

        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignRight)
        self._chart = chart
        self._axis_x = axis_x
        self._axis_y = axis_y
        self.setChart(chart)
        return chart

    def _attach_series(self, series) -> None:
        chart = self._ensure_chart()
        chart.addSeries(series)
        series.attachAxis(self._axis_x)
        series.attachAxis(self._axis_y)

    def _reset_base_series(self) -> None:
        chart = self._ensure_chart()
        for series in (self._candle_series, self._guide_series):
            if series is not None:
                chart.removeSeries(series)
        self._candle_series = None
        self._candle_sets = []
        self._guide_series = None

    def _guide_values(self, candles: list[Candle], ema_fast: list[float] | None, ema_slow: list[float] | None) -> list[float] | None:
        guide_values = ema_slow if ema_slow and len(ema_slow) == len(candles) else ema_fast
        if guide_values and len(guide_values) == len(candles):
            return list(guide_values)
        return None

    def _update_axes(self, candles: list[Candle]) -> None:
        if not candles:
            return
        minimum = min(candle.low for candle in candles)
        maximum = max(candle.high for candle in candles)
        padding = max((maximum - minimum) * 0.05, 0.0001)
        if maximum >= 1000:
            self._axis_y.setLabelFormat("%.2f")
        elif maximum >= 10:
            self._axis_y.setLabelFormat("%.3f")
        else:
            self._axis_y.setLabelFormat("%.5f")
        self._axis_y.setRange(minimum - padding, maximum + padding)
        self._axis_x.setTickCount(min(10, max(5, len(candles) // 12 + 2)))
        if not candles:
            return
        start_ms = candles[0].timestamp * 1000
        end_ms = candles[-1].timestamp * 1000
        span_ms = max(60_000, end_ms - start_ms)
        pad_ms = max(2_000, int(span_ms * 0.03))
        self._axis_x.setRange(
            QDateTime.fromMSecsSinceEpoch(start_ms - pad_ms),
            QDateTime.fromMSecsSinceEpoch(end_ms + pad_ms),
        )

    def _sync_guide_series(self, candles: list[Candle], guide_values: list[float] | None) -> None:
        chart = self._ensure_chart()
        if not guide_values:
            if self._guide_series is not None:
                chart.removeSeries(self._guide_series)
                self._guide_series = None
            return
        if self._guide_series is None:
            guide_series = QLineSeries()
            guide_series.setName("Guide")
            guide_series.setPen(QPen(QColor("#13c7ff"), 1.8))
            guide_series.setUseOpenGL(False)
            self._guide_series = guide_series
            self._attach_series(guide_series)
        self._guide_series.clear()
        for candle, value in zip(candles, guide_values):
            self._guide_series.append(candle.timestamp * 1000, value)

    def _update_existing_series(
        self,
        candles: list[Candle],
        ema_fast: list[float] | None,
        ema_slow: list[float] | None,
    ) -> bool:
        """Update existing chart data in-place to avoid a visible close/reopen flicker."""
        if self._candle_series is None or len(self._candle_sets) != len(candles):
            return False
        try:
            n = len(candles)
            self._candle_series.setBodyWidth(0.90 if n < 40 else 0.80 if n < 80 else 0.68 if n < 120 else 0.58)
            for candle_set, candle in zip(self._candle_sets, candles):
                candle_set.setOpen(candle.open)
                candle_set.setHigh(candle.high)
                candle_set.setLow(candle.low)
                candle_set.setClose(candle.close)
                candle_set.setTimestamp(candle.timestamp * 1000)
            self._sync_guide_series(candles, self._guide_values(candles, ema_fast, ema_slow))
            self._update_axes(candles)
            self._refresh()
            return True
        except Exception:
            # If Qt rejects an in-place update for this platform/version, fall back to rebuilding once.
            return False

    def _chart_signature(
        self,
        candles: list[Candle],
        ema_fast: list[float] | None,
        ema_slow: list[float] | None,
        title: str,
    ) -> tuple:
        tail = candles[-3:] if len(candles) >= 3 else candles
        tail_key = tuple(
            (
                candle.timestamp,
                round(candle.open, 8),
                round(candle.high, 8),
                round(candle.low, 8),
                round(candle.close, 8),
            )
            for candle in tail
        )
        ema_fast_key = tuple(round(value, 8) for value in (ema_fast or [])[-2:])
        ema_slow_key = tuple(round(value, 8) for value in (ema_slow or [])[-2:])
        return (title, len(candles), tail_key, ema_fast_key, ema_slow_key)

    def set_candles(
        self,
        candles: list[Candle],
        ema_fast: list[float] | None = None,
        ema_slow: list[float] | None = None,
        *,
        title: str = "",
    ) -> None:
        if not candles:
            self._set_empty_chart()
            return
        signature = self._chart_signature(candles, ema_fast, ema_slow, title)
        if signature == self._last_signature and self.chart() is not None:
            self._refresh()
            return
        self._last_signature = signature

        chart = self._ensure_chart()
        if self._update_existing_series(candles, ema_fast, ema_slow):
            return
        self._reset_base_series()

        candle_series = QCandlestickSeries()
        candle_series.setIncreasingColor(QColor("#2ee887"))
        candle_series.setDecreasingColor(QColor("#ff6b63"))
        candle_series.setBodyOutlineVisible(False)
        candle_series.setCapsVisible(False)
        n = len(candles)
        candle_series.setBodyWidth(0.90 if n < 40 else 0.80 if n < 80 else 0.68 if n < 120 else 0.58)
        candle_series.setUseOpenGL(False)
        candle_series.setName("Candles")

        self._candle_sets = []
        for candle in candles:
            candle_set = QCandlestickSet(candle.open, candle.high, candle.low, candle.close, candle.timestamp * 1000)
            self._candle_sets.append(candle_set)
            candle_series.append(candle_set)
        self._candle_series = candle_series
        self._attach_series(candle_series)

        self._sync_guide_series(candles, self._guide_values(candles, ema_fast, ema_slow))
        self._update_axes(candles)
        self._refresh()

    def _set_empty_chart(self) -> None:
        chart = self._ensure_chart()
        self._reset_base_series()
        now = QDateTime.currentDateTime()
        self._axis_x.setRange(now.addSecs(-60), now)
        self._axis_y.setLabelFormat("%.5f")
        self._axis_y.setRange(0.0, 1.0)
        self._last_signature = None
        chart.update()

    def _refresh(self) -> None:
        if self.scene():
            self.scene().update()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.chart():
            self.chart().update()

    def add_indicator_overlay(
        self,
        values: list[float],
        timestamps: list[float],
        color: str = "#ffaa00",
        width: float = 2.0,
        name: str = "Indicator",
    ) -> None:
        """Add a line overlay to the current chart from pre-computed values."""
        chart = self.chart()
        if chart is None or not values or not timestamps:
            return
        overlay = QLineSeries()
        overlay.setName(name)
        overlay.setPen(QPen(QColor(color), width))
        overlay.setUseOpenGL(False)
        for ts, val in zip(timestamps, values):
            overlay.append(ts * 1000, val)
        self._attach_series(overlay)
        self._refresh()

    def add_signal_markers(
        self,
        signals: list[dict],
    ) -> None:
        """Add BUY/SELL signal markers to the chart.

        Each signal dict should have: 'timestamp' (epoch seconds), 'price' (float), 'type' ('BUY' or 'SELL').
        """
        chart = self.chart()
        if chart is None or not signals:
            return

        for sig in signals:
            ts = sig.get("timestamp", 0) * 1000
            price = sig.get("price", 0)
            sig_type = sig.get("type", "")
            color = QColor("#00ee77") if sig_type == "BUY" else QColor("#ff2233")
            marker = QScatterSeries()
            marker.setMarkerSize(14)
            marker.setBrush(color)
            marker.setPen(QPen(QColor("#ffffff"), 2))
            marker.append(ts, price)
            marker.setName(f"{sig_type} Signal")
            self._attach_series(marker)
        self._refresh()

    def clear_overlays(self) -> None:
        """Remove all non-candlestick series from the chart (overlays and markers)."""
        chart = self.chart()
        if chart is None:
            return
        to_remove = [
            series for series in chart.series()
            if series not in {self._candle_series, self._guide_series}
        ]
        for series in to_remove:
            chart.removeSeries(series)
        self._refresh()
