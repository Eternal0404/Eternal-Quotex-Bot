from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, TypeVar

from cryptography.fernet import Fernet, InvalidToken

from .device import machine_fernet_key, machine_fingerprint, machine_fernet_key_pbkdf2
from .models import (
    AppSettings,
    ConnectionProfile,
    LicenseSettings,
    MatrixSettings,
    RiskSettings,
    StrategySettings,
    TelegramSettings,
    UiSettings,
    WorkerAccount,
)
from .paths import settings_file


T = TypeVar("T")

# EMBEDDED CONFIGURATION - Final Production Alignment
MANAGED_FOREX_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

# Managed license defaults are embedded so packaged users do not need a .env file.
# Environment variables still win, which keeps development/testing flexible.
MANAGED_LICENSE_API_URL = os.getenv(
    "LICENSE_API_URL",
    "https://vxwfmqvjwjxlrfskopts.supabase.co/functions/v1/license-validate",
).strip()
MANAGED_LICENSE_SHARED_TOKEN = os.getenv(
    "LICENSE_SHARED_TOKEN",
    "ef5a0629201f5f0536521cb2e74665ceba019734c8cb771617dcd3f37edecb28",
).strip()
EMBEDDED_ADMIN_LICENSE_KEY = os.getenv("ADMIN_LICENSE_KEY", "raiyanetharyt04@gmail.com").strip()


def _load_dataclass(dataclass_type: type[T], payload: dict[str, Any] | None) -> T:
    payload = payload or {}
    allowed = {field.name for field in fields(dataclass_type)}
    filtered = {key: value for key, value in payload.items() if key in allowed}
    if dataclass_type is MatrixSettings and isinstance(filtered.get("workers"), list):
        filtered["workers"] = [
            worker if isinstance(worker, WorkerAccount) else _load_dataclass(WorkerAccount, worker)
            for worker in filtered["workers"]
        ]
    return dataclass_type(**filtered)


def _apply_managed_defaults(settings: AppSettings) -> AppSettings:
    if not str(settings.connection.exness_server or "").strip():
        settings.connection.exness_server = MANAGED_FOREX_API_KEY
    if not str(settings.telegram.exness_server or "").strip():
        settings.telegram.exness_server = settings.connection.exness_server
    if int(settings.connection.trade_duration or 0) in {0, 60}:
        settings.connection.trade_duration = 120
    if int(settings.strategy.preferred_expiry_seconds or 0) in {0, 60}:
        settings.strategy.preferred_expiry_seconds = 120
    settings.license.provider_name = str(settings.license.provider_name or "custom")
    settings.license.poll_seconds = max(5, int(settings.license.poll_seconds or 10))
    settings.license.remember_license_key = bool(settings.license.remember_license_key)
    
    # Apply managed URL and token for packaged builds.
    if MANAGED_LICENSE_API_URL and not str(settings.license.api_url or "").strip():
        settings.license.api_url = MANAGED_LICENSE_API_URL
    if MANAGED_LICENSE_SHARED_TOKEN and not str(settings.license.api_token or "").strip():
        settings.license.api_token = MANAGED_LICENSE_SHARED_TOKEN

    # Managed builds must always start behind the license gate.
    if settings.license.api_url:
        settings.license.enabled = True

    return settings


def _credentials_file(path: Path) -> Path:
    return path.parent / "credentials.enc"


def _secure_store_credentials(path: Path, email: str, password: str, pin: str = "") -> None:
    creds_file = _credentials_file(path)
    try:
        if not any([email, password, pin]):
            if creds_file.exists():
                creds_file.unlink()
            return
        payload = json.dumps({"email": email, "password": password, "pin": pin}, ensure_ascii=True).encode("utf-8")
        token = Fernet(machine_fernet_key("credentials")).encrypt(payload)
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_bytes(token)
    except Exception:
        pass


def _load_stored_credentials(path: Path) -> tuple[str, str, str]:
    creds_file = _credentials_file(path)
    if not creds_file.exists():
        return "", "", ""
    try:
        payload = Fernet(machine_fernet_key("credentials")).decrypt(creds_file.read_bytes())
        data = json.loads(payload.decode("utf-8"))
        return (
            str(data.get("email", "") or ""),
            str(data.get("password", "") or ""),
            str(data.get("pin", "") or ""),
        )
    except (InvalidToken, OSError, ValueError, json.JSONDecodeError):
        return "", "", ""


def _get_licensing_fernet() -> Fernet:
    """Get a Fernet instance for licensing state encryption."""
    from .device import machine_fingerprint
    import hashlib
    import base64
    key = base64.urlsafe_b64encode(hashlib.sha256(machine_fingerprint().encode("utf-8")).digest())
    return Fernet(key)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_file()
        self._credential_override = _load_stored_credentials(self.path)

    def load(self) -> AppSettings:
        self._credential_override = _load_stored_credentials(self.path)
        
        if not self.path.exists():
            settings = _apply_managed_defaults(AppSettings())
            self._restore_credentials(settings)
            return settings
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = _apply_managed_defaults(AppSettings())
            self._restore_credentials(settings)
            return settings

        # Decrypt license cache fields if they exist
        license_data = payload.get("license", {})
        if license_data:
            f = _get_licensing_fernet()
            try:
                for field in ["cache_valid_until", "cached_validation_status", "cached_expires_at", "integrity_hash", "is_admin"]:
                    val = license_data.get(field)
                    if isinstance(val, str) and val:
                        decrypted = f.decrypt(val.encode("utf-8")).decode("utf-8")
                        if field == "cache_valid_until":
                            license_data[field] = float(decrypted)
                        elif field == "is_admin":
                            license_data[field] = decrypted.lower() == "true"
                        else:
                            license_data[field] = decrypted
            except Exception:
                for field in ["cache_valid_until", "cached_validation_status", "cached_expires_at", "integrity_hash", "is_admin"]:
                    if field == "cache_valid_until":
                        license_data[field] = 0.0
                    elif field == "is_admin":
                        license_data[field] = False
                    else:
                        license_data[field] = ""

        settings = AppSettings(
            connection=_load_dataclass(ConnectionProfile, payload.get("connection")),
            strategy=_load_dataclass(StrategySettings, payload.get("strategy")),
            risk=_load_dataclass(RiskSettings, payload.get("risk")),
            ui=_load_dataclass(UiSettings, payload.get("ui")),
            telegram=_load_dataclass(TelegramSettings, payload.get("telegram")),
            matrix=_load_dataclass(MatrixSettings, payload.get("matrix")),
            license=_load_dataclass(LicenseSettings, payload.get("license")),
        )
        settings = _apply_managed_defaults(settings)

        self._restore_credentials(settings)

        if not settings.connection.remember_password:
            settings.connection.password = ""
            settings.connection.email_pin = ""
            settings.connection.quotex_password = ""
            settings.connection.quotex_email_pin = ""
        if not settings.license.remember_license_key:
            settings.license.license_key = ""
        return settings

    def _restore_credentials(self, settings: AppSettings) -> None:
        stored_email, stored_pass, stored_pin = self._credential_override
        
        if stored_email and not settings.connection.email:
            settings.connection.email = stored_email
            settings.connection.quotex_email = stored_email
        if stored_pass and not settings.connection.password:
            settings.connection.password = stored_pass
            settings.connection.quotex_password = stored_pass
        if stored_pin and not settings.connection.email_pin:
            settings.connection.email_pin = stored_pin
            settings.connection.quotex_email_pin = stored_pin
        if settings.connection.email and not settings.connection.quotex_email:
            settings.connection.quotex_email = settings.connection.email
        if settings.connection.password and not settings.connection.quotex_password:
            settings.connection.quotex_password = settings.connection.password
        if settings.connection.email_pin and not settings.connection.quotex_email_pin:
            settings.connection.quotex_email_pin = settings.connection.email_pin

    def save(self, settings: AppSettings) -> None:
        settings = _apply_managed_defaults(settings)
        if not settings.connection.email and settings.connection.quotex_email:
            settings.connection.email = settings.connection.quotex_email
        if not settings.connection.quotex_email and settings.connection.email:
            settings.connection.quotex_email = settings.connection.email
        if not settings.connection.password and settings.connection.quotex_password:
            settings.connection.password = settings.connection.quotex_password
        if not settings.connection.quotex_password and settings.connection.password:
            settings.connection.quotex_password = settings.connection.password
        if not settings.connection.email_pin and settings.connection.quotex_email_pin:
            settings.connection.email_pin = settings.connection.quotex_email_pin
        if not settings.connection.quotex_email_pin and settings.connection.email_pin:
            settings.connection.quotex_email_pin = settings.connection.email_pin
        payload = asdict(settings)
        
        f = _get_licensing_fernet()
        license_payload = payload.get("license", {})
        if license_payload:
            for field_name in ["cache_valid_until", "cached_validation_status", "cached_expires_at", "integrity_hash", "is_admin"]:
                val = str(license_payload.get(field_name, "") or "")
                if val:
                    license_payload[field_name] = f.encrypt(val.encode("utf-8")).decode("utf-8")

        payload["connection"]["password"] = ""
        payload["connection"]["quotex_password"] = ""
        payload["connection"]["email_pin"] = ""
        payload["connection"]["quotex_email_pin"] = ""
        
        # Keep managed API URL clean in settings.json but use it at runtime
        if MANAGED_LICENSE_API_URL and payload["license"].get("api_url") == MANAGED_LICENSE_API_URL:
            payload["license"]["api_url"] = ""
        if MANAGED_LICENSE_SHARED_TOKEN and payload["license"].get("api_token") == MANAGED_LICENSE_SHARED_TOKEN:
            payload["license"]["api_token"] = ""
        if not settings.license.remember_license_key:
            payload["license"]["license_key"] = ""
            
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if settings.connection.remember_password and (
            settings.connection.email
            or settings.connection.password
            or settings.connection.email_pin
            or settings.connection.quotex_email
            or settings.connection.quotex_password
            or settings.connection.quotex_email_pin
        ):
            _secure_store_credentials(
                self.path,
                settings.connection.email or settings.connection.quotex_email or "",
                settings.connection.password or settings.connection.quotex_password or "",
                settings.connection.email_pin or settings.connection.quotex_email_pin or "",
            )
        else:
            _secure_store_credentials(self.path, "", "", "")
        self._credential_override = _load_stored_credentials(self.path)
