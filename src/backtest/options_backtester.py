from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import (
    ExitReason, OptionType, OrderSide, PositionStatus, SignalType, TradeGrade,
)
from src.core.logger import get_logger
from src.indicators.ema import compute_ma_ema, resample_higher_tf
from src.options.oi_analyzer import OIAnalyzer
from src.options.option_selector import OptionSelector, estimate_option_premium
from src.strategy.option_ema_strategy import OptionEMAStrategy
from src.strategy.signals import Signal
from src.utils.brokerage import compute_round_trip_costs

logger = get_logger("options_backtester")


class BacktestTrade:
    """Trade record for options-aware backtesting."""

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
        grade: TradeGrade = TradeGrade.C,
        confidence: float = 0.0,
        oi_signal: str = "",
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
        self.costs: float = 0.0
        self.net_pnl: float = 0.0
        self.reason = reason
        self.grade = grade
        self.confidence = confidence
        self.oi_signal = oi_signal
        self.partial_exits: list[dict] = []
        self._original_quantity: int = quantity

    def close(self, exit_premium: float, exit_time: datetime,
              reason: ExitReason, costs: float = 0.0) -> None:
        self.exit_price = exit_premium
        self.exit_time = exit_time
        self.exit_reason = reason
        self.pnl = (exit_premium - self.entry_price) * self.quantity
        partial_pnl = sum(p.get("pnl", 0) for p in self.partial_exits)
        self.pnl += partial_pnl
        self.costs = costs
        self.net_pnl = self.pnl - costs

    def partial_close(self, exit_premium: float, fraction: float) -> float:
        exit_qty = max(1, int(self.quantity * fraction))
        exit_qty = min(exit_qty, self.quantity)
        partial_pnl = (exit_premium - self.entry_price) * exit_qty
        self.partial_exits.append({
            "premium": exit_premium, "quantity": exit_qty, "pnl": partial_pnl,
        })
        self.quantity -= exit_qty
        return partial_pnl

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
            "quantity": self._original_quantity,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "underlying_entry": self.underlying_entry,
            "exit_reason": self.exit_reason.value if self.exit_reason else "",
            "pnl": round(self.pnl, 2),
            "costs": round(self.costs, 2),
            "net_pnl": round(self.net_pnl, 2),
            "reason": self.reason,
            "grade": self.grade.value,
            "confidence": round(self.confidence, 2),
            "oi_signal": self.oi_signal,
        }


class OptionsBacktester:
    """
    Options-aware backtesting engine with:
      - MA-EMA crossover signal generation on spot data
      - Multi-timeframe confirmation (5m entry, 15m confirmation)
      - OI simulation (synthetic or from data)
      - Option premium simulation via Black-Scholes-like approximation
      - Realistic Indian brokerage costs
      - Slippage modelling
      - Partial profit booking
      - Trailing stop loss
      - Greeks awareness (basic via premium estimate)
    """

    def __init__(self, config: AppConfig, strategy: OptionEMAStrategy | None = None):
        self.config = config
        self.strategy = strategy or OptionEMAStrategy(config)
        self.option_selector = OptionSelector(config)
        self.initial_capital = config.backtest.initial_capital
        self.lot_size = config.risk.lot_size
        self.max_trades_per_day = config.risk.max_trades_per_day
        self.max_loss_per_day = config.risk.max_loss_per_day
        self.next_candle_entry = config.backtest.next_candle_entry
        self.slippage_pct = config.backtest.slippage_pct

        self.trades: list[BacktestTrade] = []
        self.active_trade: Optional[BacktestTrade] = None
        self.equity_curve: list[dict] = []
        self._trade_counter = 0
        self._daily_trade_count = 0
        self._daily_pnl = 0.0
        self._current_date: Optional[str] = None
        self._pending_signal: Optional[Signal] = None
        self._consecutive_losses = 0
        self._partial_booked = False
        self._cooldown_until_bar: int = 0

    def run(self, df: pd.DataFrame) -> list[BacktestTrade]:
        if df.empty:
            logger.error("Cannot backtest on empty data")
            return []

        df = self.strategy.compute_indicators(df)

        htf_minutes = int(self.config.strategy.confirmation_timeframe.replace("m", ""))
        htf_df = resample_higher_tf(df, htf_minutes)
        if not htf_df.empty:
            htf_df = compute_ma_ema(htf_df, self.config.strategy.ma_period,
                                     self.config.strategy.ema_period)

        min_bars = max(self.config.strategy.ma_period, self.config.strategy.ema_period) + 5

        capital = self.initial_capital
        logger.info(
            "Starting options backtest: %d candles, capital=%.0f, strategy=%s "
            "(ma=%d, ema=%d, mtf=%s, slippage=%.1f%%)",
            len(df), capital, self.strategy.name(),
            self.config.strategy.ma_period, self.config.strategy.ema_period,
            self.config.strategy.confirmation_timeframe,
            self.slippage_pct,
        )

        for i in range(min_bars, len(df)):
            window = df.iloc[:i + 1]
            bar = window.iloc[-1]
            bar_time = window.index[-1]
            bar_date = str(bar_time.date()) if hasattr(bar_time, "date") else str(bar_time)[:10]

            if bar_date != self._current_date:
                self._reset_daily(bar_date)

            underlying = float(bar["close"])
            underlying_open = float(bar["open"])
            underlying_high = float(bar["high"])
            underlying_low = float(bar["low"])

            # Execute pending signal from previous bar
            if self._pending_signal and not self.active_trade:
                if self._can_trade() and i > self._cooldown_until_bar:
                    entry_price = underlying_open if self.next_candle_entry else underlying
                    self._open_trade(self._pending_signal, entry_price, bar_time)
                self._pending_signal = None

            # Build HTF window for this point
            htf_window = None
            if not htf_df.empty:
                htf_window = htf_df[htf_df.index <= bar_time]

            # Generate signal
            signal = self.strategy.generate_signal(window, htf_window)

            # Manage active trade
            if self.active_trade:
                current_premium = self._estimate_premium(
                    underlying, self.active_trade.strike, self.active_trade.option_type,
                )

                # Opposite signal exit
                if self.config.exit.exit_on_opposite_signal and signal.is_entry:
                    if self._is_opposite(signal):
                        costs = self._compute_costs(self.active_trade.entry_price, current_premium)
                        self._close_active(current_premium, bar_time,
                                           ExitReason.OPPOSITE_SIGNAL, costs)
                        capital += self.trades[-1].net_pnl

                        if self.next_candle_entry:
                            self._pending_signal = signal
                        elif self._can_trade():
                            self._open_trade(signal, underlying, bar_time)
                        self._record_equity(bar_time, capital, underlying)
                        continue

                # Partial profit booking
                if (self.config.exit.partial_exit.enabled and not self._partial_booked
                        and self.active_trade.quantity > 1):
                    pe_cfg = self.config.exit.partial_exit
                    profit_pct = ((current_premium - self.active_trade.entry_price)
                                  / self.active_trade.entry_price * 100)
                    if profit_pct >= pe_cfg.first_target_pct:
                        partial_pnl = self.active_trade.partial_close(
                            current_premium, pe_cfg.first_exit_fraction,
                        )
                        capital += partial_pnl
                        self._partial_booked = True
                        if pe_cfg.move_sl_to_cost:
                            self.active_trade.stop_loss = self.active_trade.entry_price
                            self.active_trade.trailing_sl = max(
                                self.active_trade.trailing_sl, self.active_trade.entry_price,
                            )

                # SL / TP / time exit
                exit_reason = self._check_exit(current_premium, bar_time)
                if exit_reason:
                    exit_premium = self._get_exit_premium(exit_reason, current_premium)
                    costs = self._compute_costs(self.active_trade.entry_price, exit_premium)
                    self._close_active(exit_premium, bar_time, exit_reason, costs)
                    capital += self.trades[-1].net_pnl

                # Trailing SL
                if self.active_trade and self.config.exit.trailing_sl.enabled:
                    self._update_trailing(current_premium)

            elif signal.is_entry and self._can_trade() and i > self._cooldown_until_bar:
                min_grade = TradeGrade(self.config.strategy.min_grade)
                if signal.passes_grade_filter(min_grade):
                    if self.next_candle_entry:
                        self._pending_signal = signal
                    else:
                        self._open_trade(signal, underlying, bar_time)

            self._record_equity(bar_time, capital, underlying)

        # Force close at end
        if self.active_trade:
            last_price = float(df["close"].iloc[-1])
            last_prem = self._estimate_premium(
                last_price, self.active_trade.strike, self.active_trade.option_type,
            )
            costs = self._compute_costs(self.active_trade.entry_price, last_prem)
            self._close_active(last_prem, df.index[-1], ExitReason.FORCE_EXIT, costs)

        logger.info("Backtest complete: %d trades", len(self.trades))
        return self.trades

    def _is_opposite(self, signal: Signal) -> bool:
        if not self.active_trade:
            return False
        return (
            (self.active_trade.option_type == OptionType.CALL and signal.type == SignalType.SHORT)
            or (self.active_trade.option_type == OptionType.PUT and signal.type == SignalType.LONG)
        )

    def _open_trade(self, signal: Signal, underlying: float, bar_time) -> None:
        self._trade_counter += 1
        opt_type = OptionType.CALL if signal.type == SignalType.LONG else OptionType.PUT

        contract = self.option_selector.select_contract(signal.type, underlying)
        entry_premium = self._estimate_premium(underlying, contract.strike, opt_type)

        slippage = entry_premium * (self.slippage_pct / 100)
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
            grade=signal.grade,
            confidence=signal.confidence,
        )
        trade.trailing_sl = sl
        trade.peak_price = entry_premium
        self.active_trade = trade
        self._daily_trade_count += 1
        self._partial_booked = False

    def _close_active(self, exit_premium: float, bar_time,
                      reason: ExitReason, costs: float = 0.0) -> None:
        if not self.active_trade:
            return

        slippage = exit_premium * (self.slippage_pct / 100)
        exit_premium = max(0.05, exit_premium - slippage)

        self.active_trade.close(exit_premium, bar_time, reason, costs)
        self._daily_pnl += self.active_trade.net_pnl
        self.trades.append(self.active_trade)

        if self.active_trade.pnl <= 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        self.active_trade = None

    def _check_exit(self, current_premium: float, bar_time) -> ExitReason | None:
        trade = self.active_trade
        if not trade:
            return None

        eff_sl = max(trade.stop_loss, trade.trailing_sl)

        if current_premium <= eff_sl:
            return (ExitReason.TRAILING_SL if trade.trailing_sl > trade.stop_loss
                    else ExitReason.STOP_LOSS)
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

    def _get_exit_premium(self, reason: ExitReason, current_premium: float) -> float:
        trade = self.active_trade
        if reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_SL):
            return max(trade.stop_loss, trade.trailing_sl)
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

    def _estimate_premium(self, underlying: float, strike: float,
                          opt_type: OptionType) -> float:
        return estimate_option_premium(underlying, strike, opt_type)

    def _compute_costs(self, entry_prem: float, exit_prem: float) -> float:
        return compute_round_trip_costs(entry_prem, exit_prem, self.lot_size,
                                        self.config.brokerage)

    def _can_trade(self) -> bool:
        if self._daily_trade_count >= self.max_trades_per_day:
            return False
        if self._daily_pnl <= -self.max_loss_per_day:
            return False
        if self._consecutive_losses >= self.config.risk.max_consecutive_losses:
            return False
        return True

    def _reset_daily(self, date_str: str) -> None:
        self._current_date = date_str
        self._daily_trade_count = 0
        self._daily_pnl = 0.0
        self._consecutive_losses = 0

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
