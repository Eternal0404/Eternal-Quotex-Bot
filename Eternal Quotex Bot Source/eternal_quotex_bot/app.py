"""
Application Entry Point v2.0 (Security Guard Edition).

IMPROVEMENTS (v2.0):
- ENFORCED GATE: The main window will NO LONGER load unless the License Gate returns True.
- SECURE INITIALIZATION: Controller is initialized early to provide diagnostic data to the gate.
- FAIL-SAFE EXIT: Immediate process termination if licensing is bypassed or failed.
"""

from __future__ import annotations

import sys
import traceback
import importlib
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLoggingCategory

QLoggingCategory.setFilterRules("*.debug=false\n")

open("startup.log", "w").write(f"{datetime.now()}: app.py starting\n")

if True:
    from .controller import BotController
    from .paths import bootstrap_runtime, log_file
    from .ui.glassmorphism_theme import apply_glassmorphism_theme
    from .ui.license_gate import run_license_gate
    from .ui.main_window import MainWindow


def main() -> int:
    def run_with_timeout(func, timeout_sec: int = 30):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func)
            try:
                return future.result(timeout=timeout_sec)
            except TimeoutError:
                open("error.log", "w").write(f"{datetime.now()}: initialization timeout > {timeout_sec}s\n")
                return 1
    
    def init_app():
        app = QApplication(sys.argv)
        apply_glassmorphism_theme(app)
        
        try:
            bootstrap_runtime()
        except Exception as exc:
            QMessageBox.critical(None, "Startup Error", f"Failed to initialize runtime: {exc}")
            return 1

        try:
            controller = BotController()
        except Exception as exc:
            error_text = f"{exc}\n\n{traceback.format_exc()}"
            QMessageBox.critical(None, "Init Error", f"Failed to start controller:\n\n{error_text}")
            return 1

        try:
            if not run_license_gate(controller):
                controller.shutdown()
                return 0
        except Exception as exc:
            QMessageBox.critical(None, "Security Error", f"Fatal license engine failure: {exc}")
            return 1

        try:
            window = MainWindow(controller)
            def close_on_license_invalidated(reason: str) -> None:
                QMessageBox.critical(window, "License Revoked", reason or "This license is no longer active.")
                controller.shutdown()
                app.quit()

            controller.license_invalidated.connect(close_on_license_invalidated)
            window.show()
        except Exception as exc:
            error_text = f"{exc}\n\n{traceback.format_exc()}"
            try:
                with open(log_file(), "a", encoding="utf-8") as f:
                    f.write(f"\n--- FATAL UI ERROR ---\n{error_text}\n")
            except: pass
            
            QMessageBox.critical(None, "UI Error", f"Failed to create the main window:\n\n{error_text}")
            controller.shutdown()
            return 1

        return app.exec()
    
    return run_with_timeout(init_app, 30)
