"""License validation and security for Eternal Quotex Bot."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .device import machine_id
from .paths import app_data_dir

if TYPE_CHECKING:
    from .models import LicenseSettings

_logger = logging.getLogger("eternal_quotex_licensing")

_EMBEDDED_ADMIN_KEY = "raiyanetharyt04@gmail.com"

_API_URL = os.getenv("LICENSE_API_URL", "https://api.quotexbot.com/license/verify")
_API_TOKEN = os.getenv("LICENSE_SHARED_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
_TIMEOUT = 30.0

# Fallback for network issues - allow embedded admin if API unreachable
_NETWORK_FALLBACK = True


@dataclass
class LicenseValidationResult:
    ok: bool = False
    valid: bool = False
    active: bool = False
    reason: str = ""
    status: str = "unknown"
    error_code: str = ""
    is_admin: bool = False
    close_app: bool = False

    def __post_init__(self) -> None:
        if self.valid or self.active:
            self.ok = self.ok or self.valid or self.active


@dataclass
class LicenseRateLimiter:
    path: Path = field(default_factory=lambda: Path(app_data_dir()) / "shield_sec_v5.json")
    data: dict = field(default_factory=dict)

    def _load(self) -> dict:
        try:
            if self.path.exists():
                c = self.path.read_text(encoding="utf-8")
                if c.strip():
                    return json.loads(c)
        except Exception:
            pass
        return {"a": 0, "l": 0.0}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        except Exception as e:
            _logger.warning(f"Save error: {e}")

    def record_failure(self) -> None:
        self.data["a"] = self.data.get("a", 0) + 1
        if self.data["a"] >= 5:
            self.data["l"] = time.time() + 600
            self.data["a"] = 0
        self._save()

    def record_success(self) -> None:
        self.data["a"] = 0
        self._save()

    def is_locked(self) -> bool:
        return bool(self.data.get("l", 0.0) and time.time() < self.data["l"])


class LicenseValidator:
    def __init__(self, hw_id: str = "", api_url: str = "", api_token: str = "") -> None:
        self.hw_id = hw_id or machine_id()
        self.api_url = api_url or _API_URL
        self.api_token = api_token or _API_TOKEN
        self.rate_limiter = LicenseRateLimiter()

    def validate(self, license_key: str, email: str = "") -> LicenseValidationResult:
        if not license_key:
            return LicenseValidationResult(ok=False, reason="License key required", error_code="empty_key")

        if self.rate_limiter.is_locked():
            return LicenseValidationResult(ok=False, reason="Rate limit exceeded", error_code="rate_limited")

        # Check embedded admin key (case-insensitive) - always works
        if _EMBEDDED_ADMIN_KEY and str(license_key or "").lower() == _EMBEDDED_ADMIN_KEY.lower():
            return LicenseValidationResult(ok=True, is_admin=True, reason="Embedded admin", valid=True, active=True)

        # Try network validation
        try:
            payload = json.dumps({"license_key": license_key, "machine_id": self.hw_id, "email": email, "app_version": "5.1"}).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
                "x-api-key": self.api_token,
                "User-Agent": "EternalQuotexBot/5.1"
            }
            req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status != 200:
                    self.rate_limiter.record_failure()
                    return LicenseValidationResult(ok=False, reason=f"Server: {resp.status}", error_code="server_error")

                data = json.loads(body)
                if data.get("ok"):
                    self.rate_limiter.record_success()
                    return LicenseValidationResult(
                        ok=True,
                        is_admin=data.get("is_admin", False),
                        reason=data.get("reason", "Active")
                    )

                self.rate_limiter.record_failure()
                return LicenseValidationResult(
                    ok=False,
                    reason=data.get("error", "Invalid"),
                    error_code=data.get("code", "invalid")
                )

        except urllib.error.HTTPError as e:
            self.rate_limiter.record_failure()
            return LicenseValidationResult(ok=False, reason=f"HTTP {e.code}", error_code="http_error")

        except Exception as e:
            self.rate_limiter.record_failure()
            return LicenseValidationResult(ok=False, reason=f"Network: {str(e)}", error_code="network_error")

    def generate_key(self, email: str = "") -> str:
        seed = f"{email}:{self.hw_id}:{time.time()}:{secrets.token_hex(8)}"
        return f"GEN-{hashlib.sha256(seed.encode()).hexdigest()[:16].upper()}"

    def revoke_key(self, license_key: str) -> bool:
        try:
            payload = json.dumps({"action": "revoke", "license_key": license_key}).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
                "x-api-key": self.api_token
            }
            req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.status == 200

        except Exception:
            return False

    def validate_settings(self, settings: "LicenseSettings") -> LicenseValidationResult:
        return self.validate(
            license_key=settings.license_key,
            email=""
        )

    def create_license(self, settings: "LicenseSettings", **kwargs: Any) -> LicenseValidationResult:
        try:
            payload = {
                "action": "create",
                "license_key": kwargs.get("license_key", ""),
                "machine_id": kwargs.get("machine_id", ""),
                "duration_days": kwargs.get("duration_days"),
                "lifetime": kwargs.get("lifetime", False),
                "notes": kwargs.get("notes", ""),
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            payload = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
                "x-api-key": self.api_token
            }
            req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                return LicenseValidationResult(
                    ok=data.get("ok", False),
                    reason=data.get("reason", "")
                )
        except Exception as e:
            return LicenseValidationResult(ok=False, reason=f"Network: {str(e)}", error_code="network_error")

    def delete_license(self, settings: "LicenseSettings", key: str) -> bool:
        try:
            payload = json.dumps({"action": "delete", "license_key": key}).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
                "x-api-key": self.api_token
            }
            req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_licenses(self, settings: "LicenseSettings", limit: int = 100) -> list:
        try:
            payload = json.dumps({"action": "list", "limit": limit}).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
                "x-api-key": self.api_token
            }
            req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                return data.get("licenses", [])
        except Exception:
            return []

    def revoke_license(self, settings: "LicenseSettings", key: str, reason: str = "") -> bool:
        return self.revoke_key(key)


LicenseClient = LicenseValidator