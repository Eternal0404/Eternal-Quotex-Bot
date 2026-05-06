"""
Device Identity & Fingerprinting v2.0 (Stable Multi-Vector).

IMPROVEMENTS (v2.0):
- BIOS UUID Integration: Uses CimInstance/WMIC for immutable hardware identity.
- FALLBACK CHAIN: Cascades from UUID -> Disk Serial -> Legacy Fingerprint.
- TOTAL SYNC: Ensures Diagnostics and LicenseClient use the EXACT same ID.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import os
import platform
import subprocess
import uuid


_RAW_HARDWARE_ID_CACHE: str | None = None
_MACHINE_FINGERPRINT_CACHE: str | None = None


def _get_raw_hardware_id() -> str:
    """Retrieves the most stable hardware identifier available."""
    global _RAW_HARDWARE_ID_CACHE
    if _RAW_HARDWARE_ID_CACHE is not None:
        return _RAW_HARDWARE_ID_CACHE
    try:
        raw_id = ""
        if platform.system() == "Windows":
            # 1. Try Product UUID (BIOS/Motherboard)
            try:
                # Use a slightly more robust command than before
                cmd = "powershell -NoProfile -Command \"(Get-CimInstance Win32_ComputerSystemProduct).UUID\""
                raw_id = subprocess.check_output(cmd, shell=True, timeout=3, stderr=subprocess.DEVNULL).decode("utf-8").strip()
            except: pass
            
            # 2. Try Disk Serial if UUID is null/generic
            if not raw_id or "0000" in raw_id or "FFFF" in raw_id:
                try:
                    cmd = "powershell -NoProfile -Command \"(Get-PhysicalDisk | Select-Object -First 1).SerialNumber\""
                    raw_id = subprocess.check_output(cmd, shell=True, timeout=3, stderr=subprocess.DEVNULL).decode("utf-8").strip()
                except: pass
        
        _RAW_HARDWARE_ID_CACHE = raw_id or ""
        return _RAW_HARDWARE_ID_CACHE
    except:
        _RAW_HARDWARE_ID_CACHE = ""
        return ""


def machine_fingerprint() -> str:
    """Return a globally stable machine fingerprint."""
    global _MACHINE_FINGERPRINT_CACHE
    if _MACHINE_FINGERPRINT_CACHE is not None:
        return _MACHINE_FINGERPRINT_CACHE
    hw_id = _get_raw_hardware_id()
    
    # If hardware ID extraction completely failed, use a stable legacy mix
    if not hw_id:
        parts = [
            str(uuid.getnode()),
            platform.node(),
            platform.system(),
            platform.machine(),
            os.getenv("PROCESSOR_IDENTIFIER", ""),
        ]
        hw_id = "|".join(part.strip().lower() for part in parts if str(part or "").strip())
    
    # Standardize as a Salted SHA256
    salt = "eternal_alpha_2026_apex"
    _MACHINE_FINGERPRINT_CACHE = hashlib.sha256(f"{hw_id}:{salt}".encode("utf-8")).hexdigest()
    return _MACHINE_FINGERPRINT_CACHE


def machine_id() -> str:
    """Alias for machine_display_id for backward compatibility."""
    return machine_display_id()


def machine_display_id(length: int = 16) -> str:
    """Returns the standardized ID used for registration and diagnostics."""
    return machine_fingerprint()[: max(8, int(length or 16))].upper()


def machine_fernet_key(namespace: str = "default") -> bytes:
    seed = f"{namespace}|{machine_fingerprint()}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(digest)


PBKDF2_SALT = b"eternal_quotex_bot_v2_salt_2026"


def machine_fernet_key_pbkdf2(namespace: str = "default") -> bytes:
    seed = f"{namespace}|{machine_fingerprint()}".encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", seed, PBKDF2_SALT, 100000, dklen=32)
    return base64.urlsafe_b64encode(key)
