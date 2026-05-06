from __future__ import annotations

from datetime import datetime
import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from eternal_quotex_bot.controller import BotController
from eternal_quotex_bot.backend.external import default_exness_assets, default_iq_option_assets
from eternal_quotex_bot.backend.live import default_live_assets
from eternal_quotex_bot.device import machine_display_id
from eternal_quotex_bot.backend.mock import default_mock_assets
from eternal_quotex_bot.models import AppSettings, AssetInfo, Candle, StrategyDecision, TradeTicket
from eternal_quotex_bot.paths import app_data_dir, log_file, resource_path, settings_file
from eternal_quotex_bot.settings import MANAGED_LICENSE_API_URL, MANAGED_LICENSE_SHARED_TOKEN
from eternal_quotex_bot.ui.charts import CandleChartWidget
from eternal_quotex_bot.telegram_bot import TelegramRuntimeState, build_start_preview
from eternal_quotex_bot.pine_script import PineScriptRunner, INDICATOR_TEMPLATES


ADMIN_PANEL_PASSWORD = "00440404"


class MainWindow(QMainWindow):
    def __init__(self, controller: BotController) -> None:
        super().__init__()
        self.controller = controller
        self.trade_rows: dict[str, int] = {}
        self._asset_cache: list[AssetInfo] = []
        self._sticky_signal: StrategyDecision | None = None
        self._sticky_signal_until = 0.0
        self._latest_candles: list[Candle] = []
        self._exness_auto_connect_armed = False
        self._admin_unlocked = False
        self._admin_email = "raiyanetharyt04@gmail.com"  # Admin email for conditional tab visibility
        self._is_admin_user = False  # Track if current logged-in user is admin
        self._startup_license_prompt_handled = False
        self._startup_license_gate_scheduled = False
        self._exness_auto_connect_timer = QTimer(self)
        self._exness_auto_connect_timer.setSingleShot(True)
        self._exness_auto_connect_timer.timeout.connect(self._maybe_auto_connect_exness)
        self.setWindowTitle("Eternal Quotex Bot")
        self.setMinimumSize(1620, 960)
        self.setWindowIcon(QIcon(str(resource_path("eternal_brand.svg"))))
        self._build_ui()
        self._wire_controller()
        self._apply_settings(self.controller.settings)
        self._set_auto_button_state(self.controller.settings.strategy.auto_trade_enabled)
        self._update_learning_state(self.controller._learning_snapshot())
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1_000)
        self._tick_clock()
        # Debounce timer for search
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._refilter_watch_table)
        self._schedule_startup_license_gate()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._schedule_startup_license_gate()

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self.clock_timer.stop() if hasattr(self, "clock_timer") else None
            self.search_timer.stop() if hasattr(self, "search_timer") else None
        except Exception:
            pass
        try:
            settings = self._collect_settings()
            self.controller.settings = settings
            self.controller.settings_store.save(settings)
        except Exception as e:
            try:
                from eternal_quotex_bot.paths import log_file
                with open(log_file(), "a", encoding="utf-8") as f:
                    f.write(f"\n--- CLOSE EVENT ERROR ---\n{e}\n")
            except Exception:
                pass
        super().closeEvent(event)

    def shutdown(self) -> None:
        for attr_name in ("clock_timer", "search_timer", "_exness_auto_connect_timer"):
            timer = getattr(self, attr_name, None)
            if timer is not None:
                timer.stop()
        for widget in self.findChildren(QTimer):
            widget.stop()
        for obj in self.findChildren(QWidget):
            try:
                for signal in ["textChanged", "currentIndexChanged", "clicked", "toggled", "valueChanged", "timeout"]:
                    try:
                        getattr(obj, f"{signal}Signal").disconnect()
                    except (AttributeError, TypeError):
                        pass
            except Exception:
                pass

    def _license_length_summary(self, key: str) -> str:
        cleaned = str(key or "").strip()
        count = len(cleaned)
        if not cleaned:
            return "Length: 0 characters"
        return f"Length: {count} characters"

    def _update_license_key_metrics(self) -> None:
        # License key edit widget was removed from settings page
        # This method is kept for backwards compatibility but does nothing
        pass

    def _update_license_admin_key_metrics(self) -> None:
        if hasattr(self, "license_admin_key_length_value"):
            self.license_admin_key_length_value.setText(self._license_length_summary(self.license_admin_key_edit.text()))

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appRoot")
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)
        root.addWidget(self._build_header())
        root.addWidget(self._build_top_tabs())
        self.pages = QStackedWidget()
        self.page_indexes: dict[str, int] = {}

        # Build trade card and watchlist card FIRST so their widgets exist
        # before any page builder runs. This prevents AttributeError and
        # ensures page builders can reuse existing widgets via hasattr checks.
        self._trade_card = self._build_trade_card()
        self._watchlist_card = self._build_watchlist_card()
        self.trade_card = self._trade_card
        self.watchlist_card = self._watchlist_card

        class _ChartCatalogProxy:
            def __init__(self, window):
                self._window = window

            def count(self):
                if hasattr(self._window, "full_chart_asset_combo"):
                    combo_count = self._window.full_chart_asset_combo.count()
                    if combo_count:
                        return combo_count
                if hasattr(self._window, "watch_table"):
                    return self._window.watch_table.rowCount()
                return 0

        for key, builder, scrollable in (
            ("markets", self._build_dashboard_page, False),
            ("charts", self._build_chart_studio_page, False),
            ("strategy", self._build_strategy_page, True),
            ("live", self._build_live_page, True),
            ("telegram", self._build_telegram_page, True),
            ("deep_scan", self._build_deep_scan_page, True),
            ("signal_format", self._build_signal_format_page, True),
            ("auto_trading", self._build_auto_trading_page, True),
            ("auto_history", self._build_history_page, False),
            ("pine_editor", self._build_pine_editor_page, False),
            ("log", self._build_log_page, False),
            ("settings", self._build_settings_page, True),
            ("admin", self._build_admin_panel_page, True),
        ):
            page = builder()
            self.page_indexes[key] = self.pages.addWidget(self._wrap_page(page) if scrollable else page)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.full_chart_list = _ChartCatalogProxy(self)

        # All card widgets already created above, just connect signals
        self.provider_combo.currentIndexChanged.connect(self._sync_provider_fields)
        self.asset_combo.currentIndexChanged.connect(lambda _: self._asset_changed())
        self.full_chart_asset_combo.currentIndexChanged.connect(self._full_chart_asset_changed)
        self.period_combo.currentIndexChanged.connect(self._period_changed)
        self.full_chart_period_combo.currentIndexChanged.connect(self._full_chart_period_changed)
        self.duration_combo.currentIndexChanged.connect(self._trade_ticket_changed)
        self.amount_spin.valueChanged.connect(lambda _: self._trade_ticket_changed())
        self.watch_table.itemSelectionChanged.connect(self._asset_from_table)
        self.asset_search_edit.textChanged.connect(lambda: (self.search_timer.stop(), self.search_timer.start(200)))
        self.watch_category_combo.currentIndexChanged.connect(self._refilter_watch_table)
        self.connect_button.clicked.connect(self._connect_clicked)
        self.disconnect_button.clicked.connect(self.controller.disconnect_backend)
        self.engine_button.clicked.connect(self._engine_button_clicked)
        self.toolbar_disconnect_button.clicked.connect(self.controller.disconnect_backend)
        self.toolbar_refresh_button.clicked.connect(self.controller.refresh_market)
        self.deep_scan_button.clicked.connect(self.controller.deep_scan_all)
        self.deep_scan_run_button.clicked.connect(self.controller.deep_scan_all)
        self.continuous_monitor_button.clicked.connect(self._continuous_monitor_toggled)
        self.buy_button.clicked.connect(lambda checked=False, action="CALL": self._submit_manual_trade(action))
        self.sell_button.clicked.connect(lambda checked=False, action="PUT": self._submit_manual_trade(action))
        self.refresh_button.clicked.connect(self.controller.refresh_market)
        self.save_button.clicked.connect(self._save_settings)
        self.auto_trade_button.clicked.connect(self._toggle_automation)
        self.show_warming_pairs_checkbox.toggled.connect(self._refilter_watch_table)
        self.telegram_enabled_checkbox.toggled.connect(self._update_telegram_preview)
        self.telegram_token_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_engine_name_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_start_title_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_start_message_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_pairs_title_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_pair_template_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_deep_scan_label_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_start_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_status_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_pairs_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_otc_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_real_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_button_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_status_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_charts_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_broadcast_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_test_capture_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_admin_chat_ids_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_preferred_broker_combo.currentIndexChanged.connect(self._update_telegram_preview)
        self.telegram_preferred_broker_combo.currentIndexChanged.connect(self._update_telegram_broker_summary)
        self.telegram_enabled_quotex_checkbox.toggled.connect(self._update_telegram_preview)
        self.telegram_enabled_quotex_checkbox.toggled.connect(self._update_telegram_broker_summary)
        self.telegram_enabled_pocket_checkbox.toggled.connect(self._update_telegram_preview)
        self.telegram_enabled_exness_checkbox.toggled.connect(self._update_telegram_preview)
        self.telegram_enabled_exness_checkbox.toggled.connect(self._update_telegram_broker_summary)
        self.telegram_use_all_brokers_checkbox.toggled.connect(self._update_telegram_preview)
        self.telegram_use_all_brokers_checkbox.toggled.connect(self._update_telegram_broker_summary)
        self.telegram_pocket_url_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_pocket_email_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_pocket_password_edit.textChanged.connect(self._update_telegram_preview)
        self.telegram_scan_seconds_spin.valueChanged.connect(self._update_telegram_preview)
        self.telegram_start_runtime_button.clicked.connect(self._start_telegram_bot)
        self.telegram_stop_runtime_button.clicked.connect(self.controller.stop_telegram_bot)
        self.learning_enabled_checkbox.toggled.connect(self._save_settings)
        self.learning_interval_spin.valueChanged.connect(lambda _: self._save_settings())
        self.learning_verify_combo.currentIndexChanged.connect(lambda _: self._save_settings())
        self.preferred_expiry_combo.currentIndexChanged.connect(self._update_signal_format_preview)
        self.sticky_signal_spin.valueChanged.connect(self._update_signal_format_preview)
        self.admin_unlock_button.clicked.connect(self._unlock_admin_panel)
        self.license_generate_button.clicked.connect(self._generate_license_key)
        self.license_create_button.clicked.connect(self._create_license)
        self.license_revoke_button.clicked.connect(self._revoke_license)
        self.license_delete_button.clicked.connect(self._on_delete_license_clicked)
        self.license_refresh_button.clicked.connect(self._refresh_license_list)
        self.license_admin_key_edit.textChanged.connect(self._update_license_admin_key_metrics)
        self._switch_page("markets")

    def _wrap_page(self, content: QWidget) -> QWidget:
        content.setObjectName("pageSurface")
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_header(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("headerSurface")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        self.engine_button = QPushButton("START Engine")
        self.engine_button.setObjectName("engineButton")
        self.engine_button.setFixedHeight(34)
        layout.addWidget(self.engine_button, 0, Qt.AlignLeft)

        brand = QVBoxLayout()
        brand.setSpacing(2)
        title = QLabel("Eternal Quotex Bot")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Live OTC cockpit with browser-backed Quotex market feed, signal engine, and execution controls")
        subtitle.setObjectName("heroSub")
        subtitle.setWordWrap(True)
        self.connection_detail = QLabel("Select a provider and start a live session.")
        self.connection_detail.setObjectName("helperText")
        self.connection_detail.setWordWrap(True)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        brand.addWidget(self.connection_detail)

        stats_layout = QGridLayout()
        stats_layout.setHorizontalSpacing(12)
        stats_layout.setVerticalSpacing(8)
        self.status_value = QLabel("Ready")
        self.balance_value = QLabel("$0.00")
        self.mode_value = QLabel("Offline")
        self.clock_value = QLabel("--:--:--")

        for label, value, row, col in (
            ("Status", self.status_value, 0, 0),
            ("Balance", self.balance_value, 0, 1),
            ("Mode", self.mode_value, 1, 0),
            ("Local Time", self.clock_value, 1, 1),
        ):
            tile = QFrame()
            tile.setObjectName("metricTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(12, 8, 12, 8)
            tile_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("metricLabel")
            value.setObjectName("metricValue")
            tile_layout.addWidget(caption)
            tile_layout.addWidget(value)
            stats_layout.addWidget(tile, row, col)

        layout.addLayout(brand, 3)
        layout.addLayout(stats_layout, 2)
        return frame

    def _build_top_tabs(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("tabStrip")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        self.page_buttons: dict[str, QPushButton] = {}
        
        # Define all tabs
        all_tabs = [
            ("Markets", "markets"),
            ("Chart Studio", "charts"),
            ("Strategy AI", "strategy"),
            ("Live", "live"),
            ("Telegram", "telegram"),
            ("Deep Scan", "deep_scan"),
            ("Signal Format", "signal_format"),
            ("Auto Trading", "auto_trading"),
            ("Auto History", "auto_history"),
            ("Pine Editor", "pine_editor"),
            ("Log", "log"),
            ("Settings", "settings"),
        ]
        
        # Add Admin tab conditionally (will be shown/hidden based on user)
        admin_tab = ("Admin", "admin")
        
        # Create all buttons
        for label, page_key in all_tabs:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("tabButton")
            button.clicked.connect(lambda checked=False, target=page_key: self._switch_page(target))
            layout.addWidget(button)
            self.page_buttons[page_key] = button
        
        # Add Admin button (initially hidden)
        admin_button = QPushButton(admin_tab[0])
        admin_button.setCheckable(True)
        admin_button.setObjectName("tabButton")
        admin_button.clicked.connect(lambda checked=False, target=admin_tab[1]: self._switch_page(target))
        admin_button.setVisible(False)  # Hidden by default
        layout.addWidget(admin_button)
        self.page_buttons[admin_tab[1]] = admin_button
        
        layout.addStretch(1)
        return frame

    def _switch_page(self, page_key: str) -> None:
        page_index = self.page_indexes.get(page_key, 0)
        self.pages.setCurrentIndex(page_index)
        if page_key == "admin":
            self._sync_admin_panel()
        self._set_active_page_button(page_key)

    def _set_active_page_button(self, page_key: str) -> None:
        for button_key, button in self.page_buttons.items():
            is_active = button_key == page_key
            button.setChecked(is_active)

    def _engine_button_clicked(self) -> None:
        if self.controller.connected:
            self.controller.disconnect_backend()
        else:
            self._connect_clicked()

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        # Welcome banner
        banner = QFrame()
        banner.setObjectName("welcomeBanner")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(16, 14, 16, 14)
        banner_layout.setSpacing(4)
        banner_title = QLabel("\U0001f451 ETERNAL AI BOT \U0001f451")
        banner_title.setObjectName("welcomeBannerTitle")
        banner_title.setAlignment(Qt.AlignCenter)
        banner_subtitle = QLabel("Apex Engine v214")
        banner_subtitle.setObjectName("welcomeBannerSub")
        banner_subtitle.setAlignment(Qt.AlignCenter)
        banner_divider = QLabel("\u2550" * 30)
        banner_divider.setObjectName("welcomeBannerDivider")
        banner_divider.setAlignment(Qt.AlignCenter)
        features_layout = QHBoxLayout()
        features_layout.setSpacing(16)
        features_layout.setAlignment(Qt.AlignCenter)
        for feature in (
            "\U0001f9e0 15-Layer Analysis",
            "\U0001f9ec OTC Currency + Stocks",
            "\U0001f916 Multi-Indicator Voting",
            "\U0001f3af Max Accuracy Signals",
        ):
            feat_label = QLabel(feature)
            feat_label.setObjectName("welcomeFeature")
            features_layout.addWidget(feat_label)
        banner_layout.addWidget(banner_title)
        banner_layout.addWidget(banner_subtitle)
        banner_layout.addWidget(banner_divider)
        banner_layout.addLayout(features_layout)
        layout.addWidget(banner)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarSurface")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)
        self.toolbar_disconnect_button = QPushButton("Stop Live")
        self.toolbar_disconnect_button.setObjectName("toolbarButton")
        self.toolbar_refresh_button = QPushButton("Refresh")
        self.toolbar_refresh_button.setObjectName("toolbarButton")
        self.deep_scan_button = QPushButton("Deep Scan All")
        self.deep_scan_button.setObjectName("primaryButton")
        self.asset_combo = QComboBox()
        self.asset_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.asset_combo.setMinimumWidth(220)
        self.asset_combo.setMaxVisibleItems(24)
        self.period_combo = QComboBox()
        self.period_combo.addItem("1m", 60)
        self.period_combo.addItem("2m", 120)
        self.period_combo.addItem("5m", 300)
        self.market_chip = QLabel("Market: --")
        self.market_chip.setObjectName("toolbarLabel")
        self.scan_chip = QLabel("Deep Scan: idle")
        self.scan_chip.setObjectName("toolbarLabel")
        self.engine_marks_value = QLabel("Engine Marks: READY")
        self.engine_marks_value.setObjectName("toolbarLabel")
        self.candle_countdown_value = QLabel("Candle closes in: --")
        self.candle_countdown_value.setObjectName("toolbarLabel")
        toolbar_layout.addWidget(self.toolbar_disconnect_button)
        toolbar_layout.addWidget(self.toolbar_refresh_button)
        toolbar_layout.addWidget(self.deep_scan_button)
        toolbar_layout.addWidget(self.asset_combo, 1)
        toolbar_layout.addWidget(QLabel("TF:"))
        toolbar_layout.addWidget(self.period_combo)
        toolbar_layout.addWidget(self.engine_marks_value)
        toolbar_layout.addWidget(self.market_chip)
        toolbar_layout.addWidget(self.scan_chip)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.candle_countdown_value)
        layout.addWidget(toolbar)

        strip = QHBoxLayout()
        strip.setSpacing(12)
        strip.addWidget(self._build_summary_card("Signal", "HOLD", "quick_signal_value", "quick_signal_summary"))
        strip.addWidget(self._build_summary_card("Confidence", "0.00", "quick_confidence_value", "quick_confidence_summary"))
        strip.addWidget(self._build_summary_card("Last Price", "--", "last_price_value", "last_price_summary"))
        strip.addWidget(self._build_summary_card("Auto Mode", "Paused", "auto_state_value", "auto_state_summary"))
        layout.addLayout(strip)

        center_card, center_layout = self._card("Market View", "Large-format candles, live price context, and the active setup stay centered here.")
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(2)
        self.chart = CandleChartWidget()
        self.chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chart.setMinimumHeight(0)
        self.market_detail = QLabel("Connect a session to start streaming candles.")
        self.market_detail.setObjectName("helperText")
        self.market_detail.setWordWrap(True)
        self.signal_display = QLabel("No active signal")
        self.signal_display.setObjectName("metricValue")
        self.signal_display.setWordWrap(True)
        self.signal_display.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.chart, 10)
        center_layout.addWidget(self.signal_display, 0)
        center_layout.addWidget(self.market_detail, 0)
        center_card.setMinimumWidth(1260)
        layout.addWidget(center_card, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        market_focus_card, market_focus_layout = self._card("Active Market", "The selected pair, live price, and last locked setup stay visible here.")
        self.market_focus_value = QLabel("Waiting for market data")
        self.market_focus_value.setObjectName("metricValue")
        self.market_focus_reason = QLabel("Select a pair from Live, connect, then watch the live chart update here.")
        self.market_focus_reason.setObjectName("helperText")
        self.market_focus_reason.setWordWrap(True)
        market_focus_layout.addWidget(self.market_focus_value)
        market_focus_layout.addWidget(self.market_focus_reason)

        scan_focus_card, scan_focus_layout = self._card("Deep Scan Focus", "The strongest confirmed scan result is pinned here until a newer one replaces it.")
        self.deep_scan_focus_value = QLabel("No Deep Scan result yet")
        self.deep_scan_focus_value.setObjectName("metricValue")
        self.deep_scan_focus_reason = QLabel("Run Deep Scan All from Markets or the Deep Scan tab.")
        self.deep_scan_focus_reason.setObjectName("helperText")
        self.deep_scan_focus_reason.setWordWrap(True)
        scan_focus_layout.addWidget(self.deep_scan_focus_value)
        scan_focus_layout.addWidget(self.deep_scan_focus_reason)

        footer.addWidget(market_focus_card, 1)
        footer.addWidget(scan_focus_card, 1)
        layout.addLayout(footer)
        return page

    def _build_chart_studio_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Compact single-row toolbar at top
        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)
        top_bar.setContentsMargins(4, 2, 4, 2)
        self.full_chart_asset_combo = QComboBox()
        self.full_chart_asset_combo.setMinimumWidth(160)
        self.full_chart_asset_combo.setMaximumWidth(220)
        self.full_chart_period_combo = QComboBox()
        self.full_chart_period_combo.addItem("1m", 60)
        self.full_chart_period_combo.addItem("2m", 120)
        self.full_chart_period_combo.addItem("5m", 300)
        self.full_chart_category_combo = QComboBox()
        self.full_chart_category_combo.setMaximumWidth(140)
        self.full_chart_category_combo.addItem("All", "all")
        self.full_chart_category_combo.addItem("OTC", "binary")
        self.full_chart_category_combo.addItem("Forex", "forex")
        self.full_chart_category_combo.addItem("Crypto", "crypto")
        self.full_chart_category_combo.addItem("Other", "other")
        self.full_chart_search_edit = QLineEdit()
        self.full_chart_search_edit.setPlaceholderText("Search...")
        self.full_chart_search_edit.setMaximumWidth(150)
        self.full_chart_refresh_button = QPushButton("Refresh")
        self.full_chart_refresh_button.setObjectName("toolbarButton")
        self.full_chart_refresh_button.clicked.connect(self.controller.refresh_market)
        top_bar.addWidget(self.full_chart_asset_combo, 2)
        top_bar.addWidget(QLabel("TF"))
        top_bar.addWidget(self.full_chart_period_combo)
        top_bar.addWidget(self.full_chart_category_combo)
        top_bar.addWidget(self.full_chart_search_edit, 1)
        top_bar.addWidget(self.full_chart_refresh_button)
        layout.addLayout(top_bar, 0)

        # Tiny status row with countdown only
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.setContentsMargins(4, 0, 4, 0)
        self.full_chart_countdown_value = QLabel("Candle closes in: --")
        self.full_chart_countdown_value.setObjectName("toolbarLabel")
        status_row.addWidget(self.full_chart_countdown_value, 1)
        layout.addLayout(status_row, 0)

        # Chart takes all remaining space
        self.full_chart = CandleChartWidget()
        self.full_chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.full_chart.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.full_chart, 1)

        return page

    def _build_strategy_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        signal_card, signal_layout = self._card("Signal Engine", "Locked-candle EMA, RSI, and pressure model tuned for 1m and 2m entries")
        signal_grid = QGridLayout()
        self.signal_value = QLabel("HOLD")
        self.confidence_value = QLabel("0.00")
        self.rsi_value = QLabel("--")
        self.trend_value = QLabel("--")
        self.expiry_value = QLabel("2m")
        self.signal_lock_value = QLabel("--")
        self.signal_reason = QLabel("Waiting for enough candles.")
        self.signal_reason.setObjectName("helperText")
        self.signal_reason.setWordWrap(True)

        for label, value, row, col in (
            ("Signal", self.signal_value, 0, 0),
            ("Confidence", self.confidence_value, 0, 1),
            ("RSI", self.rsi_value, 1, 0),
            ("Trend Strength", self.trend_value, 1, 1),
            ("Recommended Expiry", self.expiry_value, 2, 0),
            ("Locked Candle", self.signal_lock_value, 2, 1),
        ):
            caption = QLabel(label)
            caption.setObjectName("metricLabel")
            value.setObjectName("metricValue")
            signal_grid.addWidget(caption, row * 2, col)
            signal_grid.addWidget(value, row * 2 + 1, col)
        signal_layout.addLayout(signal_grid)
        signal_layout.addWidget(self.signal_reason)

        controls_card, controls_layout = self._card("Execution Rules", "Tune thresholds, risk rails, and refresh cadence")
        form = QFormLayout()
        self.fast_ema_spin = QSpinBox()
        self.fast_ema_spin.setRange(3, 50)
        self.slow_ema_spin = QSpinBox()
        self.slow_ema_spin.setRange(5, 120)
        self.rsi_spin = QSpinBox()
        self.rsi_spin.setRange(5, 40)
        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.5, 0.95)
        self.confidence_spin.setDecimals(2)
        self.confidence_spin.setSingleStep(0.01)
        self.auto_trade_checkbox = QCheckBox("Arm auto trading after saving")
        self.stop_profit_spin = QDoubleSpinBox()
        self.stop_profit_spin.setRange(1, 10_000)
        self.stop_loss_spin = QDoubleSpinBox()
        self.stop_loss_spin.setRange(1, 10_000)
        self.max_losses_spin = QSpinBox()
        self.max_losses_spin.setRange(1, 20)
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(10, 3600)
        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setRange(1, 30)
        self.save_button = QPushButton("Save Strategy + Risk")
        self.save_button.setObjectName("primaryButton")
        self.expiry_spin = QSpinBox()
        self.expiry_spin.setRange(60, 900)
        self.timer_spin = QSpinBox()
        self.timer_spin.setRange(1, 60)
        
        form.addRow("Expiry (s)", self.expiry_spin)
        form.addRow("Entry Timer (s)", self.timer_spin)
        
        form.addRow("Fast EMA", self.fast_ema_spin)
        form.addRow("Slow EMA", self.slow_ema_spin)
        form.addRow("RSI Period", self.rsi_spin)
        form.addRow("Min Confidence", self.confidence_spin)
        form.addRow("Stop Profit", self.stop_profit_spin)
        form.addRow("Stop Loss", self.stop_loss_spin)
        form.addRow("Max Loss Streak", self.max_losses_spin)
        form.addRow("Cooldown (s)", self.cooldown_spin)
        form.addRow("Refresh (s)", self.refresh_interval_spin)
        controls_layout.addLayout(form)
        controls_layout.addWidget(self.auto_trade_checkbox)
        controls_layout.addWidget(self.save_button)
        guide_card, guide_layout = self._card("How To Use This Page", "These are numeric controls, not free-text boxes.")
        guide = QLabel(
            "Use the up/down arrows or type a number into the fields. Fast EMA, Slow EMA, RSI, confidence, and risk values all update the signal rules. "
            "After changing them, click Save Strategy + Risk."
        )
        guide.setObjectName("helperText")
        guide.setWordWrap(True)
        guide_layout.addWidget(guide)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        top_row.addWidget(signal_card, 1)
        top_row.addWidget(controls_card, 1)
        layout.addWidget(guide_card)
        layout.addLayout(top_row)
        layout.addStretch(1)
        return page

    def _build_live_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Connection Center card
        connect_card, connect_layout = self._card("Connection Center", "Choose a broker session and connect to start trading.")
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Mock Sandbox", "mock")
        self.provider_combo.addItem("Quotex", "live")
        self.provider_combo.addItem("IQ Option", "iq_option")
        self.provider_combo.addItem("Forex Market", "exness")
        self.provider_combo.addItem("Multi-Broker Feed", "multi")
        self.provider_hint = QLabel()
        self.provider_hint.setObjectName("helperText")
        self.provider_hint.setWordWrap(True)
        top_form = QFormLayout()
        top_form.setSpacing(8)
        top_form.addRow("Provider", self.provider_combo)
        connect_layout.addLayout(top_form)
        connect_layout.addWidget(self.provider_hint)
        self.provider_stack = QStackedWidget()
        self.provider_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.provider_stack.addWidget(self._build_mock_provider_panel())
        self.provider_stack.addWidget(self._build_live_provider_panel())
        self.provider_stack.addWidget(self._build_pocket_option_provider_panel())
        self.provider_stack.addWidget(self._build_exness_provider_panel())
        self.provider_stack.addWidget(self._build_multi_broker_provider_panel())
        connect_layout.addWidget(self.provider_stack)
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.connect_button = QPushButton("Start Session")
        self.connect_button.setObjectName("primaryButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("ghostButton")
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)
        connect_layout.addLayout(button_row)
        layout.addWidget(connect_card)

        # Trade Ticket
        layout.addWidget(self._build_trade_card())

        # Pair Explorer
        layout.addWidget(self._build_watchlist_card(), 1)

        return page

    def _build_deep_scan_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        hero_card, hero_layout = self._card("Deep Scan All", "Scan the live OTC list, compare setups, and keep the strongest result visible for manual entry.")
        hero_layout.setSpacing(10)
        
        # Scan Mode Selection (Sniper vs Broadcast)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem("Sniper Mode (Best Accuracy)", "sniper")
        self.scan_mode_combo.addItem("Broadcast Mode (Telegram Signals)", "broadcast")
        self.scan_mode_combo.setMinimumWidth(240)
        mode_row.addWidget(QLabel("Scan Mode:"), 0)
        mode_row.addWidget(self.scan_mode_combo, 0)
        
        self.sniper_pairs_edit = QLineEdit()
        self.sniper_pairs_edit.setPlaceholderText("e.g. USDBDT_otc, USDINR_otc")
        self.sniper_pairs_edit.setMinimumWidth(250)
        mode_row.addWidget(QLabel("Sniper Pairs:"), 0)
        mode_row.addWidget(self.sniper_pairs_edit, 1)
        
        hero_layout.addLayout(mode_row)

        # Market Health Monitor - shows which pairs are getting live data
        health_card, health_layout = self._card(
            "Market Health Monitor",
            "Shows which pairs are currently receiving live price data from Quotex. Use these pairs in Sniper Mode."
        )
        self.market_health_table = QTableWidget(0, 4)
        self.market_health_table.setHorizontalHeaderLabels(["Pair", "Current Price", "Last Update", "Status"])
        self.market_health_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.market_health_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.market_health_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.market_health_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.market_health_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.market_health_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.market_health_table.verticalHeader().setVisible(False)
        self.market_health_table.setAlternatingRowColors(True)
        health_layout.addWidget(self.market_health_table)
        
        # Auto-suggest button
        self.suggest_sniper_button = QPushButton("Auto-Set Active Pairs as Sniper")
        self.suggest_sniper_button.setObjectName("primaryButton")
        self.suggest_sniper_button.clicked.connect(self._suggest_active_pairs_for_sniper)
        health_layout.addWidget(self.suggest_sniper_button)
        
        hero_layout.addWidget(health_card)
        
        hero_row = QHBoxLayout()
        self.deep_scan_run_button = QPushButton("Run Deep Scan All")
        self.deep_scan_run_button.setObjectName("primaryButton")
        self.deep_scan_status_value = QLabel("Waiting for a scan.")
        self.deep_scan_status_value.setObjectName("helperText")
        self.deep_scan_status_value.setWordWrap(True)
        hero_row.addWidget(self.deep_scan_run_button, 0)
        hero_row.addWidget(self.deep_scan_status_value, 1)
        hero_layout.addLayout(hero_row)
        self.deep_scan_result_value = QLabel("No best pair yet")
        self.deep_scan_result_value.setObjectName("metricValue")
        self.deep_scan_result_reason = QLabel("When a confirmed setup is found, it will stay pinned here instead of vanishing into the shared status line.")
        self.deep_scan_result_reason.setObjectName("helperText")
        self.deep_scan_result_reason.setWordWrap(True)
        hero_layout.addWidget(self.deep_scan_result_value)
        hero_layout.addWidget(self.deep_scan_result_reason)

        # Continuous Monitor Card
        monitor_card, monitor_layout = self._card(
            "Continuous Monitor",
            "Automatically scans all pairs every 5 minutes and alerts when high-confidence signals appear."
        )
        monitor_row = QHBoxLayout()
        self.continuous_monitor_button = QPushButton("Start Continuous Monitor")
        self.continuous_monitor_button.setObjectName("primaryButton")
        self.continuous_monitor_button.setCheckable(True)
        self.continuous_monitor_button.setChecked(False)  # Default OFF
        self.continuous_monitor_status = QLabel("Monitor is OFF")
        self.continuous_monitor_status.setObjectName("helperText")
        self.continuous_monitor_status.setWordWrap(True)
        monitor_row.addWidget(self.continuous_monitor_button, 0)
        monitor_row.addWidget(self.continuous_monitor_status, 1)
        monitor_layout.addLayout(monitor_row)
        self.continuous_signal_display = QLabel("No continuous signal yet")
        self.continuous_signal_display.setObjectName("metricValue")
        self.continuous_signal_display.setWordWrap(True)
        monitor_layout.addWidget(self.continuous_signal_display)

        learning_card, learning_layout = self._card(
            "Learning Brain",
            "Passive training mode records Deep Scan signals, checks them after the selected verification window, and learns from each win or loss."
        )
        learning_form = QFormLayout()
        self.learning_enabled_checkbox = QCheckBox("Enable passive self-learning")
        self.learning_interval_spin = QSpinBox()
        self.learning_interval_spin.setRange(20, 600)
        self.learning_interval_spin.setSuffix(" s")
        self.learning_verify_combo = QComboBox()
        self.learning_verify_combo.addItem("1 Minute", 60)
        self.learning_verify_combo.addItem("2 Minutes", 120)
        self.learning_verify_combo.addItem("3 Minutes", 180)
        learning_form.addRow("Scan Interval", self.learning_interval_spin)
        learning_form.addRow("Verify After", self.learning_verify_combo)
        learning_layout.addWidget(self.learning_enabled_checkbox)
        learning_layout.addLayout(learning_form)
        self.learning_status_value = QLabel("Learning brain is idle.")
        self.learning_status_value.setObjectName("helperText")
        self.learning_status_value.setWordWrap(True)
        self.learning_stats_value = QLabel("Samples: 0 | Win Rate: 0.00% | Pending: 0")
        self.learning_stats_value.setObjectName("metricValue")
        self.learning_recent_value = QLabel("No learning results yet.")
        self.learning_recent_value.setObjectName("helperText")
        self.learning_recent_value.setWordWrap(True)
        learning_layout.addWidget(self.learning_status_value)
        learning_layout.addWidget(self.learning_stats_value)
        learning_layout.addWidget(self.learning_recent_value)

        table_card, table_layout = self._card("Scan Results", "Every reviewed pair is listed here with its signal, confidence, current price, and confirmation state.")
        self.deep_scan_table = QTableWidget(0, 6)
        self.deep_scan_table.setHorizontalHeaderLabels(["Pair", "Signal", "Confidence", "Current Price", "Confirm", "Summary"])
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.deep_scan_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.deep_scan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.deep_scan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.deep_scan_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.deep_scan_table.verticalHeader().setVisible(False)
        self.deep_scan_table.setAlternatingRowColors(True)
        table_layout.addWidget(self.deep_scan_table)

        layout.addWidget(hero_card)
        layout.addWidget(monitor_card)
        layout.addWidget(learning_card)
        layout.addWidget(table_card, 1)
        return page

    def _build_signal_format_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        card, card_layout = self._card("Signal Format", "Control how long a signal stays visible and which expiry the engine favors when conditions are strong.")
        form = QFormLayout()
        self.preferred_expiry_combo = QComboBox()
        self.preferred_expiry_combo.addItem("1 Minute", 60)
        self.preferred_expiry_combo.addItem("2 Minutes", 120)
        self.sticky_signal_spin = QSpinBox()
        self.sticky_signal_spin.setRange(20, 240)
        self.sticky_signal_spin.setSuffix(" s")
        form.addRow("Preferred Expiry", self.preferred_expiry_combo)
        form.addRow("Signal Hold Time", self.sticky_signal_spin)
        card_layout.addLayout(form)
        self.signal_format_preview = QTextEdit()
        self.signal_format_preview.setReadOnly(True)
        self.signal_format_preview.setFixedHeight(220)
        card_layout.addWidget(self.signal_format_preview)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_auto_trading_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.addWidget(self._build_automation_card())
        session_card, session_layout = self._card("Session Metrics", "Track current run performance and automation state from one place.")
        self.session_stats_value = QLabel("0 trades | 0 wins | 0 losses")
        self.session_stats_value.setObjectName("metricValue")
        self.pnl_value = QLabel("$0.00")
        self.pnl_value.setObjectName("metricValue")
        self.automation_state = QLabel("Automation paused")
        self.automation_state.setObjectName("helperText")
        self.automation_state.setWordWrap(True)
        session_layout.addWidget(self.session_stats_value)
        session_layout.addWidget(self.pnl_value)
        session_layout.addWidget(self.automation_state)
        layout.addWidget(session_card)
        layout.addStretch(1)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        trades_card, trades_layout = self._card("Trade Journal", "Every manual and automated order is logged here.")
        self.trade_table = QTableWidget(0, 8)
        self.trade_table.setHorizontalHeaderLabels(["Time", "Source", "Asset", "Action", "Amount", "Duration", "Status", "P/L"])
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trade_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trade_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trade_table.verticalHeader().setVisible(False)
        trades_layout.addWidget(self.trade_table)
        layout.addWidget(trades_card, 1)
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        log_card, log_layout = self._card("System Log", "Connection, signal, scan, and automation events.")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        # Use document limit instead of setMaximumBlockCount (not available in PySide6)
        doc = self.log_output.document()
        doc.setMaximumBlockCount(10000)  # Keep last 10k lines
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_card, 1)
        return page

    def _build_pine_editor_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Top toolbar: indicator dropdown + Run/Save buttons
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Indicator:"))
        self.pine_indicator_combo = QComboBox()
        self.pine_indicator_combo.setMinimumWidth(180)
        self.pine_indicator_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for name in INDICATOR_TEMPLATES:
            self.pine_indicator_combo.addItem(name)
        self.pine_load_button = QPushButton("Load Template")
        self.pine_load_button.setObjectName("toolbarButton")
        self.pine_run_button = QPushButton("Run")
        self.pine_run_button.setObjectName("primaryButton")
        self.pine_save_button = QPushButton("Save")
        self.pine_save_button.setObjectName("toolbarButton")
        self.pine_apply_button = QPushButton("Apply to Chart")
        self.pine_apply_button.setObjectName("primaryButton")
        self.pine_clear_overlay_button = QPushButton("Clear Overlay")
        self.pine_clear_overlay_button.setObjectName("ghostButton")
        toolbar.addWidget(self.pine_indicator_combo, 1)
        toolbar.addWidget(self.pine_load_button)
        toolbar.addWidget(self.pine_run_button)
        toolbar.addWidget(self.pine_save_button)
        toolbar.addWidget(self.pine_apply_button)
        toolbar.addWidget(self.pine_clear_overlay_button)
        layout.addLayout(toolbar)

        # Splitter: editor on top, output on bottom
        splitter = QSplitter(Qt.Vertical)

        # Code editor
        editor_card, editor_layout = self._card("Pine Script Editor", "Write or load a Pine Script-like indicator and run it against the current chart data.")
        self.pine_editor = QTextEdit()
        self.pine_editor.setPlaceholderText("// Select an indicator from the dropdown and click 'Load Template',\n// or write your own script here.\n\nindicator = RSI(close, period=14)\n\nif indicator > 70:\n    signal = \"SELL\"\nelif indicator < 30:\n    signal = \"BUY\"\nelse:\n    signal = \"NEUTRAL\"")
        self.pine_editor.setLineWrapMode(QTextEdit.NoWrap)
        editor_layout.addWidget(self.pine_editor, 1)
        editor_card.setMinimumHeight(280)

        # Output log
        output_card, output_layout = self._card("Output Log", "Results from the last script run.")
        self.pine_output = QTextEdit()
        self.pine_output.setReadOnly(True)
        self.pine_output.setPlaceholderText("Run a script to see output here...")
        output_layout.addWidget(self.pine_output, 1)
        output_card.setMinimumHeight(180)

        splitter.addWidget(editor_card)
        splitter.addWidget(output_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # Wire up buttons
        self.pine_load_button.clicked.connect(self._load_pine_template)
        self.pine_run_button.clicked.connect(self._run_pine_script)
        self.pine_save_button.clicked.connect(self._save_pine_script)
        self.pine_apply_button.clicked.connect(self._apply_pine_script_to_chart)
        self.pine_clear_overlay_button.clicked.connect(self._clear_pine_overlay)

        return page

    def _load_pine_template(self) -> None:
        name = self.pine_indicator_combo.currentText()
        if name in INDICATOR_TEMPLATES:
            self.pine_editor.setPlainText(INDICATOR_TEMPLATES[name])

    def _run_pine_script(self) -> None:
        script = self.pine_editor.toPlainText().strip()
        if not script:
            self.pine_output.setPlainText("No script to run. Write a script or load a template.")
            return

        candles = self._get_current_candles()
        if not candles:
            self.pine_output.setPlainText("No candle data available. Connect to a market first.")
            return

        runner = PineScriptRunner(candles)
        result = runner.run(script)

        output = result["output"]
        signals = result.get("signals", [])
        overlay_count = len([v for v in result["overlay_values"] if v != 0.0])

        summary = f"--- Script Execution Results ---\nCandles processed: {len(candles)}\nOverlay points: {overlay_count}\nSignals generated: {len(signals)}\n\n"
        summary += output if output else "(No output)"

        if signals:
            summary += "\n\n--- Signals ---\n"
            for sig in signals:
                summary += f"  {sig['type']} @ {sig['price']:.5f} (ts: {sig['timestamp']})\n"

        self.pine_output.setPlainText(summary)
        # Store results for Apply to Chart
        self._last_pine_result = result

    def _save_pine_script(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        script = self.pine_editor.toPlainText()
        if not script:
            QMessageBox.information(self, "Save Script", "Nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Pine Script", "", "Pine Script (*.pine);;Text Files (*.txt);;All Files (*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(script)
                QMessageBox.information(self, "Save Script", f"Script saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save script:\n{e}")

    def _apply_pine_script_to_chart(self) -> None:
        result = getattr(self, "_last_pine_result", None)
        if result is None:
            # Run first
            self._run_pine_script()
            result = getattr(self, "_last_pine_result", None)
        if result is None:
            return

        overlay_values = result.get("overlay_values", [])
        overlay_timestamps = result.get("overlay_timestamps", [])
        overlay_color = result.get("overlay_color", "#ffaa00")
        overlay_name = result.get("overlay_name", "Indicator")
        signals = result.get("signals", [])

        # Apply to both chart widgets if they have data
        for chart_widget in (self.chart, self.full_chart):
            if chart_widget is not None:
                chart_widget.clear_overlays()
                if overlay_values:
                    chart_widget.add_indicator_overlay(
                        values=overlay_values,
                        timestamps=overlay_timestamps,
                        color=overlay_color,
                        name=overlay_name,
                    )
                if signals:
                    chart_widget.add_signal_markers(signals)

        self.pine_output.append(f"\n--- Applied {overlay_name} overlay to chart(s) ---")
        if signals:
            self.pine_output.append(f"--- Added {len(signals)} signal marker(s) ---")

    def _clear_pine_overlay(self) -> None:
        for chart_widget in (self.chart, self.full_chart):
            if chart_widget is not None:
                chart_widget.clear_overlays()
        self.pine_output.append("--- Overlays cleared ---")

    def _get_current_candles(self) -> list[Candle]:
        """Get the most recent candle data available."""
        candles = self._latest_candles or []
        if not candles and hasattr(self, "chart"):
            # The chart may still have data even if _latest_candles is empty
            pass
        return candles

    def _build_telegram_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        runtime_card, runtime_layout = self._card(
            "Telegram Runtime",
            "Start or stop the Telegram bot here. Emojis, Unicode borders, and custom captions are fully supported.",
        )
        self.telegram_runtime_status = QLabel("Stopped")
        self.telegram_runtime_status.setObjectName("metricValue")
        self.telegram_runtime_detail = QLabel("Bot is offline. Enter a token, save your settings, then start the bot.")
        self.telegram_runtime_detail.setObjectName("helperText")
        self.telegram_runtime_detail.setWordWrap(True)
        self.telegram_start_runtime_button = QPushButton("Start Telegram Bot")
        self.telegram_start_runtime_button.setObjectName("primaryButton")
        self.telegram_stop_runtime_button = QPushButton("Stop Telegram Bot")
        self.telegram_stop_runtime_button.setObjectName("ghostButton")
        self.telegram_stop_runtime_button.setEnabled(False)
        runtime_buttons = QHBoxLayout()
        runtime_buttons.addWidget(self.telegram_start_runtime_button)
        runtime_buttons.addWidget(self.telegram_stop_runtime_button)
        runtime_layout.addWidget(self.telegram_runtime_status)
        runtime_layout.addWidget(self.telegram_runtime_detail)
        runtime_layout.addLayout(runtime_buttons)
        runtime_note = QLabel(
            "Supported commands: /start, /pairs, /signal, and /deepscan. Users can also tap the custom buttons you define below."
        )
        runtime_note.setObjectName("helperText")
        runtime_note.setWordWrap(True)
        runtime_layout.addWidget(runtime_note)

        telegram_card, telegram_layout = self._card(
            "Bot Identity",
            "Configure the Telegram engine name, token, button labels, and pair naming. These are real editable fields."
        )
        telegram_form = QFormLayout()
        self.telegram_enabled_checkbox = QCheckBox("Enable Telegram formatting and runtime")
        self.telegram_auto_broadcast_checkbox = QCheckBox("Auto-broadcast Deep Scan signals to Telegram")
        self.telegram_sound_checkbox = QCheckBox("Enable Audio Alerts")
        self.telegram_token_edit = QLineEdit()
        self.telegram_token_edit.setPlaceholderText("Telegram bot token")
        self.telegram_engine_name_edit = QLineEdit()
        self.telegram_engine_name_edit.setPlaceholderText("Eternal AI Bot (Apex Engine v214)")
        self.telegram_start_title_edit = QLineEdit()
        self.telegram_start_title_edit.setPlaceholderText("Welcome 👋")
        self.telegram_start_message_edit = QTextEdit()
        self.telegram_start_message_edit.setPlaceholderText("Use emojis, Unicode, and your own /start wording here.")
        self.telegram_start_message_edit.setFixedHeight(110)
        self.telegram_pairs_title_edit = QLineEdit()
        self.telegram_pair_template_edit = QLineEdit()
        self.telegram_deep_scan_label_edit = QLineEdit()
        self.telegram_start_button_edit = QLineEdit()
        self.telegram_status_button_edit = QLineEdit()
        self.telegram_pairs_button_edit = QLineEdit()
        self.telegram_otc_button_edit = QLineEdit()
        self.telegram_real_button_edit = QLineEdit()
        self.telegram_admin_button_edit = QLineEdit()
        self.telegram_admin_status_edit = QLineEdit()
        self.telegram_admin_charts_edit = QLineEdit()
        self.telegram_admin_broadcast_edit = QLineEdit()
        self.telegram_admin_test_capture_edit = QLineEdit()
        self.telegram_admin_chat_ids_edit = QLineEdit()
        self.telegram_admin_chat_ids_edit.setPlaceholderText("123456789, 987654321")
        self.telegram_preferred_broker_combo = QComboBox()
        self.telegram_preferred_broker_combo.addItem("Quotex", "quotex")
        self.telegram_preferred_broker_combo.addItem("IQ Option", "iq_option")
        self.telegram_preferred_broker_combo.addItem("Forex Market", "exness")
        self.telegram_use_all_brokers_checkbox = QCheckBox("Use all selected brokers")
        self.telegram_enabled_quotex_checkbox = QCheckBox("Quotex")
        self.telegram_enabled_pocket_checkbox = QCheckBox("IQ Option")
        self.telegram_enabled_exness_checkbox = QCheckBox("Forex Market")
        self.telegram_enabled_quotex_checkbox.setChecked(True)
        self.telegram_enabled_pocket_checkbox.setChecked(True)
        self.telegram_enabled_exness_checkbox.setChecked(True)
        self.telegram_scan_seconds_spin = QSpinBox()
        self.telegram_scan_seconds_spin.setRange(1, 12)
        self.telegram_scan_seconds_spin.setSuffix(" s")
        telegram_form.addRow("Bot Token", self.telegram_token_edit)
        telegram_form.addRow("Auto-Broadcast", self.telegram_auto_broadcast_checkbox)
        telegram_form.addRow("Audio Alerts", self.telegram_sound_checkbox)
        telegram_form.addRow("Engine Name", self.telegram_engine_name_edit)
        telegram_form.addRow("Start Title", self.telegram_start_title_edit)
        telegram_form.addRow("Start Message", self.telegram_start_message_edit)
        telegram_form.addRow("Pairs Title", self.telegram_pairs_title_edit)
        telegram_form.addRow("Pair Label Template", self.telegram_pair_template_edit)
        telegram_form.addRow("Deep Scan Label", self.telegram_deep_scan_label_edit)
        telegram_form.addRow("Start Button Label", self.telegram_start_button_edit)
        telegram_form.addRow("Signal Button Label", self.telegram_status_button_edit)
        telegram_form.addRow("Pairs Button Label", self.telegram_pairs_button_edit)
        telegram_form.addRow("OTC Menu Button", self.telegram_otc_button_edit)
        telegram_form.addRow("Real Menu Button", self.telegram_real_button_edit)
        telegram_form.addRow("Admin Menu Button", self.telegram_admin_button_edit)
        telegram_form.addRow("Admin Status Label", self.telegram_admin_status_edit)
        telegram_form.addRow("Admin Charts Label", self.telegram_admin_charts_edit)
        telegram_form.addRow("Admin Broadcast Label", self.telegram_admin_broadcast_edit)
        telegram_form.addRow("Admin Test Capture Label", self.telegram_admin_test_capture_edit)
        telegram_form.addRow("Admin Chat IDs", self.telegram_admin_chat_ids_edit)
        telegram_layout.addWidget(self.telegram_enabled_checkbox)
        telegram_layout.addLayout(telegram_form)

        top_row.addWidget(runtime_card, 1)
        top_row.addWidget(telegram_card, 2)
        layout.addLayout(top_row)

        broker_card, broker_layout = self._card(
            "Broker Routing",
            "Choose which broker the Telegram bot uses for signal reports, pair scans, chart captures, and admin test actions."
        )
        broker_form = QFormLayout()
        broker_form.addRow("Preferred Broker", self.telegram_preferred_broker_combo)
        broker_form.addRow("Scan Animation", self.telegram_scan_seconds_spin)
        broker_layout.addLayout(broker_form)
        broker_checks = QHBoxLayout()
        broker_checks.setSpacing(12)
        broker_checks.addWidget(self.telegram_enabled_quotex_checkbox)
        broker_checks.addWidget(self.telegram_enabled_pocket_checkbox)
        broker_checks.addWidget(self.telegram_enabled_exness_checkbox)
        broker_checks.addStretch(1)
        broker_layout.addWidget(self.telegram_use_all_brokers_checkbox)
        broker_layout.addLayout(broker_checks)
        self.telegram_broker_summary_value = QLabel("Quotex")
        self.telegram_broker_summary_value.setObjectName("metricValue")
        self.telegram_broker_summary_detail = QLabel(
            "Telegram signal generation is routed through the selected broker profile. "
            "Desktop and Telegram broker routing now stay aligned across Quotex, IQ Option, and Forex Market."
        )
        self.telegram_broker_summary_detail.setObjectName("helperText")
        self.telegram_broker_summary_detail.setWordWrap(True)
        broker_layout.addWidget(self.telegram_broker_summary_value)
        broker_layout.addWidget(self.telegram_broker_summary_detail)
        layout.addWidget(broker_card)

        broker_row = QHBoxLayout()
        broker_row.setSpacing(16)

        quotex_card, quotex_layout = self._card(
            "Quotex Capture",
            "These credentials are used by Telegram test capture and analysis helpers when you trigger a Quotex chart/report from Telegram."
        )
        quotex_form = QFormLayout()
        self.telegram_quotex_email_edit = QLineEdit()
        self.telegram_quotex_email_edit.setPlaceholderText("email@example.com")
        self.telegram_quotex_password_edit = QLineEdit()
        self.telegram_quotex_password_edit.setEchoMode(QLineEdit.Password)
        self.telegram_quotex_password_edit.setPlaceholderText("Password")
        quotex_form.addRow("Email", self.telegram_quotex_email_edit)
        quotex_form.addRow("Password", self.telegram_quotex_password_edit)
        quotex_layout.addLayout(quotex_form)

        pocket_card, pocket_layout = self._card(
            "IQ Option Capture",
            "IQ Option uses Playwright automation through its web terminal."
        )
        pocket_form = QFormLayout()
        self.telegram_pocket_url_edit = QLineEdit()
        self.telegram_pocket_url_edit.setPlaceholderText("https://iqoption.com/en/login")
        self.telegram_pocket_email_edit = QLineEdit()
        self.telegram_pocket_email_edit.setPlaceholderText("email@example.com")
        self.telegram_pocket_password_edit = QLineEdit()
        self.telegram_pocket_password_edit.setEchoMode(QLineEdit.Password)
        self.telegram_pocket_password_edit.setPlaceholderText("Password")
        pocket_form.addRow("Terminal URL", self.telegram_pocket_url_edit)
        pocket_form.addRow("Email", self.telegram_pocket_email_edit)
        pocket_form.addRow("Password", self.telegram_pocket_password_edit)
        pocket_layout.addLayout(pocket_form)

        exness_card, exness_layout = self._card(
            "Forex Market",
            "This card powers Telegram forex charts and reports through the real-market forex feed."
        )
        exness_form = QFormLayout()
        self.telegram_exness_login_edit = QLineEdit()
        self.telegram_exness_login_edit.setPlaceholderText("Unused in Forex Market mode")
        self.telegram_exness_password_edit = QLineEdit()
        self.telegram_exness_password_edit.setEchoMode(QLineEdit.Password)
        self.telegram_exness_password_edit.setPlaceholderText("Unused in Forex Market mode")
        self.telegram_exness_server_edit = QLineEdit()
        self.telegram_exness_server_edit.setPlaceholderText("Feed key or leave blank for demo")
        exness_form.addRow("Feed Key", self.telegram_exness_server_edit)
        exness_layout.addLayout(exness_form)

        broker_row.addWidget(quotex_card, 1)
        broker_row.addWidget(pocket_card, 1)
        broker_row.addWidget(exness_card, 1)
        layout.addLayout(broker_row)

        preview_card, preview_layout = self._card(
            "Telegram Preview",
            "This shows how the edited /start message will appear before you start the Telegram bot."
        )
        self.telegram_preview = QTextEdit()
        self.telegram_preview.setReadOnly(True)
        self.telegram_preview.setFixedHeight(260)
        preview_layout.addWidget(self.telegram_preview)
        layout.addWidget(preview_card)
        layout.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        settings_card, settings_layout = self._card("General Preferences", "Adjust how the desktop app behaves outside the live broker connector.")
        
        pref_form = QFormLayout()
        self.expiry_spin_settings = QSpinBox()
        self.expiry_spin_settings.setRange(60, 900)
        self.timer_spin_settings = QSpinBox()
        self.timer_spin_settings.setRange(1, 60)
        
        pref_form.addRow("Default Expiry (s)", self.expiry_spin_settings)
        pref_form.addRow("Entry Signal Timer (s)", self.timer_spin_settings)
        settings_layout.addLayout(pref_form)

        self.show_warming_pairs_checkbox = QCheckBox("Show warming / unavailable pairs in Pair Explorer")
        self.show_warming_pairs_checkbox.setChecked(True)
        settings_layout.addWidget(self.show_warming_pairs_checkbox)
        settings_note = QLabel(
            "Live mode uses browser automation for Quotex authentication and market routing. "
            "Mock mode stays available for safe UI and signal testing."
        )
        settings_note.setObjectName("helperText")
        settings_note.setWordWrap(True)
        settings_layout.addWidget(settings_note)

        layout.addWidget(settings_card)
        layout.addStretch(1)
        return page

    def _build_admin_panel_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageSurface")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        self.admin_stack = QStackedWidget()

        lock_page = QWidget()
        lock_layout = QVBoxLayout(lock_page)
        lock_layout.setSpacing(16)
        unlock_card, unlock_layout = self._card(
            "Admin Lock",
            "Enter the admin password to open the Matrix tools and server-side licensing settings."
        )
        self.admin_password_edit = QLineEdit()
        self.admin_password_edit.setEchoMode(QLineEdit.Password)
        self.admin_password_edit.setPlaceholderText("Admin password")
        self.admin_unlock_button = QPushButton("Unlock Admin Panel")
        self.admin_unlock_button.setObjectName("primaryButton")
        self.admin_unlock_status = QLabel("Admin panel is locked.")
        self.admin_unlock_status.setObjectName("helperText")
        self.admin_unlock_status.setWordWrap(True)
        unlock_layout.addWidget(self.admin_password_edit)
        unlock_layout.addWidget(self.admin_unlock_button, 0, Qt.AlignLeft)
        unlock_layout.addWidget(self.admin_unlock_status)
        lock_layout.addWidget(unlock_card)
        lock_layout.addStretch(1)

        admin_content = QWidget()
        content_layout = QVBoxLayout(admin_content)
        content_layout.setSpacing(16)

        license_admin_card, license_admin_layout = self._card(
            "License Server",
            "Configure the API endpoint the desktop app calls to validate keys and poll revocations."
        )
        admin_form = QFormLayout()
        self.license_api_url_edit = QLineEdit()
        self.license_api_url_edit.setPlaceholderText("https://license.yourdomain.com/api/v1/validate")
        self.license_api_url_edit.setReadOnly(bool(MANAGED_LICENSE_API_URL))
        self.license_api_token_edit = QLineEdit()
        self.license_api_token_edit.setEchoMode(QLineEdit.Password)
        self.license_api_token_edit.setPlaceholderText("Embedded in this build")
        self.license_api_token_edit.setReadOnly(bool(MANAGED_LICENSE_SHARED_TOKEN))
        self.license_poll_spin = QSpinBox()
        self.license_poll_spin.setRange(5, 300)
        self.license_poll_spin.setSuffix(" s")
        self.license_machine_lock_checkbox = QCheckBox("Lock licenses to machine ID")
        self.license_enabled_checkbox = QCheckBox()
        self.license_enabled_checkbox.setVisible(False)
        self.license_key_edit = QLineEdit()
        self.license_key_edit.setVisible(False)
        self.license_remember_checkbox = QCheckBox()
        self.license_remember_checkbox.setVisible(False)
        admin_form.addRow("API URL", self.license_api_url_edit)
        admin_form.addRow("API Token", self.license_api_token_edit)
        admin_form.addRow("Poll Interval", self.license_poll_spin)
        license_admin_layout.addLayout(admin_form)
        license_admin_layout.addWidget(self.license_machine_lock_checkbox)
        
        # Machine ID and status display
        info_layout = QHBoxLayout()
        machine_id_label = QLabel("Machine ID:")
        machine_id_label.setObjectName("helperText")
        self.license_machine_id_value = QLabel(machine_display_id())
        self.license_machine_id_value.setObjectName("metricValue")
        self.license_machine_id_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(machine_id_label)
        info_layout.addWidget(self.license_machine_id_value)
        info_layout.addStretch(1)
        license_admin_layout.addLayout(info_layout)
        
        status_layout = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setObjectName("helperText")
        self.license_status_value = QLabel("Not checked yet")
        self.license_status_value.setObjectName("metricValue")
        self.license_status_value.setWordWrap(True)
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.license_status_value)
        status_layout.addStretch(1)
        license_admin_layout.addLayout(status_layout)
        
        license_admin_note = QLabel(
            "Normal validation is built into the desktop app. Admin actions still use the embedded shared token behind this locked panel."
        )
        license_admin_note.setObjectName("helperText")
        license_admin_note.setWordWrap(True)
        license_admin_layout.addWidget(license_admin_note)
        content_layout.addWidget(license_admin_card)

        license_manager_card, license_manager_layout = self._card(
            "License Manager",
            "Generate, create, revoke, and inspect license keys from the locked admin panel."
        )
        manager_form = QFormLayout()
        self.license_admin_key_edit = QLineEdit()
        self.license_admin_key_edit.setPlaceholderText("ETQ-XXXX-XXXX-XXXX or a custom server key")
        self.license_duration_days_spin = QSpinBox()
        self.license_duration_days_spin.setRange(1, 3650)
        self.license_duration_days_spin.setValue(30)
        self.license_duration_days_spin.setSuffix(" days")
        self.license_lifetime_checkbox = QCheckBox("Lifetime license")
        self.license_machine_lock_checkbox_admin = QCheckBox("Lock to specific machine (optional)")
        self.license_machine_id_edit = QLineEdit()
        self.license_machine_id_edit.setPlaceholderText("Leave empty for no machine binding, or paste a Machine ID")
        self.license_notes_edit = QTextEdit()
        self.license_notes_edit.setPlaceholderText("Optional note, customer name, or internal memo")
        self.license_notes_edit.setFixedHeight(72)
        manager_form.addRow("License Key", self.license_admin_key_edit)
        manager_form.addRow("Duration", self.license_duration_days_spin)
        manager_form.addRow("", self.license_lifetime_checkbox)
        manager_form.addRow("", self.license_machine_lock_checkbox_admin)
        manager_form.addRow("Machine ID (optional)", self.license_machine_id_edit)
        manager_form.addRow("Notes", self.license_notes_edit)
        license_manager_layout.addLayout(manager_form)
        self.license_admin_key_length_value = QLabel("Length: 0 characters")
        self.license_admin_key_length_value.setObjectName("helperText")
        self.license_admin_key_length_value.setWordWrap(True)
        self.license_admin_master_value = QLabel(
            "Admin actions require the shared API token configured in your environment."
        )
        self.license_admin_master_value.setObjectName("helperText")
        self.license_admin_master_value.setWordWrap(True)
        manager_buttons = QHBoxLayout()
        self.license_generate_button = QPushButton("Generate Key")
        self.license_generate_button.setObjectName("ghostButton")
        self.license_create_button = QPushButton("Create License")
        self.license_create_button.setObjectName("primaryButton")
        self.license_revoke_button = QPushButton("Revoke License")
        self.license_revoke_button.setObjectName("ghostButton")
        self.license_delete_button = QPushButton("Delete License")
        self.license_delete_button.setObjectName("ghostButton")
        self.license_delete_button.setStyleSheet("color: #e53e3e;")
        self.license_refresh_button = QPushButton("Refresh Licenses")
        self.license_refresh_button.setObjectName("ghostButton")
        manager_buttons.addWidget(self.license_generate_button)
        manager_buttons.addWidget(self.license_create_button)
        manager_buttons.addWidget(self.license_revoke_button)
        manager_buttons.addWidget(self.license_delete_button)
        manager_buttons.addWidget(self.license_refresh_button)
        manager_buttons.addStretch(1)
        self.license_admin_status = QLabel("No admin license action has been run yet.")
        self.license_admin_status.setObjectName("helperText")
        self.license_admin_status.setWordWrap(True)
        self.license_admin_list = QTextEdit()
        self.license_admin_list.setReadOnly(True)
        self.license_admin_list.setPlaceholderText("Created and revoked licenses will appear here.")
        self.license_admin_list.setMinimumHeight(160)
        license_manager_layout.addWidget(self.license_admin_key_length_value)
        license_manager_layout.addWidget(self.license_admin_master_value)
        license_manager_layout.addLayout(manager_buttons)
        license_manager_layout.addWidget(self.license_admin_status)
        license_manager_layout.addWidget(self.license_admin_list)
        content_layout.addWidget(license_manager_card)

        # Master Switch Card
        master_card, master_layout = self._card(
            "Multi-Session Matrix",
            "Run multiple Quotex sessions in parallel to monitor all pairs simultaneously."
        )
        self.matrix_enabled_checkbox = QCheckBox("Enable Multi-Session Matrix")
        self.matrix_enabled_checkbox.setChecked(False)
        master_layout.addWidget(self.matrix_enabled_checkbox)
        master_note = QLabel(
            "When OFF: Uses standard single-session mode.\n"
            "When ON: Distributes pairs across multiple browser sessions."
        )
        master_note.setObjectName("helperText")
        master_note.setWordWrap(True)
        master_layout.addWidget(master_note)
        content_layout.addWidget(master_card)

        # Account Manager Card
        account_card, account_layout = self._card(
            "Worker Accounts",
            "Select which accounts to activate in the Matrix."
        )
        self.worker_checkboxes: list[tuple[QCheckBox, QLineEdit, QLineEdit]] = []
        workers = [
            ("Worker 1", "", ""),
            ("Worker 2", "", ""),
            ("Worker 3", "", ""),
        ]
        for label_text, email, password in workers:
            row = QHBoxLayout()
            cb = QCheckBox(label_text)
            email_edit = QLineEdit()
            email_edit.setText(email)
            email_edit.setPlaceholderText("Email")
            email_edit.setMaximumWidth(280)
            pass_edit = QLineEdit()
            pass_edit.setText(password)
            pass_edit.setEchoMode(QLineEdit.Password)
            pass_edit.setPlaceholderText("Password")
            pass_edit.setMaximumWidth(180)
            row.addWidget(cb)
            row.addWidget(email_edit)
            row.addWidget(pass_edit)
            row.addStretch()
            account_layout.addLayout(row)
            self.worker_checkboxes.append((cb, email_edit, pass_edit))
        content_layout.addWidget(account_card)

        # Status Card
        status_card, status_layout = self._card("Matrix Status", "Current state of the Multi-Session Matrix.")
        self.matrix_status_label = QLabel("Matrix is OFF. Using single-session mode.")
        self.matrix_status_label.setObjectName("metricValue")
        self.matrix_status_label.setWordWrap(True)
        status_layout.addWidget(self.matrix_status_label)
        self.matrix_workers_label = QLabel("No active workers.")
        self.matrix_workers_label.setObjectName("helperText")
        self.matrix_workers_label.setWordWrap(True)
        status_layout.addWidget(self.matrix_workers_label)
        content_layout.addWidget(status_card)

        # Connect/Disconnect buttons for Matrix
        matrix_button_row = QHBoxLayout()
        self.matrix_connect_button = QPushButton("Start Matrix")
        self.matrix_connect_button.setObjectName("primaryButton")
        self.matrix_disconnect_button = QPushButton("Stop Matrix")
        self.matrix_disconnect_button.setObjectName("ghostButton")
        matrix_button_row.addWidget(self.matrix_connect_button)
        matrix_button_row.addWidget(self.matrix_disconnect_button)
        matrix_button_row.addStretch()
        content_layout.addLayout(matrix_button_row)
        content_layout.addStretch(1)

        self.admin_stack.addWidget(lock_page)
        self.admin_stack.addWidget(admin_content)
        layout.addWidget(self.admin_stack, 1)
        return page

    def _build_connect_card(self) -> QWidget:
        card, layout = self._card("Connection Center", "Choose a broker session, save credentials, or run a multi-broker live feed")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Mock Sandbox", "mock")
        self.provider_combo.addItem("Quotex", "live")
        self.provider_combo.addItem("IQ Option", "iq_option")
        self.provider_combo.addItem("Forex Market", "exness")
        self.provider_combo.addItem("Multi-Broker Feed", "multi")
        self.provider_hint = QLabel()
        self.provider_hint.setObjectName("helperText")
        self.provider_hint.setWordWrap(True)
        top_form = QFormLayout()
        top_form.setSpacing(8)
        top_form.addRow("Provider", self.provider_combo)
        layout.addLayout(top_form)
        layout.addWidget(self.provider_hint)

        self.provider_stack = QStackedWidget()
        self.provider_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.provider_stack.addWidget(self._build_mock_provider_panel())
        self.provider_stack.addWidget(self._build_live_provider_panel())
        self.provider_stack.addWidget(self._build_pocket_option_provider_panel())
        self.provider_stack.addWidget(self._build_exness_provider_panel())
        self.provider_stack.addWidget(self._build_multi_broker_provider_panel())
        layout.addWidget(self.provider_stack)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.connect_button = QPushButton("Start Session")
        self.connect_button.setObjectName("primaryButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("ghostButton")
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)
        layout.addLayout(button_row)
        return card

    def _build_mock_provider_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("lineSurface")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel("Mock Sandbox runs a simulated Quotex-like session. No email, password, or broker login is required.")
        label.setObjectName("helperText")
        label.setWordWrap(True)
        layout.addWidget(label)
        return frame

    def _build_live_provider_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("lineSurface")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        note = QLabel(
            "Live mode opens a browser for Quotex login. If Quotex emails a verification PIN, paste it into the Email PIN field before connecting."
        )
        note.setObjectName("helperText")
        note.setWordWrap(True)
        layout.addWidget(note)
        
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("email@example.com")
        self.email_edit.setClearButtonEnabled(True)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Password")
        self.pin_code_edit = QLineEdit()
        self.pin_code_edit.setPlaceholderText("Email PIN / verification code")
        self.account_mode_combo = QComboBox()
        self.account_mode_combo.setMinimumWidth(150)
        self.account_mode_combo.addItems(["PRACTICE", "REAL"])
        form.addRow("Email", self.email_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("Email PIN", self.pin_code_edit)
        form.addRow("Account", self.account_mode_combo)
        layout.addLayout(form)
        
        self.remember_checkbox = QCheckBox("Remember password locally")
        self.headless_checkbox = QCheckBox("Background browser mode (faster but invisible)")
        self.headless_checkbox.setChecked(False)
        layout.addWidget(self.remember_checkbox)
        layout.addWidget(self.headless_checkbox)

        # Browser engine and Data source selectors - combined in one row
        options_row = QHBoxLayout()
        options_row.setSpacing(12)
        
        engine_label = QLabel("Browser:")
        engine_label.setObjectName("helperText")
        self.browser_engine_combo = QComboBox()
        self.browser_engine_combo.setMinimumWidth(160)
        self.browser_engine_combo.addItem("Selenium (Recommended)", "selenium")
        self.browser_engine_combo.addItem("Playwright (Experimental)", "playwright")
        
        data_label = QLabel("Data:")
        data_label.setObjectName("helperText")
        self.data_source_combo = QComboBox()
        self.data_source_combo.setMinimumWidth(160)
        self.data_source_combo.addItem("Browser Activation", "browser")
        self.data_source_combo.addItem("WebSocket Pool (Fast)", "websocket")
        
        options_row.addWidget(engine_label)
        options_row.addWidget(self.browser_engine_combo)
        options_row.addWidget(data_label)
        options_row.addWidget(self.data_source_combo)
        options_row.addStretch()
        layout.addLayout(options_row)
        
        return frame

    def _build_pocket_option_provider_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("lineSurface")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        note = QLabel(
            "IQ Option mode opens the broker terminal in a Chromium automation session, keeps a live page feed available, "
            "and routes manual buy or sell clicks through the authenticated browser page."
        )
        note.setObjectName("helperText")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.pocket_url_edit = QLineEdit()
        self.pocket_url_edit.setPlaceholderText("https://iqoption.com/en/login")
        self.pocket_url_edit.setClearButtonEnabled(True)
        self.pocket_email_edit = QLineEdit()
        self.pocket_email_edit.setPlaceholderText("email@example.com")
        self.pocket_email_edit.setClearButtonEnabled(True)
        self.pocket_password_edit = QLineEdit()
        self.pocket_password_edit.setEchoMode(QLineEdit.Password)
        self.pocket_password_edit.setPlaceholderText("Password")
        form.addRow("Login URL", self.pocket_url_edit)
        form.addRow("Email", self.pocket_email_edit)
        form.addRow("Password", self.pocket_password_edit)
        layout.addLayout(form)
        self.pocket_note = QLabel("Use the same Pair Explorer and trade ticket after the IQ Option session is connected.")
        self.pocket_note.setObjectName("helperText")
        self.pocket_note.setWordWrap(True)
        layout.addWidget(self.pocket_note)
        return frame

    def _build_exness_provider_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("lineSurface")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        note = QLabel(
            "Forex Market is a compact data-only connector for real forex pairs. Add a feed key, connect once, and keep the chart engine focused on clean price data."
        )
        note.setObjectName("helperText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.exness_login_edit = QLineEdit(frame)
        self.exness_password_edit = QLineEdit(frame)
        self.exness_password_edit.setEchoMode(QLineEdit.Password)
        self.exness_server_edit = QLineEdit(frame)
        self.exness_server_edit.setPlaceholderText("Paste your Forex Market feed key")
        self.exness_server_edit.setClearButtonEnabled(True)
        self.exness_login_edit.hide()
        self.exness_password_edit.hide()

        key_form = QFormLayout()
        key_form.setContentsMargins(0, 0, 0, 0)
        key_form.addRow("Feed Key", self.exness_server_edit)
        layout.addLayout(key_form)

        status_frame = QFrame()
        status_frame.setObjectName("metricTile")
        status_layout = QGridLayout(status_frame)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setHorizontalSpacing(14)
        status_layout.setVerticalSpacing(6)

        profile_label = QLabel("Profile")
        profile_label.setObjectName("metricLabel")
        self.exness_profile_value = QLabel("Forex feed ready")
        self.exness_profile_value.setObjectName("metricValue")
        self.exness_profile_value.setWordWrap(True)

        server_label = QLabel("Server")
        server_label.setObjectName("metricLabel")
        self.exness_server_value = QLabel("Feed key required")
        self.exness_server_value.setObjectName("metricValue")
        self.exness_server_value.setWordWrap(True)

        runtime_label = QLabel("Runtime")
        runtime_label.setObjectName("metricLabel")
        self.exness_runtime_value = QLabel("Auto-connect with demo or saved feed key")
        self.exness_runtime_value.setObjectName("metricValue")
        self.exness_runtime_value.setWordWrap(True)

        status_layout.addWidget(profile_label, 0, 0)
        status_layout.addWidget(self.exness_profile_value, 0, 1)
        status_layout.addWidget(server_label, 1, 0)
        status_layout.addWidget(self.exness_server_value, 1, 1)
        status_layout.addWidget(runtime_label, 2, 0)
        status_layout.addWidget(self.exness_runtime_value, 2, 1)
        layout.addWidget(status_frame)

        self.exness_note = QLabel("No broker login is required here. This provider is minimized to feed the chart and market list only.")
        self.exness_note.setObjectName("helperText")
        self.exness_note.setWordWrap(True)
        layout.addWidget(self.exness_note)
        return frame

    def _build_multi_broker_provider_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("lineSurface")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        note = QLabel(
            "Multi-Broker Feed connects the selected brokers together. Live prices and candles can come from any selected source, "
            "while manual trade submission uses the primary execution broker you choose below."
        )
        note.setObjectName("helperText")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.multi_use_all_checkbox = QCheckBox("Use all available brokers")
        self.multi_quotex_checkbox = QCheckBox("Quotex")
        self.multi_pocket_checkbox = QCheckBox("IQ Option")
        self.multi_exness_checkbox = QCheckBox("Forex Market")
        self.multi_quotex_checkbox.setChecked(True)
        self.multi_pocket_checkbox.setChecked(True)
        self.multi_exness_checkbox.setChecked(True)
        layout.addWidget(self.multi_use_all_checkbox)
        checks = QHBoxLayout()
        checks.setSpacing(10)
        checks.addWidget(self.multi_quotex_checkbox)
        checks.addWidget(self.multi_exness_checkbox)
        checks.addStretch(1)
        layout.addLayout(checks)
        form = QFormLayout()
        self.multi_primary_broker_combo = QComboBox()
        self.multi_primary_broker_combo.addItem("Quotex", "quotex")
        self.multi_primary_broker_combo.addItem("Forex Market", "exness")
        form.addRow("Primary Execution Broker", self.multi_primary_broker_combo)
        layout.addLayout(form)
        self.multi_note = QLabel(
            "Keep Quotex or IQ Option ready for execution before starting a multi-broker session. Forex Market supplies data only, so use it as a feed source rather than the execution broker."
        )
        self.multi_note.setObjectName("helperText")
        self.multi_note.setWordWrap(True)
        layout.addWidget(self.multi_note)
        return frame

    def _build_automation_card(self) -> QWidget:
        card, layout = self._card("Automation", "Arm or pause the in-app auto trader")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.auto_trade_button = QPushButton("Arm Auto Trading")
        self.auto_trade_button.setObjectName("primaryButton")
        self.auto_status_label = QLabel("Automation is paused. It will not open trades until you arm it.")
        self.auto_status_label.setObjectName("helperText")
        self.auto_status_label.setWordWrap(True)
        layout.addWidget(self.auto_trade_button)
        layout.addWidget(self.auto_status_label)
        return card

    def _build_trade_card(self) -> QWidget:
        card, layout = self._card("Trade Ticket", "Manual execution controls")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        form = QFormLayout()
        self.trade_target_value = QLabel("--")
        self.trade_target_value.setObjectName("metricValue")
        self.duration_combo = QComboBox()
        self.duration_combo.addItem("1 Minute", 60)
        self.duration_combo.addItem("2 Minutes", 120)
        self.duration_combo.addItem("5 Minutes", 300)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(1, 10_000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSingleStep(1.0)
        form.addRow("Selected Market", self.trade_target_value)
        form.addRow("Trade Duration", self.duration_combo)
        form.addRow("Trade Amount", self.amount_spin)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.buy_button = QPushButton("CALL")
        self.buy_button.setObjectName("buyButton")
        self.sell_button = QPushButton("PUT")
        self.sell_button.setObjectName("sellButton")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("ghostButton")
        row.addWidget(self.buy_button)
        row.addWidget(self.sell_button)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        return card

    def _build_watchlist_card(self) -> QWidget:
        card, layout = self._card(
            "Pair Explorer",
            "Search, review, and select markets from the active provider. Forex Market loads real-market forex pairs and keeps the selected chart focused on live forex candles."
        )
        card.setMinimumHeight(560)
        search_row = QHBoxLayout()
        self.asset_search_edit = QLineEdit()
        self.asset_search_edit.setPlaceholderText("Search forex pairs like EUR/USD, GBP/JPY, AUD/CAD...")
        self.watch_category_combo = QComboBox()
        self.watch_category_combo.addItem("All Markets", "all")
        self.watch_category_combo.addItem("Binary / OTC", "binary")
        self.watch_category_combo.addItem("Forex", "forex")
        self.watch_category_combo.addItem("Other", "other")
        self.watch_status_label = QLabel("Waiting for pair data")
        self.watch_status_label.setObjectName("helperText")
        search_row.addWidget(self.asset_search_edit, 1)
        search_row.addWidget(self.watch_category_combo, 0)
        search_row.addWidget(self.watch_status_label)
        layout.addLayout(search_row)
        self.watch_table = QTableWidget(0, 6)
        self.watch_table.setHorizontalHeaderLabels(["Market", "Category", "Payout", "Feed", "Open", "Last"])
        self.watch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.watch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for section in (2, 3, 4, 5):
            self.watch_table.horizontalHeader().setSectionResizeMode(section, QHeaderView.ResizeToContents)
        self.watch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.watch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.watch_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.watch_table.verticalHeader().setVisible(False)
        self.watch_table.setAlternatingRowColors(True)
        self.watch_table.setShowGrid(False)
        self.watch_table.setWordWrap(False)
        self.watch_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.watch_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.watch_table.setMinimumHeight(480)
        layout.addWidget(self.watch_table, 1)
        return card

    def _build_summary_card(self, title: str, value: str, value_attr: str, helper_attr: str) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        helper_label = QLabel("Waiting for updates")
        helper_label.setObjectName("helperText")
        helper_label.setWordWrap(True)
        setattr(self, value_attr, value_label)
        setattr(self, helper_attr, helper_label)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(helper_label)
        return card

    def _card(self, title: str, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("helperText")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
        return card, layout

    def _wire_controller(self) -> None:
        self.controller.status_changed.connect(self._set_status)
        self.controller.balance_changed.connect(self._update_balance)
        self.controller.account_changed.connect(self._update_account)
        self.controller.assets_changed.connect(self._update_assets)
        self.controller.candles_changed.connect(self._update_chart)
        self.controller.trade_added.connect(self._append_trade)
        self.controller.trade_resolved.connect(self._resolve_trade)
        self.controller.stats_changed.connect(self._update_stats)
        self.controller.log_added.connect(self._append_log)
        self.controller.settings_loaded.connect(self._apply_settings)
        self.controller.connection_changed.connect(self._update_connection_buttons)
        self.controller.telegram_state_changed.connect(self._update_telegram_runtime_state)
        self.controller.learning_changed.connect(self._update_learning_state)
        self.controller.deep_scan_changed.connect(self._on_deep_scan_changed)
        self.controller.deep_scan_finished.connect(self._update_deep_scan)
        self.controller.continuous_signal_changed.connect(self._update_continuous_signal)
        self.controller.market_health_changed.connect(self._update_market_health)
        self.controller.license_state_changed.connect(self._update_license_state)
        self.controller.license_invalidated.connect(self._handle_license_invalidation)
        
        # Wire up Deep Scan mode controls
        self.scan_mode_combo.currentIndexChanged.connect(self._scan_mode_changed)
        self.sniper_pairs_edit.editingFinished.connect(self._sniper_pairs_changed)
        
        # Matrix button connections
        self.matrix_connect_button.clicked.connect(self._matrix_start_clicked)
        self.matrix_disconnect_button.clicked.connect(self._matrix_stop_clicked)
        self.matrix_enabled_checkbox.stateChanged.connect(self._matrix_toggled)
        self.controller.pin_code_required.connect(self._handle_pin_request)

    def _collect_settings(self) -> AppSettings:
        settings = self.controller.settings
        selected_provider = str(self.provider_combo.currentData() or "mock")
        settings.connection.provider = self.provider_combo.currentData()
        settings.connection.email = self.email_edit.text().strip()
        settings.connection.password = self.password_edit.text()
        settings.connection.email_pin = self.pin_code_edit.text().strip()
        settings.connection.quotex_email = settings.connection.email
        settings.connection.quotex_password = settings.connection.password
        settings.connection.quotex_email_pin = settings.connection.email_pin
        iq_url = self.pocket_url_edit.text().strip() or "https://iqoption.com/en/login"
        if selected_provider in {"iq_option", "pocket_option"} and "pocketoption.com" in iq_url.lower():
            iq_url = "https://iqoption.com/en/login"
        settings.connection.pocket_option_url = iq_url
        settings.connection.pocket_option_email = self.pocket_email_edit.text().strip()
        settings.connection.pocket_option_password = self.pocket_password_edit.text()
        settings.connection.exness_login = self.exness_login_edit.text().strip()
        settings.connection.exness_password = self.exness_password_edit.text()
        settings.connection.exness_server = self.exness_server_edit.text().strip()
        enabled_live_brokers = []
        if self.multi_quotex_checkbox.isChecked():
            enabled_live_brokers.append("quotex")
        if self.multi_pocket_checkbox.isChecked():
            enabled_live_brokers.append("iq_option")
        if self.multi_exness_checkbox.isChecked():
            enabled_live_brokers.append("exness")
        settings.connection.enabled_brokers = ",".join(enabled_live_brokers)
        settings.connection.use_all_brokers = self.multi_use_all_checkbox.isChecked()
        settings.connection.primary_broker = str(self.multi_primary_broker_combo.currentData() or "quotex")
        settings.connection.remember_password = self.remember_checkbox.isChecked() or (
            settings.connection.provider == "live"
            and bool(settings.connection.email)
            and bool(settings.connection.password)
        )
        settings.connection.headless = self.headless_checkbox.isChecked()
        settings.connection.browser_engine = str(self.browser_engine_combo.currentData() or "selenium")
        settings.connection.data_source = str(self.data_source_combo.currentData() or "browser")
        settings.connection.account_mode = self.account_mode_combo.currentText()
        settings.connection.selected_asset = str(self.asset_combo.currentData() or self.asset_combo.currentText() or settings.connection.selected_asset)
        settings.connection.candle_period = int(self.period_combo.currentData() or 60)
        settings.connection.trade_duration = int(self.duration_combo.currentData() or 60)
        settings.connection.trade_amount = float(self.amount_spin.value())
        settings.strategy.preferred_expiry_seconds = int(self.expiry_spin.value())
        settings.strategy.entry_timer_seconds = int(self.timer_spin.value())
        settings.strategy.fast_ema = int(self.fast_ema_spin.value())
        settings.strategy.slow_ema = int(self.slow_ema_spin.value())
        settings.strategy.rsi_period = int(self.rsi_spin.value())
        settings.strategy.min_confidence = float(self.confidence_spin.value())
        settings.strategy.auto_trade_enabled = self.auto_trade_checkbox.isChecked()
        settings.strategy.deep_scan_min_confidence = max(0.5, float(self.confidence_spin.value()) - 0.03)
        settings.strategy.preferred_expiry_seconds = int(self.preferred_expiry_combo.currentData() or 60)
        settings.strategy.sticky_signal_seconds = int(self.sticky_signal_spin.value())
        settings.strategy.learning_enabled = self.learning_enabled_checkbox.isChecked()
        settings.strategy.learning_interval_seconds = int(self.learning_interval_spin.value())
        settings.strategy.learning_verify_seconds = int(self.learning_verify_combo.currentData() or 60)
        settings.risk.stop_profit = float(self.stop_profit_spin.value())
        settings.risk.stop_loss = float(self.stop_loss_spin.value())
        settings.risk.max_consecutive_losses = int(self.max_losses_spin.value())
        settings.risk.cooldown_seconds = int(self.cooldown_spin.value())
        settings.ui.auto_refresh_seconds = int(self.refresh_interval_spin.value())
        settings.strategy.preferred_expiry_seconds = int(self.expiry_spin_settings.value())
        settings.strategy.entry_timer_seconds = int(self.timer_spin_settings.value())
        settings.ui.show_warming_pairs = self.show_warming_pairs_checkbox.isChecked()
        settings.telegram.enabled = self.telegram_enabled_checkbox.isChecked()
        settings.telegram.auto_broadcast = self.telegram_auto_broadcast_checkbox.isChecked()
        settings.telegram.sound_enabled = self.telegram_sound_checkbox.isChecked()
        settings.telegram.bot_token = self.telegram_token_edit.text().strip()
        settings.telegram.engine_name = self.telegram_engine_name_edit.text().strip()
        settings.telegram.start_title = self.telegram_start_title_edit.text().strip()
        settings.telegram.start_message = self.telegram_start_message_edit.toPlainText().strip()
        settings.telegram.pairs_title = self.telegram_pairs_title_edit.text().strip()
        settings.telegram.pair_label_template = self.telegram_pair_template_edit.text().strip()
        settings.telegram.deep_scan_label = self.telegram_deep_scan_label_edit.text().strip()
        settings.telegram.start_button_text = self.telegram_start_button_edit.text().strip()
        settings.telegram.status_button_text = self.telegram_status_button_edit.text().strip()
        settings.telegram.pairs_button_text = self.telegram_pairs_button_edit.text().strip()
        settings.telegram.otc_button_text = self.telegram_otc_button_edit.text().strip()
        settings.telegram.real_button_text = self.telegram_real_button_edit.text().strip()
        settings.telegram.admin_button_text = self.telegram_admin_button_edit.text().strip()
        settings.telegram.admin_status_text = self.telegram_admin_status_edit.text().strip()
        settings.telegram.admin_charts_text = self.telegram_admin_charts_edit.text().strip()
        settings.telegram.admin_broadcast_text = self.telegram_admin_broadcast_edit.text().strip()
        settings.telegram.admin_test_capture_text = self.telegram_admin_test_capture_edit.text().strip()
        settings.telegram.admin_chat_ids = self.telegram_admin_chat_ids_edit.text().strip()
        settings.telegram.preferred_broker = str(self.telegram_preferred_broker_combo.currentData() or "quotex")
        enabled_brokers = []
        if self.telegram_enabled_quotex_checkbox.isChecked():
            enabled_brokers.append("quotex")
        if self.telegram_enabled_pocket_checkbox.isChecked():
            enabled_brokers.append("iq_option")
        if self.telegram_enabled_exness_checkbox.isChecked():
            enabled_brokers.append("exness")
        settings.telegram.enabled_brokers = ",".join(enabled_brokers)
        settings.telegram.use_all_brokers = self.telegram_use_all_brokers_checkbox.isChecked()
        settings.telegram.scan_animation_seconds = int(self.telegram_scan_seconds_spin.value())
        settings.telegram.quotex_email = self.telegram_quotex_email_edit.text().strip()
        settings.telegram.quotex_password = self.telegram_quotex_password_edit.text()
        telegram_iq_url = self.telegram_pocket_url_edit.text().strip() or "https://iqoption.com/en/login"
        if settings.telegram.preferred_broker == "iq_option" and "pocketoption.com" in telegram_iq_url.lower():
            telegram_iq_url = "https://iqoption.com/en/login"
        settings.telegram.pocket_option_url = telegram_iq_url
        settings.telegram.pocket_option_email = self.telegram_pocket_email_edit.text().strip()
        settings.telegram.pocket_option_password = self.telegram_pocket_password_edit.text()
        settings.telegram.exness_login = self.telegram_exness_login_edit.text().strip()
        settings.telegram.exness_password = self.telegram_exness_password_edit.text()
        settings.telegram.exness_server = self.telegram_exness_server_edit.text().strip()
        
        # License settings are managed by the startup gate/admin panel. Hidden
        # compatibility widgets keep older settings snapshots working.
        settings.license.enabled = (
            self.license_enabled_checkbox.isChecked()
            if hasattr(self, "license_enabled_checkbox") and self.license_enabled_checkbox.isChecked()
            else self.controller.settings.license.enabled
        )
        settings.license.license_key = (
            self.license_key_edit.text().strip()
            if hasattr(self, "license_key_edit") and self.license_key_edit.text().strip()
            else self.controller.settings.license.license_key
        )
        settings.license.remember_license_key = (
            self.license_remember_checkbox.isChecked()
            if hasattr(self, "license_remember_checkbox") and self.license_remember_checkbox.isChecked()
            else self.controller.settings.license.remember_license_key
        )
        
        settings.license.api_url = self.license_api_url_edit.text().strip() or MANAGED_LICENSE_API_URL
        settings.license.api_token = self.license_api_token_edit.text().strip() or MANAGED_LICENSE_SHARED_TOKEN
        settings.license.poll_seconds = int(self.license_poll_spin.value())
        settings.license.machine_lock_enabled = self.license_machine_lock_checkbox.isChecked()
        
        # Matrix settings
        settings.matrix.enabled = self.matrix_enabled_checkbox.isChecked()
        for i, (cb, email_edit, pass_edit) in enumerate(self.worker_checkboxes):
            if i < len(settings.matrix.workers):
                settings.matrix.workers[i].enabled = cb.isChecked()
                settings.matrix.workers[i].email = email_edit.text().strip()
                settings.matrix.workers[i].password = pass_edit.text()
        
        return settings

    def _apply_settings(self, settings: AppSettings) -> None:
        provider_map = {"mock": 0, "live": 1, "quotex": 1, "iq_option": 2, "pocket_option": 2, "exness": 3, "multi": 4}
        self.provider_combo.setCurrentIndex(provider_map.get(settings.connection.provider, 0))
        self.email_edit.setText(settings.connection.quotex_email or settings.connection.email)
        self.password_edit.setText(settings.connection.quotex_password or settings.connection.password)
        self.pin_code_edit.setText(settings.connection.quotex_email_pin or settings.connection.email_pin)
        iq_url = settings.connection.pocket_option_url or "https://iqoption.com/en/login"
        if "pocketoption.com" in str(iq_url).lower():
            iq_url = "https://iqoption.com/en/login"
        self.pocket_url_edit.setText(iq_url)
        self.pocket_email_edit.setText(settings.connection.pocket_option_email)
        self.pocket_password_edit.setText(settings.connection.pocket_option_password)
        self.exness_login_edit.setText(settings.connection.exness_login)
        self.exness_password_edit.setText(settings.connection.exness_password)
        self.exness_server_edit.setText(settings.connection.exness_server)
        self._refresh_exness_summary(settings)
        self.remember_checkbox.setChecked(settings.connection.remember_password)
        self.headless_checkbox.setChecked(bool(settings.connection.headless))
        self._set_combo_data(self.browser_engine_combo, settings.connection.browser_engine or "selenium")
        self._set_combo_data(self.data_source_combo, settings.connection.data_source or "browser")
        self.account_mode_combo.setCurrentText(settings.connection.account_mode)
        enabled_live_brokers = {part.strip() for part in str(settings.connection.enabled_brokers or "").split(",") if part.strip()}
        self.multi_quotex_checkbox.setChecked("quotex" in enabled_live_brokers or not enabled_live_brokers)
        self.multi_pocket_checkbox.setChecked("iq_option" in enabled_live_brokers or not enabled_live_brokers)
        self.multi_exness_checkbox.setChecked("exness" in enabled_live_brokers or not enabled_live_brokers)
        self.multi_use_all_checkbox.setChecked(bool(settings.connection.use_all_brokers))
        self._set_combo_data(self.multi_primary_broker_combo, settings.connection.primary_broker)
        self.amount_spin.setValue(settings.connection.trade_amount)
        self.expiry_spin.setValue(int(settings.strategy.preferred_expiry_seconds or 120))
        self.timer_spin.setValue(int(settings.strategy.entry_timer_seconds or 5))
        self.fast_ema_spin.setValue(settings.strategy.fast_ema)
        self.slow_ema_spin.setValue(settings.strategy.slow_ema)
        self.rsi_spin.setValue(settings.strategy.rsi_period)
        self.confidence_spin.setValue(settings.strategy.min_confidence)
        self.auto_trade_checkbox.setChecked(settings.strategy.auto_trade_enabled)
        self.sticky_signal_spin.setValue(int(settings.strategy.sticky_signal_seconds or 75))
        self.learning_enabled_checkbox.setChecked(settings.strategy.learning_enabled)
        self.learning_interval_spin.setValue(int(settings.strategy.learning_interval_seconds or 45))
        self._set_combo_data(self.learning_verify_combo, int(settings.strategy.learning_verify_seconds or 120))
        self.stop_profit_spin.setValue(settings.risk.stop_profit)
        self.stop_loss_spin.setValue(settings.risk.stop_loss)
        self.max_losses_spin.setValue(settings.risk.max_consecutive_losses)
        self.cooldown_spin.setValue(settings.risk.cooldown_seconds)
        self.refresh_interval_spin.setValue(settings.ui.auto_refresh_seconds)
        self.expiry_spin_settings.setValue(int(settings.strategy.preferred_expiry_seconds or 120))
        self.timer_spin_settings.setValue(int(settings.strategy.entry_timer_seconds or 5))
        self.show_warming_pairs_checkbox.setChecked(settings.ui.show_warming_pairs)
        self.telegram_enabled_checkbox.setChecked(settings.telegram.enabled)
        self.telegram_auto_broadcast_checkbox.setChecked(settings.telegram.auto_broadcast)
        self.telegram_sound_checkbox.setChecked(getattr(settings.telegram, 'sound_enabled', True))
        self.telegram_token_edit.setText(settings.telegram.bot_token)
        self.telegram_engine_name_edit.setText(settings.telegram.engine_name)
        self.telegram_start_title_edit.setText(settings.telegram.start_title)
        self.telegram_start_message_edit.setPlainText(settings.telegram.start_message)
        self.telegram_pairs_title_edit.setText(settings.telegram.pairs_title)
        self.telegram_pair_template_edit.setText(settings.telegram.pair_label_template)
        self.telegram_deep_scan_label_edit.setText(settings.telegram.deep_scan_label)
        self.telegram_start_button_edit.setText(settings.telegram.start_button_text)
        self.telegram_status_button_edit.setText(settings.telegram.status_button_text)
        self.telegram_pairs_button_edit.setText(settings.telegram.pairs_button_text)
        self.telegram_otc_button_edit.setText(settings.telegram.otc_button_text)
        self.telegram_real_button_edit.setText(settings.telegram.real_button_text)
        self.telegram_admin_button_edit.setText(settings.telegram.admin_button_text)
        self.telegram_admin_status_edit.setText(settings.telegram.admin_status_text)
        self.telegram_admin_charts_edit.setText(settings.telegram.admin_charts_text)
        self.telegram_admin_broadcast_edit.setText(settings.telegram.admin_broadcast_text)
        self.telegram_admin_test_capture_edit.setText(settings.telegram.admin_test_capture_text)
        self.telegram_admin_chat_ids_edit.setText(settings.telegram.admin_chat_ids)
        self._set_combo_data(self.telegram_preferred_broker_combo, settings.telegram.preferred_broker)
        enabled_brokers = {part.strip() for part in str(settings.telegram.enabled_brokers or "").split(",") if part.strip()}
        self.telegram_enabled_quotex_checkbox.setChecked("quotex" in enabled_brokers or not enabled_brokers)
        self.telegram_enabled_pocket_checkbox.setChecked("iq_option" in enabled_brokers or not enabled_brokers)
        self.telegram_enabled_exness_checkbox.setChecked("exness" in enabled_brokers or not enabled_brokers)
        self.telegram_use_all_brokers_checkbox.setChecked(bool(settings.telegram.use_all_brokers))
        self.telegram_scan_seconds_spin.setValue(int(settings.telegram.scan_animation_seconds or 3))
        self.telegram_quotex_email_edit.setText(settings.telegram.quotex_email)
        self.telegram_quotex_password_edit.setText(settings.telegram.quotex_password)
        telegram_iq_url = settings.telegram.pocket_option_url or "https://iqoption.com/en/login"
        if "pocketoption.com" in str(telegram_iq_url).lower():
            telegram_iq_url = "https://iqoption.com/en/login"
        self.telegram_pocket_url_edit.setText(telegram_iq_url)
        self.telegram_pocket_email_edit.setText(settings.telegram.pocket_option_email)
        self.telegram_pocket_password_edit.setText(settings.telegram.pocket_option_password)
        self.telegram_exness_login_edit.setText(settings.telegram.exness_login)
        self.telegram_exness_password_edit.setText(settings.telegram.exness_password)
        self.telegram_exness_server_edit.setText(settings.telegram.exness_server)
        
        # License settings - always use managed token to prevent mismatches
        # Do not try to access removed widgets: license_enabled_checkbox, license_key_edit, license_remember_checkbox
        
        self.license_api_url_edit.setText(settings.license.api_url or MANAGED_LICENSE_API_URL)
        # Always use the managed token - never use saved token to prevent authentication failures
        self.license_api_token_edit.setText(MANAGED_LICENSE_SHARED_TOKEN)
        self.license_poll_spin.setValue(int(settings.license.poll_seconds or 10))
        self.license_machine_lock_checkbox.setChecked(bool(settings.license.machine_lock_enabled))
        self.license_machine_id_value.setText(machine_display_id())
        if hasattr(self, "license_enabled_checkbox"):
            self.license_enabled_checkbox.setChecked(bool(settings.license.enabled))
            self.license_key_edit.setText(settings.license.license_key)
            self.license_remember_checkbox.setChecked(bool(settings.license.remember_license_key))
        self._update_license_admin_key_metrics()
        
        # Update admin tab visibility after applying settings (email is now known)
        self._update_admin_tab_visibility()
        
        # Matrix settings
        self.matrix_enabled_checkbox.setChecked(bool(settings.matrix.enabled))
        for i, (cb, email_edit, pass_edit) in enumerate(self.worker_checkboxes):
            if i < len(settings.matrix.workers):
                cb.setChecked(settings.matrix.workers[i].enabled)
                email_edit.setText(settings.matrix.workers[i].email)
                pass_edit.setText(settings.matrix.workers[i].password)
        self._set_combo_data(self.period_combo, settings.connection.candle_period)
        self._set_combo_data(self.full_chart_period_combo, settings.connection.candle_period)
        self._set_combo_data(self.duration_combo, settings.connection.trade_duration)
        self._set_combo_data(self.preferred_expiry_combo, settings.strategy.preferred_expiry_seconds)
        self._set_auto_button_state(settings.strategy.auto_trade_enabled)
        if not self.controller.assets:
            self._render_assets(self._provider_placeholder_assets(settings.connection.provider), settings.connection.selected_asset)
        self._sync_provider_fields()
        self._refilter_watch_table()
        self._update_telegram_preview()
        self._update_telegram_broker_summary()
        self._update_signal_format_preview()
        self._sync_admin_panel()
        self._update_license_state(self.controller.license_state_payload())

    def _set_combo_data(self, combo: QComboBox, target_value) -> None:
        for index in range(combo.count()):
            item_value = combo.itemData(index)
            if str(item_value) == str(target_value):
                combo.setCurrentIndex(index)
                return

    def _connect_clicked(self) -> None:
        # Debounce: prevent multiple clicks while already connecting
        if hasattr(self.controller, 'connecting') and self.controller.connecting:
            return
        if self.controller.connected:
            return
            
        self._exness_auto_connect_timer.stop()
        if (
            self.provider_combo.currentData() == "live"
            and self.email_edit.text().strip()
            and self.password_edit.text()
            and not self.remember_checkbox.isChecked()
        ):
            self.remember_checkbox.setChecked(True)
        provider_name = self._provider_display_name(self.provider_combo.currentData())
        self.mode_value.setText(f"Connecting | {provider_name}")
        self.engine_marks_value.setText("Engine Marks: CONNECTING")
        self.controller.connect_backend(self._collect_settings())

    def _save_settings(self) -> None:
        settings = self._collect_settings()
        self.controller.apply_settings(settings)
        self._set_auto_button_state(settings.strategy.auto_trade_enabled)
        self._update_telegram_preview()
        self._update_telegram_broker_summary()
        self._update_signal_format_preview()
        self._set_status("Settings updated.", "good")

    def _generate_license_key(self) -> None:
        """Generate a new license key and display it in the key field."""
        key = self.controller.generate_license_key(prefix="ETQ")
        self.license_admin_key_edit.setText(key)
        self.license_admin_status.setText(f"Generated new key: {key}")
        self._set_status("License key generated.", "good")

    def _create_license(self) -> None:
        """Create a new license on the server."""
        settings = self._collect_settings()
        self.controller.apply_settings(settings, persist=False)

        # Debug: Log token status before creation
        api_token = str(settings.license.api_token or "").strip()

        license_key = self.license_admin_key_edit.text().strip()
        if not license_key:
            self.license_admin_status.setText("Generate or enter a license key first.")
            self._set_status("No license key provided.", "bad")
            return

        duration_days = self.license_duration_days_spin.value()
        lifetime = self.license_lifetime_checkbox.isChecked()
        notes = self.license_notes_edit.toPlainText().strip()

        # Optional machine binding
        machine_lock = self.license_machine_lock_checkbox_admin.isChecked()
        machine_id = ""
        if machine_lock:
            machine_id = self.license_machine_id_edit.text().strip()
            if not machine_id:
                self.license_admin_status.setText("Machine lock enabled but no Machine ID provided.")
                self._set_status("Machine ID required for machine binding.", "bad")
                return

        result = self.controller.create_license(
            license_key=license_key,
            duration_days=duration_days if not lifetime else None,
            lifetime=lifetime,
            machine_lock=machine_lock,
            machine_id=machine_id,
            notes=notes,
        )

        if result.ok:
            self.license_admin_status.setText(f"License created: {license_key}")
            self._set_status("License created successfully.", "good")
            self._refresh_license_list()
        else:
            message = result.reason or "Failed to create license."
            self.license_admin_status.setText(message)
            self._set_status(message, "bad")

    def _revoke_license(self) -> None:
        """Revoke a license with a reason dialog."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        license_key = self.license_admin_key_edit.text().strip()
        if not license_key:
            self.license_admin_status.setText("Enter or select a license key to revoke.")
            self._set_status("No license key provided for revocation.", "bad")
            return

        # Show revocation reason dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Revoke License")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)
        dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"Revoke license: {license_key}")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")

        reason_label = QLabel("Please provide a reason for revocation:")
        reason_label.setWordWrap(True)

        reason_edit = QTextEdit()
        reason_edit.setPlaceholderText("e.g. Payment failed, Terms violated, User request...")
        reason_edit.setFixedHeight(80)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("Revoke")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")

        layout.addWidget(title)
        layout.addWidget(reason_label)
        layout.addWidget(reason_edit)
        layout.addWidget(button_box)

        def on_confirm():
            reason = reason_edit.toPlainText().strip()
            if not reason:
                reason = "Revoked by administrator"

            settings = self._collect_settings()
            self.controller.apply_settings(settings, persist=False)

            result = self.controller.revoke_license(license_key=license_key, reason=reason)

            if result.ok:
                self.license_admin_status.setText(f"License revoked: {license_key}")
                self._set_status("License revoked successfully.", "good")
                self._refresh_license_list()
            else:
                message = result.reason or "Failed to revoke license."
                self.license_admin_status.setText(message)
                self._set_status(message, "bad")

            dialog.accept()
        button_box.accepted.connect(on_confirm)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            pass

    def _on_delete_license_clicked(self) -> None:
        """Permanently delete a license key from the logs/database."""
        license_key = self.license_admin_key_edit.text().strip()
        if not license_key:
            self._set_status("Enter a license key to delete first.", "bad")
            return

        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete License",
            f"Are you sure you want to PERMANENTLY delete license key '{license_key}'?\n\nThis cannot be undone and will remove it from all logs.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._set_status(f"Deleting license {license_key}...", "good")
            result = self.controller.delete_license(license_key)
            if result.ok:
                self.license_admin_status.setText(f"License permanently deleted: {license_key}")
                self._set_status(f"License permanently deleted: {license_key}", "good")
                self.license_admin_key_edit.clear()
                self._refresh_license_list()
            else:
                self._set_status(f"Delete failed: {result.reason}", "bad")

            return

    def _refresh_license_list(self) -> None:
        """Refresh the license list from the server."""
        settings = self._collect_settings()
        self.controller.apply_settings(settings, persist=False)
        result = self.controller.list_licenses(limit=50)
        if not result.ok:
            message = result.reason or "Could not load license list."
            self.license_admin_status.setText(message)
            self.license_admin_list.setPlainText("")
            self._set_status(message, "bad")
            return
        records = result.records or []
        lines = []
        for record in records:
            expires = record.expires_at or "lifetime"
            machine = record.machine_id or "unbound"
            note = f" | {record.notes}" if record.notes else ""
            lines.append(
                f"{record.license_key} | {record.status} | expires {expires} | machine {machine}{note}"
            )
        self.license_admin_list.setPlainText("\n".join(lines) if lines else "No licenses returned from the server yet.")
        self.license_admin_status.setText(f"Loaded {len(records)} license record(s).")
        self._set_status("License list refreshed.", "good")

    def _unlock_admin_panel(self) -> None:
        if self.admin_password_edit.text().strip() == ADMIN_PANEL_PASSWORD:
            self._admin_unlocked = True
            self.admin_unlock_status.setText("Admin panel unlocked.")
            self._sync_admin_panel()
            if self.license_api_url_edit.text().strip() or MANAGED_LICENSE_API_URL:
                self._refresh_license_list()
            self._set_status("Admin panel unlocked.", "good")
            return
        if self.controller.is_admin:
            self._admin_unlocked = True
            self.admin_unlock_status.setText("Admin panel unlocked via your admin license.")
            self._sync_admin_panel()
            if self.license_api_url_edit.text().strip() or MANAGED_LICENSE_API_URL:
                self._refresh_license_list()
            self._set_status("Admin panel unlocked.", "good")
            return
        self._admin_unlocked = False
        self.admin_unlock_status.setText("Admin access requires a valid admin license key.")
        self._sync_admin_panel()
        self._set_status("Admin access denied. Validate with admin license first.", "bad")

    def _sync_admin_panel(self) -> None:
        if hasattr(self, "admin_stack"):
            self.admin_stack.setCurrentIndex(1 if self._admin_unlocked else 0)

    def _schedule_startup_license_gate(self) -> None:
        """Disabled: Mandatory license check now handled at the application entry point (app.py)."""
        return
    def _maybe_prompt_for_license_on_startup(self) -> None:
        self._startup_license_gate_scheduled = False
        if self._startup_license_prompt_handled:
            return
        self._startup_license_prompt_handled = True

        license_settings = self.controller.settings.license
        if not license_settings.enabled:
            return

        api_url = str(license_settings.api_url or MANAGED_LICENSE_API_URL).strip()
        if not api_url:
            self._switch_page("settings")
            self._set_status("License system is enabled, but the server URL is missing.", "bad")
            return

        self._show_startup_license_dialog()

    def _show_startup_license_dialog(self) -> None:
        from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("License Required")
        dialog.setModal(True)
        dialog.setMinimumWidth(440)
        dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Enter a valid license key to continue.")
        title.setObjectName("heroSub")
        title.setWordWrap(True)
        helper = QLabel(
            "This build checks a license every launch. Saved keys can prefill the field, but launch access is still validated before the bot opens."
        )
        helper.setObjectName("helperText")
        helper.setWordWrap(True)
        machine_label = QLabel(f"Machine ID: {machine_display_id()}")
        machine_label.setObjectName("helperText")

        key_edit = QLineEdit()
        key_edit.setPlaceholderText("Enter your license key or admin email")
        key_edit.setClearButtonEnabled(True)
        key_edit.setText(str(self.controller.settings.license.license_key or "").strip())

        remember_checkbox = QCheckBox("Remember this license key on this machine (prefill only)")
        remember_checkbox.setChecked(bool(self.controller.settings.license.remember_license_key))

        key_meta_label = QLabel(self._license_length_summary(key_edit.text()))
        key_meta_label.setObjectName("helperText")
        key_meta_label.setWordWrap(True)
        status_label = QLabel("")
        status_label.setObjectName("helperText")
        status_label.setWordWrap(True)

        button_row = QHBoxLayout()
        validate_button = QPushButton("Validate & Continue")
        validate_button.setObjectName("primaryButton")
        exit_button = QPushButton("Exit")
        exit_button.setObjectName("ghostButton")
        button_row.addWidget(validate_button)
        button_row.addWidget(exit_button)

        layout.addWidget(title)
        layout.addWidget(helper)
        layout.addWidget(machine_label)
        layout.addWidget(key_edit)
        layout.addWidget(remember_checkbox)
        layout.addWidget(key_meta_label)
        layout.addWidget(status_label)
        layout.addLayout(button_row)

        def attempt_validate() -> None:
            license_key = key_edit.text().strip()
            if not license_key:
                status_label.setText("Enter the license key your admin created for you.")
                key_edit.setFocus()
                return

            settings = self._collect_settings()
            settings.license.enabled = True
            settings.license.api_url = settings.license.api_url or MANAGED_LICENSE_API_URL
            settings.license.api_token = settings.license.api_token or MANAGED_LICENSE_SHARED_TOKEN
            settings.license.license_key = license_key
            settings.license.remember_license_key = remember_checkbox.isChecked()
            self.controller.apply_settings(settings)

            result = self.controller.validate_license_now()
            if result.valid:
                self._apply_settings(self.controller.settings)
                if result.is_admin:
                    self._set_status("Admin license validated successfully.", "good")
                else:
                    self._set_status("License validated successfully.", "good")
                dialog.accept()
                return

            message = result.reason or "License validation failed."
            status_label.setText(message)
            self._apply_settings(self.controller.settings)
            self._set_status(message, "bad")
            key_edit.setFocus()
            key_edit.selectAll()

        validate_button.clicked.connect(attempt_validate)
        exit_button.clicked.connect(dialog.reject)
        key_edit.returnPressed.connect(attempt_validate)
        key_edit.textChanged.connect(lambda text="", le=key_edit, lbl=key_meta_label: lbl.setText(self._license_length_summary(le.text())))
        key_edit.setFocus()
        key_edit.selectAll()

        if dialog.exec() == QDialog.Accepted:
            return

        self._set_status("A valid license is required to open the bot.", "bad")
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def _update_license_state(self, payload: dict[str, object]) -> None:
        if not hasattr(self, "license_status_value"):
            return
        enabled = bool(payload.get("enabled"))
        valid = bool(payload.get("valid"))
        status = str(payload.get("status") or "unknown").strip().replace("_", " ").title()
        reason = str(payload.get("reason") or "").strip()
        expires_at = str(payload.get("expires_at") or "").strip()
        checked_at = float(payload.get("checked_at") or 0.0)
        checked_label = datetime.fromtimestamp(checked_at).strftime("%H:%M:%S") if checked_at > 0 else "Never"
        if not enabled:
            message = "License system is off. End users can connect without a key."
        elif valid:
            message = f"{status or 'Active'} | {reason or 'License active.'} | Last check {checked_label}"
        else:
            message = f"{status or 'Invalid'} | {reason or 'License not valid.'} | Last check {checked_label}"
        if expires_at:
            message += f" | Expires {expires_at}"
        self.license_machine_id_value.setText(str(payload.get("machine_id") or machine_display_id()))
        self.license_status_value.setText(message)
        
        # Update admin tab visibility after license state changes
        self._update_admin_tab_visibility()

    def _handle_license_invalidation(self, reason: str) -> None:
        """Silent background invalidation to prevent session interruption."""
        message = str(reason or "License sync check.")
        # Log to activity console instead of crashing/popping up
        self._append_log(f"Security: {message}", "warn")
    def _toggle_automation(self) -> None:
        enabled = not self.controller.automation.stats.automation_enabled
        self.auto_trade_checkbox.setChecked(enabled)
        self.controller.set_automation_enabled(enabled)
        self._set_auto_button_state(enabled)

    def _sync_provider_fields(self) -> None:
        provider = str(self.provider_combo.currentData() or "mock")
        index_map = {"mock": 0, "live": 1, "quotex": 1, "iq_option": 2, "pocket_option": 2, "exness": 3, "multi": 4}
        self.provider_stack.setCurrentIndex(index_map.get(provider, 0))
        self._update_provider_stack_height()
        if provider in {"live", "quotex"}:
            self.provider_hint.setText("Quotex mode needs your credentials and uses browser automation for authentication. Background browser mode can hide the window, but visible mode is still better for one-time PIN logins.")
            self.connect_button.setText("Connect Quotex")
        elif provider == "iq_option":
            self.provider_hint.setText("IQ Option mode needs your credentials and opens a browser automation terminal for live prices and manual trade routing.")
            self.connect_button.setText("Connect IQ Option")
        elif provider == "exness":
            self.provider_hint.setText("Forex Market mode keeps a lightweight forex feed connected to the chart engine and market list.")
            self.connect_button.setText("Connect Forex Market")
        elif provider == "multi":
            self.provider_hint.setText("Multi-Broker Feed connects the selected broker set and keeps the chosen primary broker ready for manual execution.")
            self.connect_button.setText("Connect Selected Brokers")
        else:
            self.provider_hint.setText("Mock Sandbox gives you a safe environment to test UI, signals, and auto trading without touching a live account.")
            self.connect_button.setText("Start Mock Session")
        if provider != "exness":
            self._exness_auto_connect_timer.stop()
            self._exness_auto_connect_armed = False
        elif not self.controller.connected and self._can_auto_connect_exness() and not self._exness_auto_connect_armed:
            self._exness_auto_connect_armed = True
            self._exness_auto_connect_timer.start(350)
        if hasattr(self, "trade_card"):
            self.trade_card.setVisible(provider != "exness")
        if not self.controller.connected:
            provider_name = self._provider_display_name(provider)
            self.mode_value.setText(f"Offline | {provider_name}")
        if not self.controller.connected and not self.controller.assets:
            selected_asset = self.controller.settings.connection.selected_asset
            self._render_assets(self._provider_placeholder_assets(self.provider_combo.currentData()), selected_asset)
        self._refilter_watch_table()

    def _update_provider_stack_height(self) -> None:
        current = self.provider_stack.currentWidget()
        if current is None:
            return
        target_height = max(118, min(360, current.sizeHint().height() + 12))
        self.provider_stack.setMinimumHeight(target_height)
        self.provider_stack.setMaximumHeight(target_height)

    def _refresh_exness_summary(self, settings: AppSettings) -> None:
        api_key = str(settings.connection.exness_server or "").strip()
        using_demo = not api_key or api_key.lower() == "demo"
        self.exness_profile_value.setText("Managed forex feed loaded")
        self.exness_server_value.setText("Feed key required" if using_demo else "Custom forex feed key")
        self.exness_runtime_value.setText(
            "Data-only mode | Manual connect"
        )

    def _can_auto_connect_exness(self) -> bool:
        if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
            return False
        api_key = str(self.controller.settings.connection.exness_server or "").strip()
        return bool(api_key and api_key.lower() != "demo")

    def _maybe_auto_connect_exness(self) -> None:
        if not self._can_auto_connect_exness():
            self._exness_auto_connect_armed = False
            return
        if self.controller.connected:
            return
        if str(self.provider_combo.currentData() or "") != "exness":
            self._exness_auto_connect_armed = False
            return
        self._connect_clicked()

    def _asset_changed(self) -> None:
        symbol = str(self.asset_combo.currentData() or self.asset_combo.currentText() or "").strip()
        if symbol:
            asset = self._asset_by_symbol(symbol)
            display_symbol = self._display_asset_symbol(asset or symbol)
            self.market_chip.setText(f"Market: {display_symbol}")
            self.trade_target_value.setText(display_symbol)
            self.market_focus_value.setText(display_symbol)
            if asset is not None:
                pass  # meta info available in chart
            self._set_full_chart_symbol(symbol)
            self.controller.select_asset(symbol)

    def _full_chart_asset_changed(self) -> None:
        symbol = str(self.full_chart_asset_combo.currentData() or self.full_chart_asset_combo.currentText() or "").strip()
        current = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        if symbol and symbol != current:
            self._set_combo_symbol(symbol)

    def _period_changed(self) -> None:
        period = int(self.period_combo.currentData() or self.controller.settings.connection.candle_period or 60)
        self.controller.settings.connection.candle_period = period
        self._set_combo_data(self.full_chart_period_combo, period)
        symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        if symbol:
            if self.controller.backend is not None and hasattr(self.controller.backend, "set_selected_asset"):
                try:
                    self.controller.backend.set_selected_asset(symbol, period)
                except Exception:
                    pass
            if self.controller.connected:
                self.controller.refresh_market()

    def _full_chart_period_changed(self) -> None:
        period = int(self.full_chart_period_combo.currentData() or self.controller.settings.connection.candle_period or 60)
        current = int(self.period_combo.currentData() or self.controller.settings.connection.candle_period or 60)
        if period != current:
            self._set_combo_data(self.period_combo, period)

    def _trade_ticket_changed(self) -> None:
        self.controller.settings.connection.trade_duration = int(self.duration_combo.currentData() or self.controller.settings.connection.trade_duration or 60)
        self.controller.settings.connection.trade_amount = float(self.amount_spin.value())

    def _submit_manual_trade(self, action: str) -> None:
        self._trade_ticket_changed()
        symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        if symbol:
            self.controller.settings.connection.selected_asset = symbol
        self.controller.place_trade(action, duration=int(self.duration_combo.currentData() or 60))

    def _asset_from_table(self) -> None:
        selected = self.watch_table.selectedItems()
        if selected and len(selected) > 0:
            symbol = str(selected[0].data(Qt.UserRole) or "").strip()
            if symbol:
                self._set_combo_symbol(symbol)

    def _update_assets(self, assets) -> None:
        current_symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        if not assets:
            assets = self._provider_placeholder_assets(self.provider_combo.currentData())
        self._render_assets(list(assets), current_symbol)

    def _provider_placeholder_assets(self, provider: str) -> list[AssetInfo | str]:
        """Get standard placeholders for the given provider with robust merging."""
        provider_key = str(provider or "mock")
        if provider_key in {"live", "quotex"}:
            return [self._safe_asset(symbol) for symbol in default_live_assets()]
        if provider_key in {"iq_option", "pocket_option"}:
            return default_iq_option_assets()
        if provider_key == "exness":
            return default_exness_assets()
        if provider_key == "multi":
            merged: dict[str, AssetInfo | str] = {}
            # Helper to extract symbol safely
            def get_sym(a): return a.symbol if hasattr(a, "symbol") else str(a)

            for asset in default_live_assets():
                merged[get_sym(asset)] = asset
            for asset in default_iq_option_assets():
                merged.setdefault(get_sym(asset), asset)
            for asset in default_exness_assets():
                merged.setdefault(get_sym(asset), asset)

            return sorted(merged.values(), key=get_sym)
        return default_mock_assets()
    def _provider_display_name(self, provider: str) -> str:
        provider_key = str(provider or "mock")
        labels = {
            "mock": "Mock Sandbox",
            "live": "Quotex",
            "quotex": "Quotex",
            "iq_option": "IQ Option",
            "pocket_option": "IQ Option",
            "exness": "Forex Market",
            "multi": "Multi-Broker Feed",
        }
        return labels.get(provider_key, "Broker Session")

    def _render_assets(self, assets: list[AssetInfo | str], selected_symbol: str) -> None:
        """Render asset list into UI combos with absolute safety."""
        self._asset_cache = list(assets)

        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        for asset in assets:
            safe = self._safe_asset(asset)
            self.asset_combo.addItem(self._display_asset_symbol(safe), safe.symbol)

        if self.asset_combo.count():
            fallback = selected_symbol if self._find_combo_symbol(selected_symbol) >= 0 else str(self.asset_combo.itemData(0))
            self._set_combo_symbol(fallback)
        self.asset_combo.blockSignals(False)

        self.full_chart_asset_combo.blockSignals(True)
        self.full_chart_asset_combo.clear()
        for asset in assets:
            safe = self._safe_asset(asset)
            self.full_chart_asset_combo.addItem(self._display_asset_symbol(safe), safe.symbol)

        if self.full_chart_asset_combo.count():
            self._set_full_chart_symbol(
                selected_symbol if self._find_full_chart_symbol(selected_symbol) >= 0 else str(self.full_chart_asset_combo.itemData(0))
            )
        self.full_chart_asset_combo.blockSignals(False)

        current_symbol = str(self.asset_combo.currentData() or selected_symbol or "")
        if current_symbol:
            display_symbol = self._display_asset_symbol(self._asset_by_symbol(current_symbol) or current_symbol)
            self.market_chip.setText(f"Market: {display_symbol}")
            self.trade_target_value.setText(display_symbol)
            self.market_focus_value.setText(display_symbol)

        self._refilter_watch_table()
        self._update_telegram_preview()

    def _asset_by_symbol(self, symbol: str) -> AssetInfo | None:
        target = str(symbol or "").strip()
        for asset in self._asset_cache:
            safe = self._safe_asset(asset)
            if safe.symbol == target:
                return safe if isinstance(asset, AssetInfo) else None
        return None
    def _display_asset_symbol(self, asset_or_symbol: AssetInfo | str) -> str:
        if isinstance(asset_or_symbol, AssetInfo):
            if asset_or_symbol.display_name:
                return asset_or_symbol.display_name
            normalized = str(asset_or_symbol.symbol or "").strip()
        else:
            normalized = str(asset_or_symbol or "").strip()
        if normalized.lower().endswith("_otc"):
            base = normalized[:-4]
            suffix = " (OTC)"
        else:
            base = normalized
            suffix = ""
        if len(base) == 6 and base.isalpha():
            return f"{base[:3]}/{base[3:]}{suffix}"
        return normalized

    def _display_asset_category(self, category: str) -> str:
        raw = str(category or "").strip().lower()
        labels = {
            "live": "Quotex",
            "mock": "Mock",
            "iq_option": "IQ Option",
            "pocket_option": "IQ Option",
            "forex": "Forex",
            "metals": "Metals",
            "crypto": "Crypto",
            "indices": "Indices",
            "stocks": "Stocks",
            "energies": "Energies",
            "commodities": "Commodities",
            "other": "Other",
        }
        if raw.startswith("multi:"):
            return "Multi"
        if raw in {"binary", "live", "mock", "iq_option", "pocket_option"}:
            return "Binary / OTC"
        return labels.get(raw, raw.replace("_", " ").title() or "Other")

    def _find_combo_symbol(self, symbol: str) -> int:
        target = str(symbol or "").strip()
        for index in range(self.asset_combo.count()):
            if str(self.asset_combo.itemData(index) or "").strip() == target:
                return index
        return -1

    def _set_combo_symbol(self, symbol: str) -> None:
        index = self._find_combo_symbol(symbol)
        if index >= 0:
            self.asset_combo.setCurrentIndex(index)

    def _find_full_chart_symbol(self, symbol: str) -> int:
        target = str(symbol or "").strip()
        for index in range(self.full_chart_asset_combo.count()):
            if str(self.full_chart_asset_combo.itemData(index) or "").strip() == target:
                return index
        return -1

    def _set_full_chart_symbol(self, symbol: str) -> None:
        index = self._find_full_chart_symbol(symbol)
        if index >= 0:
            self.full_chart_asset_combo.setCurrentIndex(index)

    def _category_matches(self, asset: AssetInfo | str, category_filter: str) -> bool:
        """Robust category matching for mixed asset data types."""
        desired = str(category_filter or "all").strip().lower()
        if desired in {"", "all"}:
            return True

        # Extract category safely
        is_obj = hasattr(asset, "category")
        actual = str(asset.category or "").strip().lower() if is_obj else "binary"
        sym = asset.symbol if is_obj else str(asset)

        if desired == "binary":
            return actual in {"live", "mock", "iq_option", "pocket_option"} or sym.lower().endswith("_otc") or actual.startswith("multi:")
        return actual == desired
    def _filter_assets(self, query: str, category_filter: str) -> list[AssetInfo | str]:
        """Safely filter assets regardless of their underlying data type."""
        assets = list(self._asset_cache)

        # 1. Feed Status Filter (Safe)
        if hasattr(self, "show_warming_pairs_checkbox") and not self.show_warming_pairs_checkbox.isChecked():
            def is_ready(a):
                if hasattr(a, "last_price"):
                    return a.feed_status in {"live", "synced"} or a.last_price > 0
                return True # Strings are always 'ready' placeholders
            assets = [asset for asset in assets if is_ready(asset)]

        # 2. Category Filter (Safe)
        assets = [asset for asset in assets if self._category_matches(asset, category_filter)]

        # 3. Query Filter (Safe)
        lowered = str(query or "").strip().lower()
        if not lowered:
            return assets

        def matches_query(a):
            is_obj = hasattr(a, "symbol")
            sym = a.symbol if is_obj else str(a)
            cat = a.category if is_obj else "binary"
            return (
                lowered in sym.lower()
                or lowered in self._display_asset_symbol(a).lower()
                or lowered in self._display_asset_category(cat).lower()
            )

        return [asset for asset in assets if matches_query(asset)]
    def _filtered_assets(self) -> list[AssetInfo]:
        return self._filter_assets(
            self.asset_search_edit.text().strip().lower(),
            str(self.watch_category_combo.currentData() or "all"),
        )

    def _refilter_watch_table(self) -> None:
        """Populate the watch table with robust handling for mixed asset types."""
        selected_symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        filtered_assets = self._filtered_assets()

        self.watch_table.blockSignals(True)
        self.watch_table.clearSelection()
        self.watch_table.setRowCount(0)

        live_count = 0
        selected_row = -1

        for row, asset in enumerate(filtered_assets):
            self.watch_table.insertRow(row)

            # Extract data with safe fallbacks for string inputs
            is_obj = hasattr(asset, "symbol")
            sym = asset.symbol if is_obj else str(asset)
            cat = asset.category if is_obj else "binary"
            payout = asset.payout if is_obj else 0.0
            last_price = asset.last_price if is_obj else 0.0
            is_open = asset.is_open if is_obj else True
            feed_status = getattr(asset, "feed_status", "") if is_obj else ""

            pair_item = QTableWidgetItem(self._display_asset_symbol(asset))
            pair_item.setData(Qt.UserRole, sym)

            category_item = QTableWidgetItem(self._display_asset_category(cat))
            payout_item = QTableWidgetItem(f"{payout*100:.0f}%")

            feed_state = feed_status.title() if feed_status else ("Live" if last_price > 0 else "Warming")
            if last_price > 0 and feed_status == "warming":
                feed_state = "Live"

            feed_item = QTableWidgetItem(feed_state)
            open_item = QTableWidgetItem("Open" if is_open else "Closed")
            last_item = QTableWidgetItem(f"{last_price:.5f}" if last_price else "--")

            self.watch_table.setItem(row, 0, pair_item)
            self.watch_table.setItem(row, 1, category_item)
            self.watch_table.setItem(row, 2, payout_item)
            self.watch_table.setItem(row, 3, feed_item)
            self.watch_table.setItem(row, 4, open_item)
            self.watch_table.setItem(row, 5, last_item)

            if last_price > 0:
                live_count += 1
            if sym == selected_symbol:
                selected_row = row

        if selected_row >= 0:
            self.watch_table.selectRow(selected_row)

        self.watch_table.blockSignals(False)
        warming_count = max(0, len(filtered_assets) - live_count)
        self.watch_status_label.setText(f"{len(filtered_assets)} shown | {live_count} live | {warming_count} warming")
    def _display_signal_decision(self, decision: StrategyDecision) -> tuple[StrategyDecision, bool]:
        now = time.time()
        if decision.action in {"CALL", "PUT"}:
            self._sticky_signal = decision
            sticky_seconds = max(
                45.0,
                float(self.controller.settings.strategy.sticky_signal_seconds or 75),
                float(decision.recommended_duration or 60) + 25.0,
            )
            self._sticky_signal_until = now + sticky_seconds
            return decision, False
        if self._sticky_signal is not None and now < self._sticky_signal_until:
            return self._sticky_signal, True
        return decision, False

    def _update_chart(self, candles, decision: StrategyDecision) -> None:
        incoming_candles = list(candles or [])
        if incoming_candles:
            self._latest_candles = incoming_candles
        elif self._latest_candles:
            incoming_candles = list(self._latest_candles)
        else:
            self._latest_candles = []
        display_decision, sticky = self._display_signal_decision(decision)
        selected_symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
        selected_asset = self._asset_by_symbol(selected_symbol)
        chart_title = self._display_asset_symbol(selected_asset or selected_symbol)
        self.chart.set_candles(incoming_candles, decision.ema_fast, decision.ema_slow, title=chart_title)
        self.full_chart.set_candles(incoming_candles, decision.ema_fast, decision.ema_slow, title=chart_title)
        if incoming_candles:
            last = incoming_candles[-1]
            locked_at = (
                datetime.fromtimestamp(display_decision.signal_timestamp).strftime("%H:%M:%S")
                if display_decision.signal_timestamp
                else "--"
            )
            summary = display_decision.summary
            if sticky and display_decision.action in {"CALL", "PUT"}:
                summary = f"{display_decision.summary} | Entry window active"
            self.market_detail.setText(
                f"{self.asset_combo.currentText()} | O {last.open:.5f} H {last.high:.5f} "
                f"L {last.low:.5f} C {last.close:.5f} | {summary} | "
                f"Expiry {display_decision.recommended_duration // 60}m | Locked {locked_at}"
            )
            # Use safety wrapper for attributes
            safe_selected = self._safe_asset(selected_asset or selected_symbol)
            category_label = self._display_asset_category(safe_selected.category)
            feed_label = (
                safe_selected.feed_status.title()
                if safe_selected.feed_status
                else ("Live" if last.close else "Warming")
            )

            self.market_focus_value.setText(f"{self.asset_combo.currentText()} | {last.close:.5f}")
            self.market_focus_reason.setText(
                f"{summary} | Recommended expiry {max(1, int(display_decision.recommended_duration or 60) // 60)}m | "
                f"Locked candle {locked_at}"
            )
            self.last_price_value.setText(f"{last.close:.5f}")
            self.last_price_summary.setText(f"Updated at {datetime.fromtimestamp(last.timestamp).strftime('%H:%M:%S')}")
        self._set_signal_widgets(display_decision, sticky=sticky)

    def _append_trade(self, ticket: TradeTicket) -> None:
        row = self.trade_table.rowCount()
        self.trade_table.insertRow(row)
        self.trade_rows[ticket.id] = row
        values = [
            datetime.fromtimestamp(ticket.opened_at).strftime("%H:%M:%S"),
            ticket.raw.get("source", "manual"),
            ticket.asset,
            ticket.action,
            f"{ticket.amount:.2f}",
            f"{ticket.duration}s",
            "OPEN",
            "--",
        ]
        for column, value in enumerate(values):
            self.trade_table.setItem(row, column, QTableWidgetItem(value))

    def _resolve_trade(self, ticket: TradeTicket) -> None:
        row = self.trade_rows.get(ticket.id)
        if row is None:
            return
        self.trade_table.setItem(row, 6, QTableWidgetItem("WIN" if ticket.result else "LOSS"))
        self.trade_table.setItem(row, 7, QTableWidgetItem(f"{ticket.profit:+.2f}"))

    def _update_stats(self, stats) -> None:
        self.session_stats_value.setText(
            f"{stats.trades_taken} trades | {stats.wins} wins | {stats.losses} losses | Loss streak {stats.consecutive_losses}"
        )
        self.pnl_value.setText(f"${stats.net_pnl:+.2f}")
        state = "Auto trader armed and waiting for a qualified signal." if stats.automation_enabled else "Auto trader paused."
        if stats.active_trade_id:
            state += f" Active trade: {stats.active_trade_id}"
        self.automation_state.setText(state)
        self.auto_status_label.setText(state)
        self.auto_state_value.setText("Armed" if stats.automation_enabled else "Paused")
        self.auto_state_summary.setText(f"{stats.trades_taken} trades this session | Net {stats.net_pnl:+.2f}")
        self._set_auto_button_state(stats.automation_enabled)

    def _append_log(self, line: str, _level: str) -> None:
        # Limit log output to prevent memory issues
        try:
            self.log_output.document().setMaxBlockCount(5000)
        except Exception:
            pass  # Fallback if document API is not available
        self.log_output.append(line)

    def _update_balance(self, balance: float) -> None:
        self.balance_value.setText(f"${balance:,.2f}")

    def _update_account(self, snapshot) -> None:
        self.mode_value.setText(f"{snapshot.mode} | {snapshot.backend_name}")
        self.connection_detail.setText(f"{snapshot.backend_name} connected in {snapshot.mode} mode. Balance sync is active.")
        self.engine_marks_value.setText("Engine Marks: LIVE READY")
        self.scan_chip.setText("Deep Scan: ready")
        self.deep_scan_status_value.setText("Connected. Run Deep Scan All to pin the strongest live setup.")
        # Update admin tab visibility based on logged-in user
        self._update_admin_tab_visibility()

    def _update_connection_buttons(self, connected: bool) -> None:
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.toolbar_disconnect_button.setEnabled(connected)
        self.engine_button.setText("STOP Engine" if connected else "START Engine")
        if not connected:
            provider_name = self._provider_display_name(self.provider_combo.currentData())
            self.mode_value.setText(f"Offline | {provider_name}")
            if not self.controller.assets:
                self._render_assets(
                    self._provider_placeholder_assets(self.provider_combo.currentData()),
                    self.controller.settings.connection.selected_asset,
                )
    
    def _update_admin_tab_visibility(self) -> None:
        """Update admin tab visibility based on logged-in email and admin status"""
        admin_button = self.page_buttons.get("admin")
        if not admin_button:
            return
        
        # Get current email from settings (check both email and quotex_email fields)
        current_email = (
            self.controller.settings.connection.quotex_email or 
            self.controller.settings.connection.email or 
            ""
        )
        
        # Also check if the license key itself is the admin email
        license_key = str(self.controller.settings.license.license_key or "").strip()
        is_admin_license_key = license_key.lower() == self._admin_email.lower()
        
        # Show admin tab if:
        # 1. User has admin license flag (controller._is_admin is True) OR
        # 2. The license key is the admin email address
        has_admin_license = getattr(self.controller, '_is_admin', False)
        should_show = has_admin_license or is_admin_license_key
        
        admin_button.setVisible(should_show)
        
        # Debug logging
        
        # If admin tab is currently active but shouldn't be visible, switch to Live tab
        if not should_show and self.pages.currentIndex() == self.page_indexes.get("admin", -1):
            self._switch_page("live")

    def _set_status(self, message: str, tone: str) -> None:
        self.status_value.setText(message)
        self.connection_detail.setText(message)
        if tone == "good":
            self.engine_marks_value.setText("Engine Marks: ACTIVE")
        elif tone == "bad":
            self.engine_marks_value.setText("Engine Marks: ATTENTION")
        else:
            self.engine_marks_value.setText("Engine Marks: MONITOR")
        if "deep scan" in message.lower():
            self.scan_chip.setText(message if len(message) <= 42 else "Deep Scan: updated")
        if not self.controller.connected:
            if tone == "working":
                provider_name = self._provider_display_name(self.provider_combo.currentData())
                self.mode_value.setText(f"Connecting | {provider_name}")
            elif tone == "bad":
                provider_name = self._provider_display_name(self.provider_combo.currentData())
                self.mode_value.setText(f"Offline | {provider_name}")
        if tone == "good":
            self.status_value.setObjectName("statusGood")
        elif tone == "bad":
            self.status_value.setObjectName("statusBad")
        else:
            self.status_value.setObjectName("statusWarn")

    def _set_signal_widgets(self, decision: StrategyDecision, *, sticky: bool = False) -> None:
        object_name = "signalCall" if decision.action == "CALL" else "signalPut" if decision.action == "PUT" else "signalHold"
        for label in (self.signal_value, self.quick_signal_value):
            label.setText(decision.action)
            label.setObjectName(object_name)
        self.confidence_value.setText(f"{decision.confidence:.2f}")
        self.rsi_value.setText("--" if decision.rsi is None else f"{decision.rsi:.2f}")
        self.trend_value.setText(f"{decision.trend_strength:.5f}")
        self.expiry_value.setText(f"{max(1, int(decision.recommended_duration or 60) // 60)}m")
        self.signal_lock_value.setText(
            datetime.fromtimestamp(decision.signal_timestamp).strftime("%H:%M:%S")
            if decision.signal_timestamp
            else "--"
        )
        self.signal_reason.setText(decision.reason or decision.summary)
        if sticky and decision.action in {"CALL", "PUT"}:
            self.quick_signal_summary.setText(
                f"{decision.summary} | Manual window active | {max(1, int(decision.recommended_duration or 60) // 60)}m expiry"
            )
        else:
            self.quick_signal_summary.setText(f"{decision.summary} | {max(1, int(decision.recommended_duration or 60) // 60)}m expiry")
        self.quick_confidence_value.setText(f"{decision.confidence:.2f}")
        self.quick_confidence_summary.setText(decision.reason or decision.summary)

        # Update the signal display in the Market View card
        if decision.action in {"CALL", "PUT"}:
            direction_emoji = "\U0001f53c" if decision.action == "CALL" else "\U0001f53d"
            confidence = decision.confidence
            if confidence >= 0.78:
                level = "DEEP CONFIRMED"
            elif confidence >= 0.68:
                level = "CONFIRMED"
            elif confidence >= 0.58:
                level = "DEVELOPING"
            else:
                level = "WEAK BIAS"
            selected_symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")
            selected_asset = self._asset_by_symbol(selected_symbol)
            display_symbol = self._display_asset_symbol(selected_asset or selected_symbol)
            expiry_min = max(1, int(decision.recommended_duration or 60) // 60)
            locked_at = (
                datetime.fromtimestamp(decision.signal_timestamp).strftime("%H:%M:%S")
                if decision.signal_timestamp
                else "--"
            )
            analysis_points = decision.reason or decision.summary or ""
            self.signal_display.setText(
                f"{direction_emoji} {decision.action} | {display_symbol} | {expiry_min}m | Price: {self.last_price_value.text()}\n"
                f"Confidence: {confidence:.0%} | Level: {level}\n"
                f"Locked: {locked_at} | {analysis_points}"
            )
            self.signal_display.setObjectName("signalDisplay")
        else:
            self.signal_display.setText("No active signal")
            self.signal_display.setObjectName("metricValue")

    def _set_auto_button_state(self, enabled: bool) -> None:
        self.auto_trade_button.setText("Pause Auto Trading" if enabled else "Arm Auto Trading")
        self.auto_state_value.setText("Armed" if enabled else "Paused")

    def _on_deep_scan_changed(self, active: bool) -> None:
        """Update UI when a deep scan starts or stops."""
        self.deep_scan_button.setEnabled(not active)
        self.deep_scan_run_button.setEnabled(not active)
        if active:
            self.deep_scan_status_value.setText("Deep Scan in progress... Reviewing all pairs.")
            self.deep_scan_status_value.setStyleSheet("color: #4299e1;")
        else:
            self.deep_scan_status_value.setStyleSheet("color: #a0aec0;")

    def _update_deep_scan(self, result: dict) -> None:
        asset = str(result.get("asset") or "") if isinstance(result, dict) else ""
        decision = result.get("decision") if isinstance(result, dict) else None
        rows = list(result.get("rows") or []) if isinstance(result, dict) else []
        scanned = int(result.get("scanned") or 0) if isinstance(result, dict) else 0

        self.deep_scan_table.setRowCount(0)
        for row_index, row in enumerate(rows):
            asset_name = self._display_asset_symbol(str(row.get("asset") or ""))
            status = str(row.get("status") or "")
            confidence = row.get("confidence")
            current_price = row.get("current_price", 0.0)
            confirm = str(row.get("confirm") or "NA")
            summary = str(row.get("summary") or row.get("message") or "")
            
            # Format current price for its own column
            if current_price and current_price > 0:
                price_display = f"{current_price:.5f}"
            else:
                price_display = "--"
                
            self.deep_scan_table.insertRow(row_index)
            self.deep_scan_table.setItem(row_index, 0, QTableWidgetItem(asset_name))
            self.deep_scan_table.setItem(row_index, 1, QTableWidgetItem(status))
            self.deep_scan_table.setItem(row_index, 2, QTableWidgetItem(f"{float(confidence):.2f}" if confidence not in {None, ""} else "--"))
            self.deep_scan_table.setItem(row_index, 3, QTableWidgetItem(price_display))
            self.deep_scan_table.setItem(row_index, 4, QTableWidgetItem(confirm if confirm != "NA" else "No data"))
            self.deep_scan_table.setItem(row_index, 5, QTableWidgetItem(summary))

        if asset and isinstance(decision, StrategyDecision) and decision.action in {"CALL", "PUT"}:
            display_asset = self._display_asset_symbol(asset)
            self.scan_chip.setText(f"Deep Scan: {decision.action} {display_asset}")
            self.deep_scan_status_value.setText(f"Scanned {scanned} pairs. Best result stays pinned until a newer scan replaces it.")
            self.deep_scan_result_value.setText(f"{decision.action} | {display_asset} | {decision.confidence:.2f}")
            self.deep_scan_result_reason.setText(decision.reason or decision.summary)
            self.deep_scan_focus_value.setText(f"{decision.action} | {display_asset}")
            self.deep_scan_focus_reason.setText(decision.reason or decision.summary)
        else:
            self.scan_chip.setText("Deep Scan: no edge")
            result_type = str(result.get("result_type") or "none") if isinstance(result, dict) else "none"
            decision_obj = result.get("decision") if isinstance(result, dict) else None
            if isinstance(decision_obj, StrategyDecision) and decision_obj.confidence == 0.0:
                self.deep_scan_status_value.setText(f"Scanned {scanned} pairs. {decision_obj.summary}")
                self.deep_scan_result_value.setText("No data from Quotex")
                self.deep_scan_result_reason.setText(decision_obj.reason or decision_obj.summary)
            elif isinstance(decision_obj, StrategyDecision) and decision_obj.action == "HOLD":
                self.deep_scan_status_value.setText(f"Scanned {scanned} pairs. Best result stays below threshold.")
                self.deep_scan_result_value.setText(f"{decision_obj.summary}")
                self.deep_scan_result_reason.setText(decision_obj.reason or "No pair met the minimum confidence threshold.")
            else:
                self.deep_scan_status_value.setText(f"Scanned {scanned} pairs. No confirmed setup met the threshold.")
                self.deep_scan_result_value.setText("No confirmed setup")
                self.deep_scan_result_reason.setText("The scan completed, but no pair had a clean confirmed edge strong enough to pin.")

    def _safe_asset(self, asset_or_str: AssetInfo | str) -> AssetInfo:
        """Permanent safety wrapper. Always returns an AssetInfo-compatible object."""
        if isinstance(asset_or_str, AssetInfo):
            return asset_or_str
        # Return a dummy object with safe defaults for strings
        return AssetInfo(
            symbol=str(asset_or_str),
            payout=0.0,
            is_open=True,
            category="binary",
            last_price=0.0,
            feed_status="warming"
        )

    def _update_telegram_preview(self) -> None:
        """Render the Telegram preview with absolute type-safety."""
        if not hasattr(self, "telegram_preview"):
            return
        settings = self._collect_settings()

        # Convert all to safe objects before filtering
        safe_cache = [self._safe_asset(a) for a in self._asset_cache]

        preview_assets = [a for a in safe_cache if a.feed_status in {"live", "synced"} or a.last_price > 0]
        if not preview_assets:
            preview_assets = safe_cache[:6]

        self.telegram_preview.setPlainText(build_start_preview(settings.telegram, preview_assets))
        self._update_telegram_broker_summary()
    def _update_telegram_broker_summary(self) -> None:
        if not hasattr(self, "telegram_broker_summary_value"):
            return
        broker_key = str(self.telegram_preferred_broker_combo.currentData() or "quotex")
        broker_label = self.telegram_preferred_broker_combo.currentText() or "Quotex"
        selected = []
        if self.telegram_enabled_quotex_checkbox.isChecked():
            selected.append("Quotex")
        if self.telegram_enabled_pocket_checkbox.isChecked():
            selected.append("IQ Option")
        if self.telegram_enabled_exness_checkbox.isChecked():
            selected.append("Forex Market")
        if self.telegram_use_all_brokers_checkbox.isChecked():
            summary_label = "All Selected Brokers"
        else:
            summary_label = broker_label
        selected_text = ", ".join(selected) if selected else "No brokers selected"
        self.telegram_broker_summary_value.setText(f"Telegram Broker Mode: {summary_label}")
        if self.telegram_use_all_brokers_checkbox.isChecked():
            detail = (
                f"Signals will evaluate all selected brokers and use the strongest available result. "
                f"Selected brokers: {selected_text}."
            )
        elif broker_key == "iq_option":
            detail = (
                "IQ Option is selected for Telegram scans and captures. "
                "Use the IQ Option email, password, and login URL fields below."
            )
        elif broker_key == "exness":
            detail = (
                "Forex Market is selected for Telegram scans and reports. "
                "Use the API key field below, or leave it blank to fall back to the demo key."
            )
        else:
            detail = (
                "Quotex is selected for Telegram scans and captures. "
                "Desktop live mode uses the same Quotex session when Quotex is your active provider."
            )
        self.telegram_broker_summary_detail.setText(detail)

    def _start_telegram_bot(self) -> None:
        self._save_settings()
        self.controller.start_telegram_bot()

    def _update_telegram_runtime_state(self, state: TelegramRuntimeState) -> None:
        if not hasattr(self, "telegram_runtime_status"):
            return
        self.telegram_runtime_status.setText(state.status)
        details = []
        if state.me:
            details.append(f"Bot: {state.me}")
        if state.last_chat_id:
            details.append(f"Last chat: {state.last_chat_id}")
        if state.last_command:
            details.append(f"Last command: {state.last_command}")
        if state.error:
            details.append(f"Error: {state.error}")
        self.telegram_runtime_detail.setText(" | ".join(details) if details else "Bot is offline.")
        self.telegram_start_runtime_button.setEnabled(not state.running)
        self.telegram_stop_runtime_button.setEnabled(state.running)

    def _update_learning_state(self, payload: dict) -> None:
        if not hasattr(self, "learning_status_value"):
            return
        enabled = bool((payload or {}).get("enabled"))
        busy = bool((payload or {}).get("busy"))
        pending_count = int((payload or {}).get("pending_count", 0) or 0)
        samples = int((payload or {}).get("samples", 0) or 0)
        win_rate = float((payload or {}).get("win_rate", 0.0) or 0.0) * 100.0
        interval_seconds = int((payload or {}).get("interval_seconds", 45) or 45)
        verify_seconds = int((payload or {}).get("verify_seconds", 120) or 120)
        status_parts = []
        status_parts.append("Learning active" if enabled else "Learning paused")
        if busy:
            status_parts.append("scanning now")
        status_parts.append(f"interval {interval_seconds}s")
        status_parts.append(f"verify {verify_seconds}s")
        self.learning_status_value.setText(" | ".join(status_parts))
        self.learning_stats_value.setText(
            f"Samples: {samples} | Win Rate: {win_rate:.2f}% | Pending: {pending_count}"
        )
        recent = (payload or {}).get("recent") or []
        if not recent:
            self.learning_recent_value.setText("No learning results yet.")
            return
        first = recent[0]
        outcome = "WIN" if first.get("win") else "LOSS"
        self.learning_recent_value.setText(
            f"Last settled: {first.get('action')} {first.get('asset')} -> {outcome} "
            f"({first.get('reference_price')} -> {first.get('result_price')})"
        )

    def _update_signal_format_preview(self) -> None:
        if not hasattr(self, "signal_format_preview"):
            return
        settings = self._collect_settings()
        expiry_minutes = max(1, int(settings.strategy.preferred_expiry_seconds or 60) // 60)
        sticky_seconds = int(settings.strategy.sticky_signal_seconds or 75)
        preview = (
            f"Signal lock model: closed candle only\n"
            f"Preferred expiry: {expiry_minutes} minute(s)\n"
            f"Manual entry window: {sticky_seconds} seconds\n\n"
            f"When a CALL or PUT is confirmed, Eternal keeps that signal pinned for the hold window instead of "
            "repainting it away on the next tick. Deep Scan results also stay visible on the dedicated page and in "
            "the Markets focus card so manual users have time to act."
        )
        self.signal_format_preview.setPlainText(preview)

    def _tick_clock(self) -> None:
        """Update real-time clock and countdowns with absolute type-safety."""
        self.clock_value.setText(datetime.now().strftime("%H:%M:%S"))
        selected_symbol = str(self.asset_combo.currentData() or self.controller.settings.connection.selected_asset or "")

        # Safe asset lookup using wrapper
        selected_asset = None
        for asset in self._asset_cache:
            safe = self._safe_asset(asset)
            if safe.symbol == selected_symbol:
                selected_asset = safe
                break

        countdown_text = "Candle closes in: --"

        if selected_asset and selected_asset.countdown_seconds is not None and selected_asset.countdown_updated_at > 0:
            elapsed = max(0, int(time.time() - float(selected_asset.countdown_updated_at)))
            remaining = max(0, int(selected_asset.countdown_seconds) - elapsed)
            countdown_text = f"Candle closes in: {remaining}s"
        elif self._latest_candles:
            last_timestamp = self._latest_candles[-1].timestamp
            period = max(5, int(self.controller.settings.connection.candle_period or 60))
            if int(last_timestamp) > 0:
                remaining = max(1, period - (int(time.time()) % period))
            else:
                remaining = max(0, period - (int(time.time()) - int(last_timestamp)))
            countdown_text = f"Candle closes in: {remaining}s"
        self.candle_countdown_value.setText(countdown_text)
        if hasattr(self, "full_chart_countdown_value"):
            self.full_chart_countdown_value.setText(countdown_text)

    # -----------------------------------------------------------------------
    # Multi-Session Matrix handlers
    # -----------------------------------------------------------------------

    def _matrix_toggled(self, state: int) -> None:
        """Handle master switch toggle."""
        enabled = state == 2  # Qt.Checked
        self.controller.settings.matrix.enabled = enabled
        if enabled:
            self.matrix_status_label.setText("Matrix is ON. Start Matrix to activate workers.")
        else:
            self.matrix_status_label.setText("Matrix is OFF. Using single-session mode.")
            self.matrix_workers_label.setText("No active workers.")

    def _show_pin_dialog(self, email: str) -> str:
        """Show PIN interceptor dialog and wait for user input."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"2FA PIN Required - {email}")
        dialog.setModal(True)
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Quotex requires email verification for:\n\n{email}\n\nEnter the PIN code sent to your email:"))
        
        pin_edit = QLineEdit()
        pin_edit.setPlaceholderText("Enter 6-digit PIN code")
        pin_edit.textChanged.connect(lambda text="", pe=pin_edit, btn=ok_btn: btn.setEnabled(bool(pe.text().strip())))
        layout.addWidget(pin_edit)
        
        button_row = QHBoxLayout()
        ok_btn = QPushButton("Submit PIN")
        ok_btn.setEnabled(False)
        ok_btn.setObjectName("primaryButton")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("ghostButton")
        button_row.addWidget(ok_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)
        
        result = {"pin": ""}
        
        def on_ok():
            result["pin"] = pin_edit.text().strip()
            dialog.accept()
        
        def on_cancel():
            dialog.reject()
        
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(on_cancel)
        pin_edit.returnPressed.connect(on_ok)
        
        dialog.exec()
        return result["pin"]

    def _handle_pin_request(self) -> None:
        """Handle 2FA PIN request from the controller/backend."""
        email = self.email_edit.text().strip() or "Your Quotex Account"
        pin = self._show_pin_dialog(email)
        # Even if pin is empty (cancelled), submit it so the backend doesn't hang forever
        self.controller.submit_pin_code(pin)

    def _matrix_start_clicked(self) -> None:
        """Start the Multi-Session Matrix."""
        if not self.matrix_enabled_checkbox.isChecked():
            self.matrix_status_label.setText("Enable the Matrix toggle first.")
            return
        
        # Collect worker accounts from checkboxes (sync UI state to settings)
        workers = []
        for cb, email_edit, pass_edit in self.worker_checkboxes:
            if cb.isChecked():
                from eternal_quotex_bot.models import WorkerAccount
                workers.append(WorkerAccount(
                    email=email_edit.text().strip(),
                    password=pass_edit.text(),
                    enabled=True,  # Mark as enabled since checkbox is checked
                ))
        
        if not workers:
            self.matrix_status_label.setText("No workers selected. Check at least one account.")
            return
        
        # Update settings matrix workers
        self.controller.settings.matrix.enabled = True
        self.controller.settings.matrix.workers = workers
        
        self.matrix_status_label.setText(f"Starting Matrix with {len(workers)} worker(s)...")
        self.controller._log("info", f"Matrix starting with {len(workers)} workers")
        
        # Start matrix via controller
        self.controller.runner.submit(
            self.controller.start_matrix(pin_callback=self._show_pin_dialog)
        ).add_done_callback(self._matrix_start_result)
    
    def _matrix_start_result(self, future) -> None:
        """Handle matrix start result."""
        try:
            success = future.result()
            if success:
                self.matrix_status_label.setText("Matrix started successfully.")
                self.controller._log("info", "Matrix started")
            else:
                self.matrix_status_label.setText("Matrix failed to start.")
                self.controller._log("error", "Matrix start failed")
        except Exception as e:
            self.matrix_status_label.setText(f"Matrix error: {e}")
            self.controller._log("error", f"Matrix start error: {e}")

    def _continuous_monitor_toggled(self, checked: bool) -> None:
        """Handle continuous monitor button toggle."""
        if checked:
            self.controller.start_continuous_monitor()
            self.continuous_monitor_button.setText("Stop Continuous Monitor")
            self.continuous_monitor_status.setText("Monitor is ON - scanning every 5 minutes")
            self.continuous_monitor_status.setObjectName("metricValue")
        else:
            self.controller.stop_continuous_monitor()
            self.continuous_monitor_button.setText("Start Continuous Monitor")
            self.continuous_monitor_status.setText("Monitor is OFF")
            self.continuous_monitor_status.setObjectName("helperText")
            self.continuous_signal_display.setText("No continuous signal yet")

    def _update_continuous_signal(self, signal: dict) -> None:
        """Update the continuous signal display."""
        if signal and signal.get("asset"):
            action = signal.get("action", "")
            asset = signal.get("asset", "")
            confidence = signal.get("confidence", 0)
            conf_pct = int(confidence * 100)
            pattern = signal.get("pattern", "none")
            duration = signal.get("duration", 60)
            price = signal.get("price", 0)
            
            self.continuous_signal_display.setText(
                f"🚨 {action} {asset} @ {conf_pct}% confidence\n"
                f"Price: {price:.5f} | Pattern: {pattern} | Duration: {duration}s\n"
                f"Enter trade NOW - signal may expire soon!"
            )
            self.continuous_monitor_status.setText(f"Signal found: {action} {asset} at {conf_pct}%")

    def _scan_mode_changed(self) -> None:
        """Handle scan mode change."""
        mode = str(self.scan_mode_combo.currentData() or "sniper")
        self.controller.set_scan_mode(mode)

    def _sniper_pairs_changed(self) -> None:
        """Handle sniper pairs change."""
        pairs_text = self.sniper_pairs_edit.text().strip()
        pairs = [p.strip() for p in pairs_text.split(",") if p.strip()] if pairs_text else []
        self.controller.set_sniper_pairs(pairs)

    def _suggest_active_pairs_for_sniper(self) -> None:
        """Auto-set the currently active pairs as sniper pairs."""
        active_pairs = self.controller.get_active_pairs()
        if active_pairs:
            self.sniper_pairs_edit.setText(", ".join(active_pairs))
            self.controller.set_sniper_pairs(active_pairs)
            self.controller._log("info", f"Sniper pairs auto-set to active pairs: {', '.join(active_pairs)}")
        else:
            self.controller._log("warn", "No active pairs detected. Wait for prices to load.")

    def _update_market_health(self, health_data: dict) -> None:
        """Update the Market Health Monitor table."""
        if not hasattr(self, 'market_health_table'):
            return

        self.market_health_table.setRowCount(0)
        for row_index, (symbol, data) in enumerate(sorted(health_data.items())):
            price = data.get("price", 0.0)
            last_update = data.get("last_update", 0)
            status = data.get("status", "no_data")

            # Format time since last update
            import time
            if last_update > 0:
                age = time.time() - last_update
                if age < 10:
                    time_str = f"{age:.0f}s ago"
                elif age < 60:
                    time_str = f"{age:.0f}s ago"
                else:
                    time_str = f"{age/60:.0f}m ago"
            else:
                time_str = "Never"

            # Format price
            price_str = f"{price:.5f}" if price > 0 else "--"

            # Status display
            if status == "active":
                status_str = "✓ LIVE"
            elif status == "stale":
                status_str = "⚠ Stale"
            else:
                status_str = "✗ No Data"

            self.market_health_table.insertRow(row_index)
            self.market_health_table.setItem(row_index, 0, QTableWidgetItem(self._display_asset_symbol(symbol)))
            self.market_health_table.setItem(row_index, 1, QTableWidgetItem(price_str))
            self.market_health_table.setItem(row_index, 2, QTableWidgetItem(time_str))
            self.market_health_table.setItem(row_index, 3, QTableWidgetItem(status_str))

    def _matrix_stop_clicked(self) -> None:
        """Stop the Multi-Session Matrix."""
        self.controller.runner.submit(
            self.controller.stop_matrix()
        ).add_done_callback(self._matrix_stop_result)
    
    def _matrix_stop_result(self, future) -> None:
        """Handle matrix stop result."""
        try:
            future.result()
            self.matrix_status_label.setText("Matrix stopped. Using single-session mode.")
            self.matrix_workers_label.setText("No active workers.")
            self.controller._log("info", "Matrix stopped")
        except Exception as e:
            self.controller._log("error", f"Matrix stop error: {e}")
