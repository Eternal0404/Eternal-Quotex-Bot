"""
AI Signal Learner v4 (Apex-Adaptive Memory): Atomic and Stable Online Learning.

IMPROVEMENTS (v4):
- ATOMIC SAVE: Uses tempfile + os.replace to prevent JSON corruption during crashes.
- FLASH MEMORY (10-trade): Prioritizes the immediate market cycle for 10-minute adaptation.
- REGIME-AWARE WEIGHTS: Blends long-term bias with immediate 'Flash' win-rates.
- AUTO-COMPOUND SIGNALING: Calculates win-probability based on recent asset history.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .models import StrategyDecision
from .paths import cache_dir

MAX_ASSET_STATS = 200

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FastStats:
    wins: int = 0
    losses: int = 0
    recent_outcomes: list[bool] = field(default_factory=list) # Last 20 trades
    
    @property
    def flash_win_rate(self) -> float:
        if not self.recent_outcomes: return 0.5
        return sum(self.recent_outcomes) / len(self.recent_outcomes)


class SignalLearner:
    """Fast-adaptive AI learner with atomic persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cache_dir() / "signal_learner_v4.json"
        self.asset_stats: dict[str, FastStats] = {}
        self.global_bias: float = 1.0
        self.samples = 0
        self.state = SimpleNamespace()
        self._load()

    def _load(self) -> None:
        """Robust load with recovery."""
        if not self.path.exists(): return
        try:
            content = self.path.read_text(encoding="utf-8")
            if not content.strip(): return
            
            data = json.loads(content)
            self.global_bias = data.get("global_bias", 1.0)
            self.samples = data.get("samples", 0)
            for k, v in data.get("asset_stats", {}).items():
                self.asset_stats[k] = FastStats(
                    wins=v.get("wins", 0),
                    losses=v.get("losses", 0),
                    recent_outcomes=v.get("recent_outcomes", [])
                )
        except (json.JSONDecodeError, KeyError):
            # Attempt to restore from backup if possible, else reset
            bak_path = self.path.with_suffix(".bak")
            if bak_path.exists():
                os.replace(str(bak_path), str(self.path))
                self._load()

    def save(self) -> None:
        """Atomic save to prevent data corruption."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "global_bias": self.global_bias,
                "samples": self.samples,
                "asset_stats": {k: {"wins": v.wins, "losses": v.losses, "recent_outcomes": v.recent_outcomes} for k, v in self.asset_stats.items()}
            }
            
            # Create backup of current file before overwriting
            if self.path.exists():
                try: os.replace(str(self.path), str(self.path.with_suffix(".bak")))
                except: pass

            fd, temp_path = tempfile.mkstemp(dir=str(self.path.parent), prefix="learner_")
            try:
                with os.fdopen(fd, 'w', encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, str(self.path))
                try:
                    self.path.with_suffix(".bak").unlink(missing_ok=True)
                except OSError:
                    pass
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
        except Exception as e:
            _logger.error(f"Failed to save SignalLearner data: {e}")

    def adjusted_confidence(
        self,
        symbol: str | None = None,
        base_confidence: float | None = None,
        payout: float = 0.0,
        **kwargs,
    ) -> tuple[float, float, int]:
        if symbol is None:
            symbol = str(kwargs.get("asset", "unknown"))
        decision = kwargs.get("decision")
        if base_confidence is None:
            base_confidence = float(getattr(decision, "confidence", 0.5) or 0.5)
        stats = self.asset_stats.get(symbol, FastStats())
        flash_wr = stats.flash_win_rate
        
        # Predictive Filter
        multiplier = 1.0
        if len(stats.recent_outcomes) >= 3:
            if flash_wr < 0.45: multiplier = 0.75 # Slashed
            elif flash_wr > 0.75: multiplier = 1.15 # Boosted
                
        adjusted = base_confidence * multiplier * self.global_bias
        return max(0.50, min(0.999, adjusted)), flash_wr, self.samples

    def record_trade_outcome(self, context: dict[str, Any], win: bool, profit: float = 0.0) -> dict[str, Any]:
        symbol = context.get("asset", "unknown")
        stats = self.asset_stats.setdefault(symbol, FastStats())
        
        stats.recent_outcomes.append(win)
        if len(stats.recent_outcomes) > 20: stats.recent_outcomes.pop(0)
            
        if win: stats.wins += 1
        else: stats.losses += 1
        self.samples += 1
        
        # Dynamic Market Efficiency Tracker
        total_wins = sum(s.wins for s in self.asset_stats.values())
        total_wr = total_wins / max(1, self.samples)
        self.global_bias = 0.85 + (total_wr * 0.3) # Range 0.85 to 1.15
        
        # Cleanup old entries if dict exceeds limit
        if len(self.asset_stats) > MAX_ASSET_STATS:
            self._cleanup_asset_stats()
        
        self.save()
        return {"asset": symbol, "win": win, "flash_wr": stats.flash_win_rate}

    def _cleanup_asset_stats(self) -> None:
        """Remove assets with lowest sample counts to stay under limit."""
        if len(self.asset_stats) <= MAX_ASSET_STATS:
            return
        sorted_assets = sorted(self.asset_stats.items(), key=lambda x: x[1].wins + x[1].losses)
        to_remove = len(self.asset_stats) - MAX_ASSET_STATS
        for i in range(to_remove):
            del self.asset_stats[sorted_assets[i][0]]

    def snapshot(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "asset_stats": {k: {"wr": round(v.flash_win_rate, 2), "count": len(v.recent_outcomes)} for k, v in self.asset_stats.items()}
        }

    def create_outcome_context(self, asset, decision, payout, period_seconds, reference_price, source):
        return {"asset": asset, "decision_conf": decision.confidence}
