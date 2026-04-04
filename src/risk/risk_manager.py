from __future__ import annotations

from datetime import datetime, time

from src.core.config import AppConfig
from src.core.logger import get_logger
from src.execution.position_manager import PositionManager

logger = get_logger("risk_manager")


class RiskManager:
    """Enforces risk rules: max trades, max loss, trading hours, position limits."""

    def __init__(self, config: AppConfig, position_manager: PositionManager):
        self.config = config
        self.pm = position_manager
        self._kill_switch_active = False

    @property
    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def can_open_trade(self) -> tuple[bool, str]:
        if self._kill_switch_active:
            return False, "kill_switch_active"

        if self.pm.has_open_position:
            return False, "position_already_open"

        if self.pm.daily_trade_count >= self.config.risk.max_trades_per_day:
            return False, f"max_daily_trades_reached ({self.config.risk.max_trades_per_day})"

        if self.pm.daily_pnl <= -self.config.risk.max_loss_per_day:
            self._kill_switch_active = True
            logger.critical(
                "KILL SWITCH activated: daily loss %.2f exceeds limit %.2f",
                self.pm.daily_pnl,
                self.config.risk.max_loss_per_day,
            )
            return False, "max_daily_loss_reached"

        if not self.is_within_trading_hours():
            return False, "outside_trading_hours"

        return True, "ok"

    def is_within_trading_hours(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        current_time = now.time()
        start = time.fromisoformat(self.config.trading_hours.start)
        end = time.fromisoformat(self.config.trading_hours.end)
        return start <= current_time <= end

    def should_force_exit(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        force_time = time.fromisoformat(self.config.trading_hours.force_exit)
        return now.time() >= force_time

    def should_time_exit(self, now: datetime | None = None) -> bool:
        if not self.config.exit.time_based_exit.enabled:
            return False
        now = now or datetime.now()
        exit_time = time.fromisoformat(self.config.exit.time_based_exit.exit_time)
        return now.time() >= exit_time

    def compute_position_size(self, entry_price: float, stop_loss: float) -> int:
        """Calculate quantity based on risk per trade."""
        risk_amount = self.config.risk.capital_per_trade * (self.config.risk.risk_per_trade_pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return self.config.risk.lot_size

        qty = int(risk_amount / risk_per_unit)
        lot_size = self.config.risk.lot_size
        qty = max(lot_size, (qty // lot_size) * lot_size)
        return qty

    def reset_daily(self) -> None:
        self._kill_switch_active = False
        self.pm.reset_daily()
        logger.info("Risk manager daily reset")
