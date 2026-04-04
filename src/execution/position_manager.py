from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.core.constants import ExitReason, OptionType, OrderSide, PositionStatus, SignalType
from src.core.logger import get_logger

logger = get_logger("position_manager")


@dataclass
class Trade:
    trade_id: str
    symbol: str
    side: OrderSide
    entry_price: float
    quantity: int
    entry_time: datetime
    stop_loss: float
    target: float
    # Option-specific fields
    option_type: Optional[OptionType] = None
    strike: float = 0.0
    expiry: str = ""
    option_security_id: str = ""
    underlying_price_at_entry: float = 0.0
    # Common fields
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: Optional[ExitReason] = None
    status: PositionStatus = PositionStatus.OPEN
    pnl: float = 0.0
    order_id: str = ""
    trailing_sl: float = 0.0
    peak_price: float = 0.0
    notes: str = ""

    @property
    def is_option(self) -> bool:
        return self.option_type is not None

    def close(self, exit_price: float, exit_time: datetime, reason: ExitReason) -> None:
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.status = PositionStatus.CLOSED
        # For option buying: always BUY to enter, SELL to exit
        # P&L = (sell_premium - buy_premium) * quantity
        self.pnl = (exit_price - self.entry_price) * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        return 0.0

    def display_name(self) -> str:
        if self.is_option:
            ot = "CE" if self.option_type == OptionType.CALL else "PE"
            return f"{self.symbol} {self.strike:.0f}{ot}"
        return self.symbol

    def __repr__(self) -> str:
        name = self.display_name()
        return (
            f"Trade({self.trade_id} BUY {name} "
            f"premium={self.entry_price:.2f} sl={self.stop_loss:.2f} "
            f"tp={self.target:.2f} status={self.status.value})"
        )


class PositionManager:
    """Tracks all open and closed positions, enforcing single-position rule.

    For options buying:
    - LONG signal → BUY CALL option
    - SHORT signal → BUY PUT option
    - Exit → SELL the option
    - All trades are BUY-side; P&L is (exit_premium - entry_premium) * qty
    """

    def __init__(self):
        self._trade_counter = 0
        self.active_trade: Optional[Trade] = None
        self.closed_trades: list[Trade] = []
        self.daily_trades: list[Trade] = []

    @property
    def has_open_position(self) -> bool:
        return self.active_trade is not None

    @property
    def daily_trade_count(self) -> int:
        return len(self.daily_trades)

    @property
    def daily_pnl(self) -> float:
        return sum(t.pnl for t in self.daily_trades if t.status == PositionStatus.CLOSED)

    def open_trade(
        self,
        symbol: str,
        signal_type: SignalType,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        target: float,
        order_id: str = "",
        option_type: OptionType | None = None,
        strike: float = 0.0,
        expiry: str = "",
        option_security_id: str = "",
        underlying_price: float = 0.0,
    ) -> Trade:
        if self.has_open_position:
            raise RuntimeError("Cannot open trade: position already open")

        self._trade_counter += 1

        trade = Trade(
            trade_id=f"T{self._trade_counter:04d}",
            symbol=symbol,
            side=OrderSide.BUY,  # Always BUY for option buying
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(),
            stop_loss=stop_loss,
            target=target,
            order_id=order_id,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            option_security_id=option_security_id,
            underlying_price_at_entry=underlying_price,
            peak_price=entry_price,
            trailing_sl=stop_loss,
        )

        self.active_trade = trade
        self.daily_trades.append(trade)
        logger.info("Opened: %s", trade)
        return trade

    def close_trade(self, exit_price: float, reason: ExitReason) -> Trade | None:
        if not self.has_open_position:
            logger.warning("No active trade to close")
            return None

        trade = self.active_trade
        trade.close(exit_price, datetime.now(), reason)
        self.closed_trades.append(trade)
        self.active_trade = None
        logger.info(
            "Closed: %s | PnL=%.2f | Reason=%s",
            trade.trade_id, trade.pnl, reason.value,
        )
        return trade

    def update_trailing_sl(self, current_price: float, trail_pct: float, activation_pct: float) -> None:
        """Update trailing SL based on option premium movement."""
        if not self.has_open_position:
            return

        trade = self.active_trade
        # For option buying, premium going up = profit
        trade.peak_price = max(trade.peak_price, current_price)
        profit_pct = ((trade.peak_price - trade.entry_price) / trade.entry_price) * 100

        if profit_pct >= activation_pct:
            new_sl = trade.peak_price * (1 - trail_pct / 100)
            if new_sl > trade.trailing_sl:
                trade.trailing_sl = new_sl
                logger.debug("Trailing SL updated to %.2f", new_sl)

    def check_sl_tp(self, current_price: float) -> ExitReason | None:
        """Check SL/TP against option premium (not underlying price)."""
        if not self.has_open_position:
            return None

        trade = self.active_trade
        # For option buying: price dropping = loss, price rising = profit
        effective_sl = max(trade.stop_loss, trade.trailing_sl) if trade.trailing_sl else trade.stop_loss

        if current_price <= effective_sl:
            return ExitReason.TRAILING_SL if trade.trailing_sl > trade.stop_loss else ExitReason.STOP_LOSS
        if current_price >= trade.target:
            return ExitReason.TARGET

        return None

    def reset_daily(self) -> None:
        self.daily_trades = []
        logger.info("Daily trade counters reset")

    def get_all_trades(self) -> list[Trade]:
        trades = list(self.closed_trades)
        if self.active_trade:
            trades.append(self.active_trade)
        return trades
