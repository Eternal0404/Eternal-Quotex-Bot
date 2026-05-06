"""
Multi-Session Matrix: Manages multiple Quotex browser sessions in parallel.

Each worker account gets its own browser session and is assigned a subset
of pairs to monitor. This bypasses Quotex's per-session broadcast limit.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from eternal_quotex_bot.backend.live import (
    PREFERRED_LIVE_SYMBOLS,
    LiveQuotexBackend,
    _normalize_symbol,
    _safe_float,
)
from eternal_quotex_bot.models import AssetInfo, Candle, MatrixSettings, WorkerAccount


@dataclass
class WorkerSession:
    """Represents a single worker's browser session."""
    worker: WorkerAccount
    backend: Optional[LiveQuotexBackend] = None
    assigned_pairs: list[str] = field(default_factory=list)
    is_connected: bool = False
    last_error: str = ""
    pin_callback: Optional[Callable[[str], str]] = None  # For PIN interceptor


class MultiSessionMatrix:
    """Manages multiple Quotex sessions for parallel pair monitoring."""
    
    def __init__(self, settings: MatrixSettings, log_callback=None):
        self.settings = settings
        self.workers: list[WorkerSession] = []
        self._log = log_callback or (lambda level, msg: None)
        self._session_dir = Path(__file__).parent.parent.parent / "browser_sessions"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize worker sessions
        self._init_workers()
    
    def _init_workers(self):
        """Initialize worker sessions from settings."""
        self.workers = []
        for worker in self.settings.workers:
            if worker.enabled:
                session = WorkerSession(worker=worker)
                self.workers.append(session)
    
    def get_active_workers(self) -> list[WorkerSession]:
        """Get list of enabled and connected workers."""
        return [w for w in self.workers if w.worker.enabled and w.is_connected]
    
    def allocate_pairs(self) -> dict[str, list[str]]:
        """Dynamically allocate pairs across active workers.
        
        Returns dict mapping worker email to list of assigned pairs.
        """
        if not self.settings.enabled:
            return {}
        
        active_workers = self.get_active_workers()
        if not active_workers:
            return {}
        
        all_pairs = PREFERRED_LIVE_SYMBOLS[:]
        pairs_per_worker = len(all_pairs) // len(active_workers)
        remainder = len(all_pairs) % len(active_workers)
        
        allocation = {}
        start_idx = 0
        for i, worker in enumerate(active_workers):
            # Give remainder pairs to first workers
            count = pairs_per_worker + (1 if i < remainder else 0)
            worker.assigned_pairs = all_pairs[start_idx:start_idx + count]
            allocation[worker.worker.email] = worker.assigned_pairs
            start_idx += count
        
        self._log("info", f"Matrix allocated {len(all_pairs)} pairs across {len(active_workers)} workers")
        for email, pairs in allocation.items():
            self._log("info", f"  {email}: {len(pairs)} pairs")
        
        return allocation
    
    async def connect_all(self, pin_callback: Callable[[str], str]) -> bool:
        """Connect all enabled workers. Returns True if at least one connected."""
        if not self.settings.enabled:
            self._log("info", "Matrix is disabled - using single session mode")
            return False
        
        success_count = 0
        for session in self.workers:
            if not session.worker.enabled:
                continue
            
            try:
                self._log("info", f"Connecting worker: {session.worker.email}")
                
                # Check for cached session
                session_file = self._get_session_file(session.worker.email)
                has_cached_session = session_file.exists()
                
                # Create backend for this worker
                session.backend = LiveQuotexBackend(log_callback=self._log)
                session.pin_callback = pin_callback
                
                # For now, we need to login through the normal flow
                # The PIN interceptor will be triggered during login
                # TODO: Implement full browser automation with PIN handling
                
                session.is_connected = True
                success_count += 1
                
                if has_cached_session:
                    self._log("info", f"Worker {session.worker.email} using cached session")
                else:
                    self._log("info", f"Worker {session.worker.email} needs fresh login + PIN")
                    
            except Exception as e:
                session.last_error = str(e)
                self._log("error", f"Failed to connect worker {session.worker.email}: {e}")
        
        if success_count > 0:
            self.allocate_pairs()
        
        return success_count > 0
    
    async def disconnect_all(self):
        """Disconnect all workers and save sessions."""
        for session in self.workers:
            if session.backend is not None:
                try:
                    await session.backend.disconnect()
                except Exception:
                    pass
                session.backend = None
                session.is_connected = False
                session.assigned_pairs = []
    
    def _get_session_file(self, email: str) -> Path:
        """Get path to cached session file for a worker."""
        safe_email = email.replace("@", "_").replace(".", "_")
        return self._session_dir / f"session_{safe_email}.json"
    
    def save_session(self, email: str, session_data: dict):
        """Save browser session cookies/state to disk."""
        session_file = self._get_session_file(email)
        session_data["saved_at"] = time.time()
        session_data["email"] = email
        session_file.write_text(json.dumps(session_data, indent=2))
        self._log("info", f"Session cached for {email}")
    
    def load_session(self, email: str) -> Optional[dict]:
        """Load cached session data if available and not expired (< 24h)."""
        session_file = self._get_session_file(email)
        if not session_file.exists():
            return None
        
        try:
            data = json.loads(session_file.read_text())
            saved_at = data.get("saved_at", 0)
            if time.time() - saved_at > 86400:  # 24 hours
                self._log("info", f"Cached session for {email} expired")
                session_file.unlink()
                return None
            return data
        except Exception as e:
            self._log("error", f"Failed to load session for {email}: {e}")
            return None
    
    def get_all_prices(self) -> dict[str, float]:
        """Get combined prices from all workers."""
        all_prices = {}
        for session in self.workers:
            if session.backend and hasattr(session.backend, '_last_known_prices'):
                all_prices.update(session.backend._last_known_prices)
        return all_prices
    
    def is_matrix_enabled(self) -> bool:
        return self.settings.enabled
    
    def get_worker_status(self) -> list[dict]:
        """Get status of all workers for UI display."""
        return [
            {
                "email": w.worker.email,
                "enabled": w.worker.enabled,
                "connected": w.is_connected,
                "pairs": len(w.assigned_pairs),
                "error": w.last_error,
            }
            for w in self.workers
        ]
