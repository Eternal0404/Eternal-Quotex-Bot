from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "EternalQuotexBot"
PACKAGE_DIR = Path(__file__).resolve().parent
_RESOLVED_APP_DIR: Path | None = None


def app_data_dir() -> Path:
    global _RESOLVED_APP_DIR
    if _RESOLVED_APP_DIR is not None:
        return _RESOLVED_APP_DIR

    override = os.getenv("ETERNAL_QUOTEX_BOT_DATA_DIR")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))

    if sys.platform.startswith("win"):
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    candidates.extend([base / APP_DIR_NAME, Path.cwd() / ".eternal_quotex_bot"])

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _RESOLVED_APP_DIR = candidate
            return candidate
        except OSError:
            continue

    _RESOLVED_APP_DIR = Path.cwd() / ".eternal_quotex_bot"
    _RESOLVED_APP_DIR.mkdir(parents=True, exist_ok=True)
    return _RESOLVED_APP_DIR


def runtime_dir() -> Path:
    return app_data_dir() / "runtime"


def cache_dir() -> Path:
    return app_data_dir() / "cache"


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def log_file() -> Path:
    return app_data_dir() / "activity.log"


def resource_path(name: str) -> Path:
    return PACKAGE_DIR / "resources" / name


def ensure_runtime_dirs() -> None:
    for directory in (app_data_dir(), runtime_dir(), cache_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def bootstrap_runtime() -> Path:
    ensure_runtime_dirs()
    os.chdir(runtime_dir())
    return runtime_dir()
