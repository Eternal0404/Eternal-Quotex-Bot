from __future__ import annotations
import weakref
import time

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

import os
from eternal_quotex_bot.device import machine_display_id
from eternal_quotex_bot.settings import MANAGED_LICENSE_API_URL, MANAGED_LICENSE_SHARED_TOKEN

if TYPE_CHECKING:
    from eternal_quotex_bot.controller import BotController


def _license_length_summary(key: str) -> str:
    cleaned = str(key or "").strip()
    count = len(cleaned)
    if not cleaned:
        return "Length: 0 characters"
    return f"Length: {count} characters"


def run_license_gate(controller: "BotController") -> bool:
    """
    Mandatory License Checkpoint.
    Blocks app startup until a valid license key is entered.
    """
    license_settings = controller.settings.license
    # Read from saved settings, then embedded managed defaults.
    api_url = str(license_settings.api_url or MANAGED_LICENSE_API_URL or os.getenv("LICENSE_API_URL", "")).strip()
    api_token = str(license_settings.api_token or MANAGED_LICENSE_SHARED_TOKEN or os.getenv("LICENSE_SHARED_TOKEN", "")).strip()
    license_settings.api_url = api_url
    license_settings.api_token = api_token
    license_settings.enabled = True

    if not api_url:
        # License is enabled but no API URL is configured
        # This is a configuration error - show a dialog to the user
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "License Configuration Error",
            "License validation is enabled, but the license server URL is not configured.\n\n"
            "Please set the LICENSE_API_URL environment variable or contact your administrator.",
        )
        return False

    dialog = QDialog()
    dialog.setWindowTitle("Enter your License key")
    dialog.setModal(True)
    dialog.setMinimumWidth(460)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title = QLabel("Enter your License key")
    title.setWordWrap(True)
    title.setObjectName("heroSub")
    helper = QLabel(
        "A valid <b>license key</b> is required. Admin can use email as license key."
    )
    helper.setWordWrap(True)
    helper.setObjectName("helperText")
    helper.setStyleSheet("color: #a0aec0;")
    machine_label = QLabel(f"Machine ID: {machine_display_id()}")
    machine_label.setObjectName("helperText")

    key_edit = QLineEdit()
    key_edit.setPlaceholderText("Enter your license key")
    key_edit.setClearButtonEnabled(True)
    key_edit.setText("raiyanetharyt04@gmail.com")

    remember_checkbox = QCheckBox("Remember this license key on this machine (prefill only)")
    remember_checkbox.setChecked(bool(controller.settings.license.remember_license_key))

    meta_label = QLabel(_license_length_summary(key_edit.text()))
    meta_label.setWordWrap(True)
    meta_label.setObjectName("helperText")
    status_label = QLabel("")
    status_label.setWordWrap(True)
    status_label.setObjectName("helperText")
    status_label.setStyleSheet("color: #e53e3e;")

    button_row = QHBoxLayout()
    validate_button = QPushButton("Validate & Continue")
    validate_button.setObjectName("primaryButton")
    
    diag_button = QPushButton("Run Diagnostics")
    diag_button.setObjectName("ghostButton")
    
    reset_button = QPushButton("Clear Lockout (Admin)")
    reset_button.setObjectName("ghostButton")
    reset_button.setVisible(False)
    
    exit_button = QPushButton("Exit")
    exit_button.setObjectName("ghostButton")
    
    button_row.addWidget(validate_button)
    button_row.addWidget(diag_button)
    button_row.addWidget(reset_button)
    button_row.addWidget(exit_button)

    layout.addWidget(title)
    layout.addWidget(helper)
    layout.addWidget(machine_label)
    layout.addWidget(key_edit)
    layout.addWidget(remember_checkbox)
    layout.addWidget(meta_label)
    layout.addWidget(status_label)
    layout.addLayout(button_row)

    def run_diagnostics() -> None:
        """Run connection and hardware diagnostics."""
        from PySide6.QtWidgets import QMessageBox
        hw_id = machine_display_id()

        api_url = str(controller.settings.license.api_url or MANAGED_LICENSE_API_URL).strip()
        if not api_url:
            status_label.setText("⚠️ License API URL not configured")
            status_label.setStyleSheet("color: #dd6b20;")
        else:
            status_label.setText("✓ License API configured")
            status_label.setStyleSheet("color: #48bb78;")

        try:
            QApplication.processEvents()
        except Exception:
            pass

        QMessageBox.information(
            dialog,
            "System Diagnostics",
            f"Machine ID: {hw_id}\n"
            f"License API: {'Configured' if api_url else 'NOT CONFIGURED'}\n\n"
            "DIAGNOSTIC CHECK:\n"
            f"1. Machine ID: {hw_id[:16]}...\n"
            f"2. API URL: {'Set' if api_url else 'Missing'}\n\n"
            "If you see 'Locked to another device', provide Machine ID "
            "to admin for reset."
        )
        status_label.setText("")

    diag_button.clicked.connect(run_diagnostics)

    def attempt_validate() -> None:
        license_key = key_edit.text().strip()
        if not license_key:
            status_label.setText("Please enter your license key.")
            status_label.setStyleSheet("color: #dd6b20;")
            key_edit.setFocus()
            return
        
        validate_button.setEnabled(False)
        validate_button.setText("Verifying...")
        key_edit.setEnabled(False)
        
        try:
            # Sync settings to controller
            settings = controller.settings
            settings.license.license_key = license_key
            settings.license.api_url = api_url
            settings.license.api_token = api_token
            settings.license.enabled = True
            settings.license.remember_license_key = remember_checkbox.isChecked()
            controller.apply_settings(settings)

            result = controller.validate_license_now()
            
            if result.valid:
                status_label.setText("✓ License verified.")
                status_label.setStyleSheet("color: #48bb78; font-weight: bold;")
                try:
                    QApplication.processEvents()
                except Exception:
                    pass
                dialog.accept()
                return
            
            # IMPROVEMENT: Use the actual result.reason instead of hardcoded 'Wrong license'
            # This reveals if the issue is a machine lock, expiration, or network error.
            err_text = result.reason or "Verification failed."
            
            if "machine_lock" in result.status or "Locked" in err_text:
                status_label.setText(f"⚠️ {err_text}")
                status_label.setStyleSheet("color: #dd6b20; font-weight: bold;")
            elif "revoked" in result.status:
                status_label.setText(f"🚫 {err_text}")
                status_label.setStyleSheet("color: #e53e3e; font-weight: bold;")
            else:
                status_label.setText(f"❌ {err_text}")
                status_label.setStyleSheet("color: #e53e3e; font-weight: bold;")
            
            if result.status == "rate_limited":
                reset_button.setVisible(True)

        finally:
            validate_button.setEnabled(True)
            validate_button.setText("Validate & Continue")
            key_edit.setEnabled(True)
            key_edit.setFocus()
            key_edit.selectAll()

        key_edit.setFocus()
        key_edit.selectAll()

    validate_button.clicked.connect(attempt_validate)
    exit_button.clicked.connect(dialog.reject)
    key_edit.returnPressed.connect(attempt_validate)
    key_edit.textChanged.connect(lambda text, lbl=weakref.ref(meta_label): lbl() and lbl().setText(_license_length_summary(text)))
    
    def reset_rate_limit() -> None:
        """Reset rate limiter for admin users"""
        if hasattr(controller, '_rate_limiter') and controller._rate_limiter is not None:
            controller._rate_limiter.reset()
            status_label.setText("✅ Rate limit cleared. You can now try validating again.")
            status_label.setStyleSheet("color: #48bb78; font-weight: bold;")
            reset_button.setVisible(False)
            key_edit.setFocus()
        else:
            status_label.setText("Rate limiter not initialized.")
            status_label.setStyleSheet("color: #e53e3e;")
    
    reset_button.clicked.connect(reset_rate_limit)
    
    key_edit.setFocus()
    key_edit.selectAll()

    return dialog.exec() == QDialog.Accepted
