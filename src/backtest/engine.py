from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import ExitReason, OptionType, OrderSide, PositionStatus, SignalType
from src.core.logger import get_logger
from src.options.contract_selector import ContractSelector, estimate_option_premium
from src.strategy.base import BaseStrategy

logger = get_logger("backtest_engine")


class BacktestTrade:
    """Lightweight trade record for option buying backtest."""

    def __init__(
        self,
        trade_id: str,
        entry_premium: float,
        entry_time: datetime,
        quantity: int,
        stop_loss: float,
        target: float,
        option_type: OptionType,
        strike: float,
        underlying_entry: float,
        reason: str = "",
    ):
        self.trade_id = trade_id
        self.side = OrderSide.BUY
        self.entry_price = entry_premium
        self.entry_time = entry_time
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.target = target
        self.trailing_sl = stop_loss
        self.peak_price = entry_premium
        self.option_type = option_type
        self.strike = strike
        self.underlying_entry = underlying_entry
        self.exit_price: float = 0.0
        self.exit_time: Optional[datetime] = None
        self.exit_reason: Optional[ExitReason] = None
        self.pnl: float = 0.0
        self.reason = reason

    def close(self, exit_premium: float, exit_time: datetime, reason: ExitReason) -> None:
        self.exit_price = exit_premium
        self.exit_time = exit_time
        self.exit_reason = reason
        self.pnl = (exit_premium - self.entry_price) * self.quantity

    @property
    def display_name(self) -> str:
        ot = "CE" if self.option_type == OptionType.CALL else "PE"
        return f"{self.strike:.0f}{ot}"

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "side": "BUY",
            "option_type": "CE" if self.option_type == OptionType.CALL else "PE",
            "strike": self.strike,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time,
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "underlying_entry": self.underlying_entry,
            "exit_reason": self.exit_reason.value if self.exit_reason else "",
            "pnl": round(self.pnl, 2),
            "reason": self.reason,
        }


class BacktestEngine:
    """
    Event-driven backtesting engine for option buying strategy.

    Processes underlying candles to generate signals, then simulates
    option premium P&L using a simplified pricing model.
    """

    def __init__(self, config: AppConfig, strategy: BaseStrategy):
        self.config = config
        self.strategy = strategy
        self.contract_selector = ContractSelector(config)
        self.initial_capital = config.backtest.initial_capital
        self.commission = config.backtest.commission_per_trade
        self.lot_size = config.risk.lot_size
        self.max_trades_per_day = config.risk.max_trades_per_day
        self.max_loss_per_day = config.risk.max_loss_per_day

        self.trades: list[BacktestTrade] = []
        self.active_trade: Optional[BacktestTrade] = None
        self.equity_curve: list[dict] = []
        self._trade_counter = 0
        self._daily_trade_count = 0
        self._daily_pnl = 0.0
        self._current_date: Optional[str] = None

    def run(self, df: pd.DataFrame) -> list[BacktestTrade]:
        if df.empty:
            logger.error("Cannot backtest on empty data")
            return []

        df = self.strategy.compute_indicators(df)
        min_bars = max(
            self.config.ema.primary_period,
            self.config.ema.short_period,
            self.config.ema.long_period,
            self.config.sideways_filter.atr_period,
        ) + 5

        capital = self.initial_capital
        logger.info(
            "Starting backtest: %d candles, capital=%.0f, strategy=%s (OPTION BUYING)",
            len(df), capital, self.strategy.name(),
        )

        for i in range(min_bars, len(df)):
            window = df.iloc[:i + 1]
            bar = window.iloc[-1]
            bar_time = window.index[-1]
            bar_date = str(bar_time.date()) if hasattr(bar_time, "date") else str(bar_time)[:10]

            if bar_date != self._current_date:
                self._reset_daily(bar_date)

            underlying = float(bar["close"])
            underlying_high = float(bar["high"])
            underlying_low = float(bar["low"])

            signal = self.strategy.generate_signal(window)

            if self.active_trade:
                current_premium = self._estimate_premium(
                    underlying, self.active_trade.strike, self.active_trade.option_type,
                )

                # Check for opposite signal exit FIRST (fast reaction)
                if self.config.exit.exit_on_opposite_signal and signal.is_entry:
                    if self._is_opposite_signal(signal):
                        self._close_active(current_premium, bar_time, ExitReason.OPPOSITE_SIGNAL)
                        capital += self.trades[-1].pnl - self.commission
                        # Immediately re-enter on the new signal
                        if self._can_trade():
                            self._open_trade(signal, underlying, bar_time)
                            capital -= self.commission
                        self._record_equity(bar_time, capital, underlying)
                        continue

                exit_reason = self._check_exit(current_premium, bar_time)
                if exit_reason:
                    exit_premium = self._get_exit_premium(
                        exit_reason, current_premium, underlying_high, underlying_low, underlying,
                    )
                    self._close_active(exit_premium, bar_time, exit_reason)
                    capital += self.trades[-1].pnl - self.commission

                if self.active_trade and self.config.exit.trailing_sl.enabled:
                    self._update_trailing(current_premium)

            elif signal.is_entry and self._can_trade():
                self._open_trade(signal, underlying, bar_time)
                capital -= self.commission

            self._record_equity(bar_time, capital, underlying)

        if self.active_trade:
            last_underlying = float(df["close"].iloc[-1])
            last_premium = self._estimate_premium(
                last_underlying, self.active_trade.strike, self.active_trade.option_type,
            )
            self._close_active(last_premium, df.index[-1], ExitReason.FORCE_EXIT)

        logger.info("Backtest complete: %d trades", len(self.trades))
        return self.trades

    def _is_opposite_signal(self, signal) -> bool:
        """Check if new signal is opposite to active trade's direction."""
        if not self.active_trade:
            return False
        if self.active_trade.option_type == OptionType.CALL and signal.type == SignalType.SHORT:
            return True
        if self.active_trade.option_type == OptionType.PUT and signal.type == SignalType.LONG:
            return True
        return False

    def _open_trade(self, signal, underlying: float, bar_time) -> None:
        self._trade_counter += 1
        opt_type = OptionType.CALL if signal.type == SignalType.LONG else OptionType.PUT

        contract = self.contract_selector.select_contract(signal.type, underlying)
        entry_premium = self._estimate_premium(underlying, contract.strike, opt_type)

        slippage = entry_premium * (self.config.paper_trading.slippage_pct / 100)
        entry_premium += slippage

        if self.config.options.use_premium_based_sl:
            sl = entry_premium * (1 - self.config.options.premium_sl_pct / 100)
            tp = entry_premium * (1 + self.config.options.premium_target_pct / 100)
        else:
            sl = signal.stop_loss
            tp = signal.target

        trade = BacktestTrade(
            trade_id=f"BT{self._trade_counter:04d}",
            entry_premium=entry_premium,
            entry_time=bar_time,
            quantity=self.lot_size,
            stop_loss=sl,
            target=tp,
            option_type=opt_type,
            strike=contract.strike,
            underlying_entry=underlying,
            reason=signal.reason,
        )
        trade.trailing_sl = sl
        trade.peak_price = entry_premium
        self.active_trade = trade
        self._daily_trade_count += 1

    def _close_active(self, exit_premium: float, bar_time, reason: ExitReason) -> None:
        if not self.active_trade:
            return
        self.active_trade.close(exit_premium, bar_time, reason)
        self._daily_pnl += self.active_trade.pnl
        self.trades.append(self.active_trade)
        self.active_trade = None

    def _check_exit(self, current_premium: float, bar_time) -> ExitReason | None:
        trade = self.active_trade
        if not trade:
            return None

        # SL/TP checked BEFORE time exit so we capture the precise level
        eff_sl = max(trade.stop_loss, trade.trailing_sl)

        if current_premium <= eff_sl:
            return ExitReason.TRAILING_SL if trade.trailing_sl > trade.stop_loss else ExitReason.STOP_LOSS
        if current_premium >= trade.target:
            return ExitReason.TARGET

        if self.config.exit.time_based_exit.enabled:
            try:
                exit_t = time.fromisoformat(self.config.exit.time_based_exit.exit_time)
                if hasattr(bar_time, "time") and bar_time.time() >= exit_t:
                    return ExitReason.TIME_EXIT
            except (ValueError, AttributeError):
                pass

        return None

    def _get_exit_premium(
        self, reason: ExitReason, current_premium: float,
        high: float, low: float, close: float,
    ) -> float:
        trade = self.active_trade
        if reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_SL):
            eff_sl = max(trade.stop_loss, trade.trailing_sl)
            return eff_sl
        if reason == ExitReason.TARGET:
            return trade.target
        return current_premium

    def _update_trailing(self, current_premium: float) -> None:
        trade = self.active_trade
        if not trade:
            return
        cfg = self.config.exit.trailing_sl

        trade.peak_price = max(trade.peak_price, current_premium)
        profit_pct = ((trade.peak_price - trade.entry_price) / trade.entry_price) * 100

        if profit_pct >= cfg.activation_pct:
            new_sl = trade.peak_price * (1 - cfg.trail_pct / 100)
            if new_sl > trade.trailing_sl:
                trade.trailing_sl = new_sl

    def _estimate_premium(self, underlying: float, strike: float, opt_type: OptionType) -> float:
        return estimate_option_premium(underlying, strike, opt_type)

    def _can_trade(self) -> bool:
        if self._daily_trade_count >= self.max_trades_per_day:
            return False
        if self._daily_pnl <= -self.max_loss_per_day:
            return False
        return True

    def _reset_daily(self, date_str: str) -> None:
        self._current_date = date_str
        self._daily_trade_count = 0
        self._daily_pnl = 0.0

    def _record_equity(self, bar_time, capital: float, underlying: float) -> None:
        unrealized = 0.0
        if self.active_trade:
            curr_prem = self._estimate_premium(
                underlying, self.active_trade.strike, self.active_trade.option_type,
            )
            unrealized = (curr_prem - self.active_trade.entry_price) * self.active_trade.quantity

        self.equity_curve.append({
            "timestamp": bar_time,
            "equity": capital + unrealized,
            "price": underlying,
        })
