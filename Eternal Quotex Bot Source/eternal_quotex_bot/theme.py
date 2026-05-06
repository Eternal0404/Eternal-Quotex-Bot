from __future__ import annotations

from PySide6.QtGui import QFont


STYLESHEET = """
QMainWindow, QWidget#appRoot, QWidget#pageSurface {
    background: #07111e;
}
QWidget {
    color: #e6eefc;
    font-size: 12px;
    background: transparent;
}
QLabel, QCheckBox {
    background: transparent;
}
QScrollArea#pageScroll {
    background: transparent;
    border: 0;
}
QFrame#card, QFrame#headerSurface, QFrame#tabStrip, QFrame#toolbarSurface {
    background: #0d1830;
    border: 1px solid rgba(80, 116, 170, 0.34);
    border-radius: 20px;
}
QFrame#headerSurface {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a162b, stop:1 #102140);
}
QFrame#lineSurface, QFrame#metricTile {
    background: #0a1323;
    border: 1px solid rgba(68, 101, 154, 0.32);
    border-radius: 16px;
}
QChartView, QGraphicsView {
    background: #07101d;
    border: 1px solid rgba(75, 112, 172, 0.22);
    border-radius: 18px;
}
QLabel#heroTitle {
    font-size: 24px;
    font-weight: 700;
    color: #f8fbff;
}
QLabel#heroSub {
    color: #9cb6dd;
    font-size: 12px;
}
QLabel#cardTitle {
    font-size: 16px;
    font-weight: 650;
    color: #f5f9ff;
}
QLabel#metricLabel {
    color: #89a4cf;
    font-size: 11px;
}
QLabel#metricValue {
    font-size: 18px;
    font-weight: 700;
    color: #f7fbff;
}
QLabel#helperText {
    color: #9ab0d3;
    font-size: 12px;
}
QLabel#toolbarLabel {
    color: #abd8ff;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusGood {
    color: #45e0a1;
    font-weight: 700;
}
QLabel#statusWarn {
    color: #ffcf69;
    font-weight: 700;
}
QLabel#statusBad {
    color: #ff897b;
    font-weight: 700;
}
QLabel#signalCall {
    color: #20d77d;
    font-weight: 700;
}
QLabel#signalPut {
    color: #ff8c5a;
    font-weight: 700;
}
QLabel#signalHold {
    color: #8eaad5;
    font-weight: 700;
}
QPushButton {
    border-radius: 13px;
    border: 1px solid rgba(92, 138, 215, 0.24);
    background: #112143;
    color: #edf5ff;
    padding: 10px 15px;
    font-weight: 600;
}
QPushButton:hover {
    background: #17305d;
}
QPushButton:pressed {
    background: #0f2447;
}
QPushButton:disabled {
    background: rgba(14, 24, 42, 0.9);
    color: #7387aa;
}
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e9fff, stop:1 #66d2ff);
    color: #04131f;
    border-color: #58cfff;
}
QPushButton#primaryButton:hover {
    background: #57c7ff;
}
QPushButton#engineButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff9f3f, stop:1 #ffc35d);
    color: #301500;
    border-color: #ffc05b;
    padding: 9px 18px;
    font-weight: 700;
}
QPushButton#toolbarButton {
    background: #239cf1;
    color: #f8fbff;
    border-color: #43b7ff;
    padding: 8px 16px;
}
QPushButton#toolbarButton:hover {
    background: #39aeff;
}
QPushButton#tabButton {
    background: #0f1b34;
    border: 1px solid rgba(73, 106, 165, 0.42);
    border-radius: 14px;
    padding: 12px 20px;
    min-width: 86px;
}
QPushButton#tabButton:checked {
    background: #15284f;
    border-color: #2da9ff;
    color: #fefefe;
}
QPushButton#buyButton {
    background: #1fbc6c;
    color: #04130c;
    border-color: #1fbc6c;
}
QPushButton#sellButton {
    background: #ff7d47;
    color: #1f0a02;
    border-color: #ff7d47;
}
QPushButton#ghostButton {
    background: rgba(14, 27, 48, 0.94);
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 36px;
    background: #081222;
    color: #eef4ff;
    border: 1px solid rgba(100, 137, 196, 0.28);
    border-radius: 12px;
    padding: 6px 10px;
    selection-background-color: rgba(39, 176, 255, 0.34);
    selection-color: #fdfefe;
}
QTextEdit, QPlainTextEdit {
    background: #081222;
    color: #eef4ff;
    border: 1px solid rgba(100, 137, 196, 0.28);
    border-radius: 12px;
    padding: 8px 10px;
    selection-background-color: rgba(39, 176, 255, 0.34);
    selection-color: #fdfefe;
}
QLineEdit::placeholder {
    color: #60779d;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #7489aa;
    background: rgba(7, 15, 27, 0.72);
}
QComboBox::drop-down {
    border: 0;
    width: 26px;
}
QComboBox QAbstractItemView {
    background: #0b1222;
    color: #ecf4ff;
    border: 1px solid rgba(102, 138, 198, 0.24);
}
QHeaderView::section {
    background: #132543;
    color: #dceaff;
    padding: 9px;
    border: 0;
}
QTableWidget {
    background: #081222;
    gridline-color: transparent;
    border: 1px solid rgba(100, 137, 196, 0.22);
    border-radius: 18px;
    alternate-background-color: rgba(14, 27, 49, 0.84);
}
QListWidget {
    background: #081222;
    border: 1px solid rgba(100, 137, 196, 0.22);
    border-radius: 18px;
    padding: 6px;
    alternate-background-color: rgba(14, 27, 49, 0.84);
}
QTableWidget::item {
    padding: 9px 10px;
    border-bottom: 1px solid rgba(137, 168, 219, 0.08);
}
QListWidget::item {
    padding: 10px 12px;
    margin: 2px 0;
    border-radius: 10px;
    border: 1px solid transparent;
}
QTableWidget::item:selected {
    background: rgba(39, 176, 255, 0.22);
    color: #f8fbff;
}
QListWidget::item:selected {
    background: rgba(39, 176, 255, 0.22);
    color: #f8fbff;
    border-color: rgba(79, 183, 255, 0.45);
}
QCheckBox {
    spacing: 8px;
    color: #dce7f8;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: rgba(88, 126, 186, 0.55);
    border-radius: 5px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: rgba(88, 126, 186, 0.55);
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: 0;
    background: none;
}
QSplitter::handle {
    background: rgba(121, 166, 235, 0.08);
    border-radius: 4px;
}
QChartView {
    background: transparent;
    border: 0;
}
"""


def apply_theme(app) -> None:
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
