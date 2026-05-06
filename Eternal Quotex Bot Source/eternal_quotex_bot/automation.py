from __future__ import annotations

import time

from .models import RiskSettings, SessionStats, StrategyDecision, StrategySettings, TradeTicket

MAX_ASSET_ENTRIES = 100


class AutomationEngine:
    def __init__(self) -> None:
        self.strategy_settings = StrategySettings()
        self.risk_settings = RiskSettings()
        self.stats = SessionStats()
        self._asset_cooldowns: dict[str, float] = {} # {asset_symbol: cooldown_until_timestamp}
        self._martingale_step: dict[str, int] = {} # {asset_symbol: current_martingale_step}
        self._last_trade_amount: dict[str, float] = {} # {asset_symbol: last_trade_amount}

    def configure(self, strategy: StrategySettings, risk: RiskSettings) -> None:
        self.strategy_settings = strategy
        self.risk_settings = risk
        self.stats.automation_enabled = strategy.auto_trade_enabled

    def set_enabled(self, enabled: bool) -> None:
        self.stats.automation_enabled = enabled

    def can_trade(self, decision: StrategyDecision, current_balance: float) -> tuple[bool, str]:
        now = time.time()
        
        if not self.stats.automation_enabled:
            return False, "Automation is turned off."
        if self.stats.active_trade_id and self.risk_settings.max_open_trades <= 1:
            return False, "A trade is already active (max_open_trades=1)."
        if decision.action == "HOLD":
            return False, "Signal is HOLD."
        if decision.confidence < self.strategy_settings.min_confidence:
            return False, f"Signal confidence ({decision.confidence:.2f}) is below threshold ({self.strategy_settings.min_confidence:.2f})."
        if self.stats.net_pnl >= self.risk_settings.stop_profit:
            return False, f"Stop-profit limit reached ({self.stats.net_pnl:.2f} >= {self.risk_settings.stop_profit:.2f})."
        if self.stats.net_pnl <= -abs(self.risk_settings.stop_loss):
            return False, f"Stop-loss limit reached ({self.stats.net_pnl:.2f} <= {-abs(self.risk_settings.stop_loss):.2f})."
        if self.stats.consecutive_losses >= self.risk_settings.max_consecutive_losses:
            return False, f"Loss streak limit reached ({self.stats.consecutive_losses} >= {self.risk_settings.max_consecutive_losses})."
        if now - self.stats.last_trade_at < self.risk_settings.cooldown_seconds:
            return False, f"Global cooldown timer is still active ({int(self.risk_settings.cooldown_seconds - (now - self.stats.last_trade_at))}s remaining)."
        
        # Asset-specific cooldown
        asset_cooldown_until = self._asset_cooldowns.get(decision.asset, 0.0)
        if now < asset_cooldown_until:
            return False, f"Asset '{decision.asset}' is on cooldown ({int(asset_cooldown_until - now)}s remaining)."

        # Dynamic/Martingale sizing checks
        trade_amount = self.calculate_trade_amount(decision.confidence, decision.asset, current_balance)
        if trade_amount <= 0 or trade_amount > self.risk_settings.max_trade_amount or trade_amount > current_balance:
            return False, f"Calculated trade amount ({trade_amount:.2f}) is invalid or exceeds balance/max trade amount."

        return True, "Auto-trade is ready."

    def calculate_trade_amount(self, confidence: float, asset_symbol: str, current_balance: float) -> float:
        """Calculates the trade amount based on dynamic sizing and martingale settings."""
        base_amount = self.risk_settings.sizing_base_amount
        
        # Martingale adjustment
        if self.risk_settings.martingale_enabled:
            step = self._martingale_step.get(asset_symbol, 0)
            if step > 0: # If there was a previous loss on this asset
                last_amount = self._last_trade_amount.get(asset_symbol, base_amount)
                base_amount = last_amount * self.risk_settings.martingale_factor
                
                # Check martingale step limit
                if step >= self.risk_settings.martingale_max_steps:
                    return 0.0 # Cannot trade further in this martingale sequence
        
        # Dynamic sizing adjustment based on confidence
        if self.risk_settings.dynamic_sizing_enabled and self.risk_settings.sizing_multiplier_per_confidence_point > 0:
            confidence_delta = max(0, confidence - self.strategy_settings.min_confidence)
            confidence_points = confidence_delta * 100 # Convert 0.01 to 1 point
            
            sizing_increase = confidence_points * self.risk_settings.sizing_multiplier_per_confidence_point
            trade_amount = base_amount + sizing_increase
        else:
            trade_amount = base_amount
        
        trade_amount = round(min(trade_amount, self.risk_settings.max_trade_amount, current_balance), 2)
        return max(self.risk_settings.sizing_base_amount, trade_amount)

    def register_open(self, ticket: TradeTicket) -> None:
        self.stats.trades_taken += 1
        self.stats.active_trade_id = ticket.id
        self.stats.last_trade_at = time.time()
        self._last_trade_amount[ticket.asset] = ticket.amount
        
        # Reset martingale step for this asset if trade amount is base amount
        if ticket.amount == self.risk_settings.sizing_base_amount:
            self._martingale_step[ticket.asset] = 0

    def reset(self) -> None:
        """Reset all session state on disconnect."""
        self.stats = SessionStats()
        self._asset_cooldowns.clear()
        self._martingale_step.clear()
        self._last_trade_amount.clear()
        self.stats.active_trade_id = None

    def _cleanup_stale_entries(self) -> None:
        """Remove stale entries from tracking dicts to prevent unbounded growth."""
        now = time.time()
        stale_assets = [a for a, t in self._asset_cooldowns.items() if t < now - 86400]
        for a in stale_assets:
            self._asset_cooldowns.pop(a, None)
            self._martingale_step.pop(a, None)
            self._last_trade_amount.pop(a, None)
        if len(self._asset_cooldowns) > MAX_ASSET_ENTRIES:
            self._asset_cooldowns.clear()
            self._martingale_step.clear()
            self._last_trade_amount.clear()

    def register_result(self, ticket: TradeTicket) -> None:
        self.stats.active_trade_id = None
        
        # Apply asset cooldown
        self._asset_cooldowns[ticket.asset] = time.time() + self.risk_settings.asset_cooldown_seconds

        if ticket.result is True:
            self.stats.wins += 1
            self.stats.consecutive_losses = 0
            profit = ticket.profit if ticket.profit is not None else ticket.amount * (ticket.estimated_payout / 100)
            self.stats.net_pnl += profit
            self._martingale_step[ticket.asset] = 0 # Reset martingale on win
        elif ticket.result is False:
            self.stats.losses += 1
            self.stats.consecutive_losses += 1
            loss = ticket.profit if ticket.profit is not None else -ticket.amount
            self.stats.net_pnl += loss
            
            # Increment martingale step on loss
            current_step = self._martingale_step.get(ticket.asset, 0)
            self._martingale_step[ticket.asset] = current_step + 1
        
        # Log trade result for potential learning module
        # print(f"Trade result for {ticket.asset}: {ticket.result}. PNL: {ticket.profit}. Current Martingale Step: {self._martingale_step.get(ticket.asset, 0)}")
        
        self._cleanup_stale_entries()