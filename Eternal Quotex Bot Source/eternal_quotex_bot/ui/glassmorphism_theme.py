"""
Eternal Quotex Bot - Glassmorphism Theme Engine
Modern professional UI with glassmorphism effects, smooth animations,
and contemporary design principles.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter
from PySide6.QtWidgets import QGraphicsDropShadowEffect


# ============================================================================
# Color Palette - Modern Dark Theme with Glass Effects
# ============================================================================

class GlassColors:
    """Professional color palette following glassmorphism design principles."""
    
    # Primary brand colors
    PRIMARY = "#6366f1"          # Indigo 500
    PRIMARY_LIGHT = "#818cf8"    # Indigo 400
    PRIMARY_DARK = "#4f46e5"     # Indigo 600
    PRIMARY_GLOW = "#6366f140"   # Indigo with 25% opacity
    
    # Accent colors
    ACCENT = "#06b6d4"           # Cyan 500
    ACCENT_LIGHT = "#22d3ee"     # Cyan 400
    ACCENT_GLOW = "#06b6d430"
    
    # Background layers
    BG_DARKEST = "#0a0a0f"       # Near black
    BG_DARK = "#0f0f17"          # Deep dark
    BG_SURFACE = "#151520"       # Card background
    BG_ELEVATED = "#1a1a2e"      # Elevated surfaces
    
    # Glass panels
    GLASS_BG = "rgba(255, 255, 255, 0.03)"
    GLASS_BORDER = "rgba(255, 255, 255, 0.08)"
    GLASS_HOVER = "rgba(255, 255, 255, 0.06)"
    
    # Text hierarchy
    TEXT_PRIMARY = "#f8fafc"     # Slate 50
    TEXT_SECONDARY = "#94a3b8"   # Slate 400
    TEXT_MUTED = "#64748b"       # Slate 500
    TEXT_DISABLED = "#475569"    # Slate 600
    
    # Status colors
    SUCCESS = "#10b981"          # Emerald 500
    SUCCESS_GLOW = "#10b98130"
    WARNING = "#f59e0b"          # Amber 500
    WARNING_GLOW = "#f59e0b30"
    ERROR = "#ef4444"            # Red 500
    ERROR_GLOW = "#ef444430"
    INFO = "#3b82f6"             # Blue 500
    INFO_GLOW = "#3b82f630"
    QUANTUM = "#d946ef"          # Fuchsia 500
    QUANTUM_GLOW = "#d946ef40"
    
    # Gradients
    GRADIENT_PRIMARY = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6366f1, stop:1 #8b5cf6)"
    GRADIENT_ACCENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #3b82f6)"
    GRADIENT_SUCCESS = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #06b6d4)"
    GRADIENT_ERROR = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #f97316)"
    GRADIENT_QUANTUM = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d946ef, stop:1 #6366f1)"


# ============================================================================
# Typography
# ============================================================================

class Typography:
    """Font hierarchy with semantic sizing."""
    
    FAMILY = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"
    MONO = "JetBrains Mono, Consolas, monospace"
    
    @staticmethod
    def heading1(size=28):
        font = QFont(Typography.FAMILY, size, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
        return font
    
    @staticmethod
    def heading2(size=22):
        font = QFont(Typography.FAMILY, size, QFont.Weight.Bold)
        return font
    
    @staticmethod
    def heading3(size=18):
        font = QFont(Typography.FAMILY, size, QFont.Weight.Medium)
        return font
    
    @staticmethod
    def body(size=14):
        return QFont(Typography.FAMILY, size, QFont.Weight.Normal)
    
    @staticmethod
    def body_small(size=13):
        return QFont(Typography.FAMILY, size, QFont.Weight.Normal)
    
    @staticmethod
    def caption(size=12):
        return QFont(Typography.FAMILY, size, QFont.Weight.Normal)
    
    @staticmethod
    def mono(size=13):
        return QFont(Typography.MONO, size, QFont.Weight.Normal)


# ============================================================================
# Spacing Scale
# ============================================================================

class Spacing:
    """8pt grid system."""
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32
    XXXL = 48


# ============================================================================
# Global Stylesheet
# ============================================================================

def get_glassmorphism_stylesheet() -> str:
    """
    Generate comprehensive QSS stylesheet with glassmorphism effects.
    This is the core styling engine for the entire application.
    """
    
    return f"""
    /* ============================================================
       ROOT APPLICATION
       ============================================================ */
    #appRoot {{
        background-color: {GlassColors.BG_DARKEST};
        border: none;
    }}
    
    QMainWindow {{
        background-color: {GlassColors.BG_DARKEST};
    }}
    
    /* ============================================================
       GLASSMORPHISM CARDS & PANELS
       ============================================================ */
    #card {{
        background-color: {GlassColors.GLASS_BG};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 12px;
        padding: 0px;
    }}
    
    #card:hover {{
        background-color: {GlassColors.GLASS_HOVER};
        border-color: rgba(255, 255, 255, 0.12);
    }}
    
    QFrame#lineSurface {{
        background-color: {GlassColors.GLASS_BG};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
    }}
    
    /* ============================================================
       TYPOGRAPHY
       ============================================================ */
    #cardTitle {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 18px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
        margin-bottom: 4px;
    }}
    
    #heroSub {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 20px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
    }}
    
    #helperText {{
        color: {GlassColors.TEXT_SECONDARY};
        font-size: 13px;
        font-family: '{Typography.FAMILY}';
        line-height: 1.5;
    }}
    
    #metricValue {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 16px;
        font-weight: 600;
        font-family: '{Typography.MONO}';
    }}
    
    /* ============================================================
       BUTTONS - Primary
       ============================================================ */
    #primaryButton {{
        background: {GlassColors.GRADIENT_PRIMARY};
        color: {GlassColors.TEXT_PRIMARY};
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
        min-height: 40px;
    }}
    
    #primaryButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 {GlassColors.PRIMARY_LIGHT}, 
                    stop:1 {GlassColors.PRIMARY});
    }}
    
    #primaryButton:pressed {{
        background: {GlassColors.PRIMARY_DARK};
    }}
    
    #primaryButton:disabled {{
        background: {GlassColors.TEXT_DISABLED};
        color: {GlassColors.TEXT_MUTED};
    }}
    
    /* ============================================================
       BUTTONS - Ghost
       ============================================================ */
    #ghostButton {{
        background-color: {GlassColors.GLASS_BG};
        color: {GlassColors.TEXT_PRIMARY};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: 500;
        font-family: '{Typography.FAMILY}';
        min-height: 40px;
    }}
    
    #ghostButton:hover {{
        background-color: {GlassColors.GLASS_HOVER};
        border-color: rgba(255, 255, 255, 0.15);
    }}
    
    #ghostButton:pressed {{
        background-color: rgba(255, 255, 255, 0.1);
    }}
    
    #ghostButton:disabled {{
        color: {GlassColors.TEXT_DISABLED};
        border-color: {GlassColors.TEXT_DISABLED};
    }}
    
    /* ============================================================
       BUTTONS - Success / Danger
       ============================================================ */
    QPushButton[variant="success"] {{
        background: {GlassColors.GRADIENT_SUCCESS};
        color: {GlassColors.TEXT_PRIMARY};
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
    }}
    
    QPushButton[variant="danger"] {{
        background: {GlassColors.GRADIENT_ERROR};
        color: {GlassColors.TEXT_PRIMARY};
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
    }}
    
    /* ============================================================
       BUTTONS - Buy/Sell (CALL/PUT)
       ============================================================ */
    QPushButton#buyButton {{
        background: {GlassColors.SUCCESS};
        color: #04130c;
        border: none;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: 700;
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        min-height: 44px;
    }}
    
    QPushButton#buyButton:hover {{
        background: #34d399;
    }}
    
    QPushButton#buyButton:pressed {{
        background: #059669;
    }}
    
    QPushButton#sellButton {{
        background: {GlassColors.ERROR};
        color: #1f0a02;
        border: none;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: 700;
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        min-height: 44px;
    }}
    
    QPushButton#sellButton:hover {{
        background: #f87171;
    }}
    
    QPushButton#sellButton:pressed {{
        background: #dc2626;
    }}
    
    /* ============================================================
       BUTTONS - Engine / Special
       ============================================================ */
    QPushButton#engineButton {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #f59e0b, stop:1 #fbbf24);
        color: #301500;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 700;
        font-family: '{Typography.FAMILY}';
        min-height: 40px;
    }}
    
    QPushButton#engineButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #fbbf24, stop:1 #f59e0b);
    }}
    
    /* ============================================================
       BUTTONS - Toolbar
       ============================================================ */
    QPushButton#toolbarButton {{
        background: {GlassColors.INFO};
        color: {GlassColors.TEXT_PRIMARY};
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: 600;
        font-family: '{Typography.FAMILY}';
        min-height: 36px;
    }}
    
    QPushButton#toolbarButton:hover {{
        background: #60a5fa;
    }}
    
    /* ============================================================
       BUTTONS - Tab Navigation
       ============================================================ */
    QPushButton#tabButton {{
        background-color: transparent;
        color: {GlassColors.TEXT_SECONDARY};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 12px 20px;
        font-size: 14px;
        font-weight: 500;
        font-family: '{Typography.FAMILY}';
        min-height: 40px;
    }}
    
    QPushButton#tabButton:hover {{
        color: {GlassColors.TEXT_PRIMARY};
        background-color: {GlassColors.GLASS_HOVER};
    }}
    
    QPushButton#tabButton:checked {{
        color: {GlassColors.TEXT_PRIMARY};
        background: {GlassColors.GRADIENT_PRIMARY};
        font-weight: 600;
    }}
    
    /* ============================================================
       LABELS - Status Colors
       ============================================================ */
    QLabel#statusGood {{
        color: {GlassColors.SUCCESS};
        font-weight: 700;
    }}
    
    QLabel#statusWarn {{
        color: {GlassColors.WARNING};
        font-weight: 700;
    }}
    
    QLabel#statusBad {{
        color: {GlassColors.ERROR};
        font-weight: 700;
    }}
    
    QLabel#signalCall {{
        color: {GlassColors.SUCCESS};
        font-weight: 700;
    }}
    
    QLabel#signalPut {{
        color: {GlassColors.ERROR};
        font-weight: 700;
    }}
    
    QLabel#signalHold {{
        color: {GlassColors.TEXT_MUTED};
        font-weight: 700;
    }}
    
    QLabel#signalQuantum {{
        color: {GlassColors.QUANTUM};
        font-weight: 800;
        text-transform: uppercase;
    }}
    
    QLabel#toolbarLabel {{
        color: {GlassColors.ACCENT_LIGHT};
        font-size: 12px;
        font-weight: 600;
    }}
    
    QLabel#metricLabel {{
        color: {GlassColors.TEXT_SECONDARY};
        font-size: 11px;
    }}
    
    /* ============================================================
       SPECIAL WIDGETS
       ============================================================ */
    QFrame#welcomeBanner {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 rgba(99, 102, 241, 0.15), 
                    stop:1 rgba(139, 92, 246, 0.08));
        border: 1px solid rgba(99, 102, 241, 0.25);
        border-radius: 16px;
        padding: 24px;
    }}
    
    QLabel#welcomeBannerTitle {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 24px;
        font-weight: 700;
        font-family: '{Typography.FAMILY}';
    }}
    
    QLabel#welcomeBannerSub {{
        color: {GlassColors.TEXT_SECONDARY};
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        line-height: 1.6;
    }}
    
    QFrame#welcomeBannerDivider {{
        background-color: {GlassColors.GLASS_BORDER};
        max-height: 1px;
        min-height: 1px;
    }}
    
    QLabel#welcomeFeature {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 13px;
        font-family: '{Typography.FAMILY}';
        padding: 4px 0px;
    }}
    
    /* Generic QPushButton styling (fallback) */
    QPushButton {{
        background-color: {GlassColors.GLASS_BG};
        color: {GlassColors.TEXT_PRIMARY};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
        font-family: '{Typography.FAMILY}';
        min-height: 32px;
    }}
    
    QPushButton:hover {{
        background-color: {GlassColors.GLASS_HOVER};
        border-color: rgba(255, 255, 255, 0.15);
    }}
    
    QPushButton:pressed {{
        background-color: rgba(255, 255, 255, 0.1);
    }}
    
    QPushButton:disabled {{
        color: {GlassColors.TEXT_DISABLED};
        border-color: {GlassColors.TEXT_DISABLED};
    }}
    
    /* ============================================================
       INPUT FIELDS
       ============================================================ */
    QLineEdit {{
        background-color: rgba(0, 0, 0, 0.3);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        padding: 10px 14px;
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        selection-background-color: {GlassColors.PRIMARY};
        min-height: 40px;
    }}
    
    QLineEdit:focus {{
        border-color: {GlassColors.PRIMARY};
        background-color: rgba(0, 0, 0, 0.4);
    }}
    
    QLineEdit:disabled {{
        background-color: rgba(0, 0, 0, 0.2);
        color: {GlassColors.TEXT_DISABLED};
        border-color: rgba(255, 255, 255, 0.03);
    }}
    
    QLineEdit[echoMode="2"] {{  /* Password fields */
        font-family: '{Typography.MONO}';
    }}
    
    /* ============================================================
       TEXT EDIT / LOG OUTPUT
       ============================================================ */
    QTextEdit {{
        background-color: rgba(0, 0, 0, 0.3);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        padding: 12px;
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 13px;
        font-family: '{Typography.MONO}';
        selection-background-color: {GlassColors.PRIMARY};
    }}
    
    QTextEdit:focus {{
        border-color: {GlassColors.PRIMARY};
    }}
    
    /* ============================================================
       COMBO BOXES
       ============================================================ */
    QComboBox {{
        background-color: rgba(0, 0, 0, 0.3);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        padding: 10px 14px;
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        min-height: 40px;
    }}
    
    QComboBox:hover {{
        border-color: rgba(255, 255, 255, 0.15);
    }}
    
    QComboBox:focus {{
        border-color: {GlassColors.PRIMARY};
    }}
    
    QComboBox::drop-down {{
        border: none;
        width: 30px;
    }}
    
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {GlassColors.TEXT_SECONDARY};
        margin-right: 10px;
    }}
    
    QComboBox QAbstractItemView {{
        background-color: {GlassColors.BG_SURFACE};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        color: {GlassColors.TEXT_PRIMARY};
        selection-background-color: {GlassColors.PRIMARY};
        selection-color: {GlassColors.TEXT_PRIMARY};
        outline: none;
        padding: 4px;
    }}
    
    QComboBox QAbstractItemView::item {{
        min-height: 32px;
        padding: 6px 12px;
        border-radius: 4px;
    }}
    
    QComboBox QAbstractItemView::item:selected {{
        background-color: {GlassColors.PRIMARY};
    }}
    
    /* ============================================================
       SPIN BOXES
       ============================================================ */
    QSpinBox, QDoubleSpinBox {{
        background-color: rgba(0, 0, 0, 0.3);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        padding: 10px 14px;
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 14px;
        font-family: '{Typography.MONO}';
        min-height: 40px;
    }}
    
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {GlassColors.PRIMARY};
    }}
    
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        background-color: transparent;
        border: none;
        width: 24px;
        margin: 2px;
    }}
    
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {GlassColors.GLASS_HOVER};
        border-radius: 4px;
    }}
    
    /* ============================================================
       CHECKBOXES
       ============================================================ */
    QCheckBox {{
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        spacing: 10px;
    }}
    
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {GlassColors.GLASS_BORDER};
        border-radius: 4px;
        background-color: rgba(0, 0, 0, 0.3);
    }}
    
    QCheckBox::indicator:hover {{
        border-color: {GlassColors.PRIMARY_LIGHT};
    }}
    
    QCheckBox::indicator:checked {{
        background: {GlassColors.GRADIENT_PRIMARY};
        border-color: {GlassColors.PRIMARY};
    }}
    
    /* ============================================================
       LABELS
       ============================================================ */
    QLabel {{
        color: {GlassColors.TEXT_PRIMARY};
        font-family: '{Typography.FAMILY}';
        background: transparent;
        border: none;
    }}
    
    /* ============================================================
       TABS / SIDEBAR NAVIGATION
       ============================================================ */
    QListWidget#sidebarList {{
        background-color: rgba(0, 0, 0, 0.2);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 12px;
        padding: 8px;
        spacing: 4px;
    }}
    
    QListWidget#sidebarList::item {{
        color: {GlassColors.TEXT_SECONDARY};
        padding: 12px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-family: '{Typography.FAMILY}';
        border: none;
        background: transparent;
    }}
    
    QListWidget#sidebarList::item:hover {{
        color: {GlassColors.TEXT_PRIMARY};
        background-color: {GlassColors.GLASS_HOVER};
    }}
    
    QListWidget#sidebarList::item:selected {{
        color: {GlassColors.TEXT_PRIMARY};
        background: {GlassColors.GRADIENT_PRIMARY};
        font-weight: 600;
    }}
    
    /* ============================================================
       TABLES
       ============================================================ */
    QTableWidget {{
        background-color: rgba(0, 0, 0, 0.2);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 8px;
        gridline-color: rgba(255, 255, 255, 0.05);
        color: {GlassColors.TEXT_PRIMARY};
        font-size: 13px;
        font-family: '{Typography.FAMILY}';
        selection-background-color: {GlassColors.PRIMARY};
        selection-color: {GlassColors.TEXT_PRIMARY};
    }}
    
    QTableWidget::item {{
        padding: 10px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    }}
    
    QHeaderView::section {{
        background-color: rgba(0, 0, 0, 0.3);
        color: {GlassColors.TEXT_SECONDARY};
        padding: 12px;
        border: none;
        border-bottom: 1px solid {GlassColors.GLASS_BORDER};
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    
    /* ============================================================
       CHARTS & GRAPHICS
       ============================================================ */
    QChartView, QGraphicsView {{
        background-color: rgba(0, 0, 0, 0.25);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 12px;
    }}
    
    /* ============================================================
       SCROLLBARS - Modern minimal
       ============================================================ */
    QScrollBar:vertical {{
        background-color: rgba(0, 0, 0, 0.2);
        width: 8px;
        border-radius: 4px;
        margin: 0px;
    }}
    
    QScrollBar::handle:vertical {{
        background-color: rgba(255, 255, 255, 0.15);
        border-radius: 4px;
        min-height: 30px;
    }}
    
    QScrollBar::handle:vertical:hover {{
        background-color: rgba(255, 255, 255, 0.25);
    }}
    
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        height: 0px;
        width: 0px;
    }}
    
    QScrollBar:horizontal {{
        background-color: rgba(0, 0, 0, 0.2);
        height: 8px;
        border-radius: 4px;
    }}
    
    QScrollBar::handle:horizontal {{
        background-color: rgba(255, 255, 255, 0.15);
        border-radius: 4px;
        min-width: 30px;
    }}
    
    QScrollBar::handle:horizontal:hover {{
        background-color: rgba(255, 255, 255, 0.25);
    }}
    
    /* ============================================================
       STATUS BAR
       ============================================================ */
    QStatusBar {{
        background-color: rgba(0, 0, 0, 0.3);
        border-top: 1px solid {GlassColors.GLASS_BORDER};
        color: {GlassColors.TEXT_SECONDARY};
        font-size: 12px;
        font-family: '{Typography.FAMILY}';
    }}
    
    /* ============================================================
       SPLITTER
       ============================================================ */
    QSplitter::handle {{
        background-color: {GlassColors.GLASS_BORDER};
        border-radius: 2px;
    }}
    
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    
    QSplitter::handle:vertical {{
        height: 2px;
    }}
    
    QSplitter::handle:hover {{
        background-color: {GlassColors.PRIMARY};
    }}
    
    /* ============================================================
       DIALOGS
       ============================================================ */
    QDialog {{
        background-color: {GlassColors.BG_DARK};
    }}
    
    /* ============================================================
       PROGRESS BAR
       ============================================================ */
    QProgressBar {{
        background-color: rgba(0, 0, 0, 0.3);
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 6px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    
    QProgressBar::chunk {{
        background: {GlassColors.GRADIENT_PRIMARY};
        border-radius: 5px;
    }}
    
    /* ============================================================
       GROUP BOX
       ============================================================ */
    QGroupBox {{
        background-color: {GlassColors.GLASS_BG};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 12px;
        margin-top: 12px;
        padding-top: 24px;
        font-weight: 600;
        color: {GlassColors.TEXT_PRIMARY};
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 16px;
        padding: 0 8px;
        color: {GlassColors.TEXT_PRIMARY};
    }}
    
    /* ============================================================
       TOOLTIP
       ============================================================ */
    QToolTip {{
        background-color: {GlassColors.BG_SURFACE};
        color: {GlassColors.TEXT_PRIMARY};
        border: 1px solid {GlassColors.GLASS_BORDER};
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 13px;
        font-family: '{Typography.FAMILY}';
    }}
    
    /* ============================================================
       SPECIAL EFFECTS
       ============================================================ */
    
    /* Status indicators */
    .status-good {{
        color: {GlassColors.SUCCESS};
    }}
    
    .status-bad {{
        color: {GlassColors.ERROR};
    }}
    
    .status-warn {{
        color: {GlassColors.WARNING};
    }}
    
    /* Call/PUT action badges */
    .action-call {{
        color: {GlassColors.SUCCESS};
        font-weight: bold;
    }}
    
    .action-put {{
        color: {GlassColors.ERROR};
        font-weight: bold;
    }}
    """


# ============================================================================
# Application Theme Applier
# ============================================================================

def apply_glassmorphism_theme(app):
    """
    Apply the complete glassmorphism theme to the QApplication.
    Call this BEFORE creating any widgets.
    """
    from PySide6.QtWidgets import QApplication
    
    # Set application-wide attributes
    app.setFont(Typography.body())
    
    # Apply the comprehensive stylesheet
    stylesheet = get_glassmorphism_stylesheet()
    app.setStyleSheet(stylesheet)
    
    # Set palette for native widgets
    from PySide6.QtGui import QPalette
    palette = QPalette()
    
    palette.setColor(QPalette.Window, QColor(GlassColors.BG_DARKEST))
    palette.setColor(QPalette.WindowText, QColor(GlassColors.TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(GlassColors.BG_SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(GlassColors.BG_ELEVATED))
    palette.setColor(QPalette.ToolTipBase, QColor(GlassColors.BG_SURFACE))
    palette.setColor(QPalette.ToolTipText, QColor(GlassColors.TEXT_PRIMARY))
    palette.setColor(QPalette.Text, QColor(GlassColors.TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(GlassColors.BG_SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(GlassColors.TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(GlassColors.PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor(GlassColors.TEXT_PRIMARY))
    
    app.setPalette(palette)


# ============================================================================
# Utility Functions for Glass Effects
# ============================================================================

def create_glass_effect(widget, opacity=0.03, blur_radius=10):
    """Apply a subtle glass effect to any widget."""
    widget.setStyleSheet(f"""
        background-color: rgba(255, 255, 255, {opacity});
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
    """)


def add_glow_effect(widget, color=GlassColors.PRIMARY, blur_radius=15):
    """Add a glow effect to a widget."""
    glow = QGraphicsDropShadowEffect()
    glow.setBlurRadius(blur_radius)
    glow.setColor(QColor(color))
    glow.setOffset(0, 0)
    widget.setGraphicsEffect(glow)
    return glow


def create_fade_animation(widget, property_name=b"geometry", duration=300):
    """Create a smooth fade/slide animation."""
    anim = QPropertyAnimation(widget, property_name)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    return anim
