from __future__ import annotations

import signal as sys_signal
import time
from datetime import datetime, timedelta

from src.core.config import AppConfig
from src.core.constants import ExitReason, OptionType, SignalType, TradeGrade, TradingMode, TIMEFRAME_MAP
from src.core.logger import get_logger
from src.data.dhan_client import DhanClient
from src.data.market_data import MarketDataManager
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager
from src.notifications.telegram import TelegramNotifier
from src.options.contract_selector import ContractSelector, OptionContract, estimate_option_premium
from src.risk.risk_manager import RiskManager
from src.strategy.base import BaseStrategy
from src.webhooks.handler import OrderStatus, OrderUpdate, WebhookHandler
from src.webhooks.server import WebhookServer

logger = get_logger("live_engine")


class LiveEngine:
    """
    Main event loop for option buying (live / paper).

    Signal flow:
    1. EMA strategy analyzes UNDERLYING (NIFTY/BANKNIFTY) candles
    2. LONG signal -> BUY CALL, SHORT signal -> BUY PUT
    3. SL/TP tracked on OPTION PREMIUM
    4. Exit -> SELL the option
    """

    def __init__(self, config: AppConfig, strategy: BaseStrategy):
        self.config = config
        self.strategy = strategy
        self.mode = TradingMode(config.trading_mode)

        self.client = DhanClient(config) if self.mode != TradingMode.BACKTEST else None
        self.market_data = MarketDataManager(config, self.client) if self.client else None
        self.position_manager = PositionManager()
        self.order_manager = OrderManager(config, self.client)
        self.risk_manager = RiskManager(config, self.position_manager)
        self.telegram = TelegramNotifier(config)
        self.contract_selector = ContractSelector(config)

        self.webhook_handler = WebhookHandler()
        self.webhook_server: WebhookServer | None = None

        self._running = False
        self._last_signal_bar = None
        self._pending_order_ids: set[str] = set()
        self._active_contract: OptionContract | None = None
        self._tick_count = 0
        self._last_candle_count = 0

    def start(self) -> None:
        logger.info("=" * 60)
        logger.info("  OPTION BUYING — %s MODE", self.mode.value.upper())
        logger.info("  Strategy: %s | Symbol: %s | Timeframe: %s",
                     self.strategy.name(), self.config.symbol, self.config.timeframe)
        logger.info("  Strike: %s | Expiry: %s | Lot: %d",
                     self.config.options.strike_selection,
                     self.config.options.expiry_preference,
                     self.config.risk.lot_size)
        logger.info("  Capital: %d | Max loss/day: %d | Max trades/day: %d",
                     self.config.risk.capital_per_trade,
                     self.config.risk.max_loss_per_day,
                     self.config.risk.max_trades_per_day)
        logger.info("  Trading hours: %s - %s | Force exit: %s",
                     self.config.trading_hours.start,
                     self.config.trading_hours.end,
                     self.config.trading_hours.force_exit)
        logger.info("=" * 60)

        sys_signal.signal(sys_signal.SIGINT, self._shutdown_handler)
        sys_signal.signal(sys_signal.SIGTERM, self._shutdown_handler)

        self._setup_webhook()

        if not self.market_data:
            logger.error("Market data manager not initialized")
            return

        logger.info("Loading initial candle data...")
        candles = self.market_data.initialize()
        if candles.empty:
            logger.error("Failed to load initial candle data — aborting")
            return

        logger.info("Loaded %d candles (%s to %s)",
                     len(candles), candles.index[0], candles.index[-1])
        self._last_candle_count = len(candles)

        self.telegram.notify_startup(
            mode=self.mode.value,
            symbol=self.config.symbol,
            strategy=self.strategy.name(),
            capital=self.config.risk.capital_per_trade,
            lot_size=self.config.risk.lot_size,
        )

        self._running = True
        self._run_loop()

    def _setup_webhook(self) -> None:
        if not self.config.webhook.enabled:
            logger.info("Webhook server disabled")
            return
        self._register_webhook_subscribers()
        self.webhook_server = WebhookServer(self.config, self.webhook_handler)
        self.webhook_server.start()
        logger.info("Postback URL: %s", self.webhook_server.url)

    def _register_webhook_subscribers(self) -> None:
        self.webhook_handler.subscribe(OrderStatus.TRADED, self._on_order_traded)
        self.webhook_handler.subscribe(OrderStatus.REJECTED, self._on_order_rejected)
        self.webhook_handler.subscribe(OrderStatus.CANCELLED, self._on_order_cancelled)
        self.webhook_handler.subscribe(OrderStatus.PENDING, self._on_order_pending)
        self.webhook_handler.subscribe(OrderStatus.TRANSIT, self._on_order_transit)
        self.webhook_handler.subscribe(OrderStatus.EXPIRED, self._on_order_expired)

    def _on_order_traded(self, update: OrderUpdate) -> None:
        logger.info(
            "ORDER TRADED: id=%s side=%s qty=%d price=%.2f",
            update.order_id, update.transaction_type,
            update.quantity, update.price,
        )
        self._pending_order_ids.discard(update.order_id)

        if self.position_manager.has_open_position:
            trade = self.position_manager.active_trade
            if trade and trade.order_id == update.order_id and update.price > 0:
                old = trade.entry_price
                trade.entry_price = update.price
                trade.peak_price = update.price
                if old != update.price:
                    logger.info("Premium reconciled: %.2f -> %.2f", old, update.price)

        self.telegram.notify_order_update(update)

    def _on_order_rejected(self, update: OrderUpdate) -> None:
        logger.error(
            "ORDER REJECTED: id=%s error=%s",
            update.order_id, update.oms_error_description or "N/A",
        )
        self._pending_order_ids.discard(update.order_id)
        if self.position_manager.has_open_position:
            trade = self.position_manager.active_trade
            if trade and trade.order_id == update.order_id:
                self.position_manager.close_trade(trade.entry_price, ExitReason.MANUAL)
        self.telegram.notify_order_update(update)

    def _on_order_cancelled(self, update: OrderUpdate) -> None:
        logger.warning("ORDER CANCELLED: id=%s", update.order_id)
        self._pending_order_ids.discard(update.order_id)
        self.telegram.notify_order_update(update)

    def _on_order_pending(self, update: OrderUpdate) -> None:
        self._pending_order_ids.add(update.order_id)

    def _on_order_transit(self, update: OrderUpdate) -> None:
        self._pending_order_ids.add(update.order_id)

    def _on_order_expired(self, update: OrderUpdate) -> None:
        logger.warning("ORDER EXPIRED: id=%s", update.order_id)
        self._pending_order_ids.discard(update.order_id)
        self.telegram.notify_order_update(update)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _run_loop(self) -> None:
        tf_minutes = TIMEFRAME_MAP.get(self.config.timeframe, 5)
        tf_seconds = tf_minutes * 60
        poll_interval = min(tf_seconds // 3, 30)

        logger.info("Entering main loop (poll every %ds, candle=%dm)", poll_interval, tf_minutes)
        logger.info("Press Ctrl+C to stop")
        logger.info("-" * 60)

        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("Error in main loop tick")
                self.telegram.notify_error("Main loop exception — check logs")
                time.sleep(5)
                continue

            time.sleep(poll_interval)

        self._on_shutdown()

    def _tick(self) -> None:
        self._tick_count += 1
        now = datetime.now()
        now_str = now.strftime("%H:%M:%S")

        # Outside trading hours — wait silently (log every 5 min)
        if not self.risk_manager.is_within_trading_hours(now):
            if self._tick_count % 10 == 1:
                logger.info("[%s] Outside trading hours (%s-%s). Waiting...",
                            now_str,
                            self.config.trading_hours.start,
                            self.config.trading_hours.end)
            return

        # Force exit time
        if self.risk_manager.should_force_exit(now):
            if self.position_manager.has_open_position:
                logger.info("[%s] Force exit time reached", now_str)
                self._exit_position(ExitReason.FORCE_EXIT)
            return

        # Fetch latest candles
        candles = self.market_data.update()
        if candles.empty:
            logger.debug("[%s] No candle data", now_str)
            return

        new_candles = len(candles) - self._last_candle_count
        self._last_candle_count = len(candles)

        underlying_price = float(candles["close"].iloc[-1])
        current_bar = candles.index[-1]

        # Log status every tick
        position_str = "FLAT"
        if self.position_manager.has_open_position:
            trade = self.position_manager.active_trade
            if trade:
                prem = self._get_current_premium(trade, underlying_price)
                unrealized = (prem - trade.entry_price) * trade.quantity
                ot = "CE" if trade.option_type == OptionType.CALL else "PE"
                position_str = f"{trade.strike:.0f}{ot} entry={trade.entry_price:.1f} now={prem:.1f} pnl={unrealized:+.0f}"

        if new_candles > 0 or self._tick_count % 5 == 0:
            logger.info("[%s] %s @ %.1f | %s | trades=%d",
                        now_str, self.config.symbol, underlying_price,
                        position_str,
                        self.position_manager.daily_trade_count)

        # Manage open position
        if self.position_manager.has_open_position:
            self._manage_open_position(underlying_price, now, candles)
            return

        # Check for new entry
        if current_bar == self._last_signal_bar:
            return

        can_trade, reason = self.risk_manager.can_open_trade()
        if not can_trade:
            if self._tick_count % 10 == 0:
                logger.info("[%s] Cannot trade: %s", now_str, reason)
            return

        signal = self.strategy.generate_signal(candles)
        if not signal.is_entry:
            return

        # Trade grade filter
        min_grade = TradeGrade(self.config.entry.min_grade)
        if not signal.passes_grade_filter(min_grade):
            logger.info("[%s] Signal rejected: grade %s < min %s",
                        now_str, signal.grade.value, min_grade.value)
            return

        # Theta decay protection for options
        avoid, avoid_reason = self.contract_selector.should_avoid_entry(now)
        if avoid:
            logger.info("[%s] Entry blocked: %s", now_str, avoid_reason)
            return

        if self.config.entry.confirm_candle_close and not self.market_data.is_candle_closed():
            logger.debug("[%s] Waiting for candle close confirmation", now_str)
            return

        self._last_signal_bar = current_bar
        logger.info("[%s] %s signal: grade=%s conf=%.0f%% | %s",
                    now_str, signal.type.value, signal.grade.value,
                    signal.confidence * 100, signal.score_breakdown)
        self._enter_option(signal, underlying_price)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    def _enter_option(self, signal, underlying_price: float) -> None:
        chain = None
        if self.client and self.mode == TradingMode.LIVE:
            chain = self.client.get_option_chain(
                underlying_security_id=self.config.security_id,
                expiry=self.config.expiry,
            )

        contract = self.contract_selector.select_contract(
            signal.type, underlying_price, chain,
        )

        if contract.ltp > 0:
            premium = contract.ltp
        else:
            premium = estimate_option_premium(
                underlying_price, contract.strike, contract.option_type,
            )

        if self.config.options.use_premium_based_sl:
            sl = premium * (1 - self.config.options.premium_sl_pct / 100)
            tp = premium * (1 + self.config.options.premium_target_pct / 100)
        else:
            sl = signal.stop_loss
            tp = signal.target

        qty = self.config.risk.lot_size

        resp = self.order_manager.place_entry_order(signal.type, premium, qty, contract)
        if resp.get("status") != "success":
            logger.warning("Order failed: %s", resp)
            return

        fill_premium = resp.get("price", premium)
        order_id = resp.get("orderId", "")

        if order_id:
            self._pending_order_ids.add(order_id)

        if self.config.options.use_premium_based_sl:
            sl = fill_premium * (1 - self.config.options.premium_sl_pct / 100)
            tp = fill_premium * (1 + self.config.options.premium_target_pct / 100)

        trade = self.position_manager.open_trade(
            symbol=self.config.symbol,
            signal_type=signal.type,
            entry_price=fill_premium,
            quantity=qty,
            stop_loss=sl,
            target=tp,
            order_id=order_id,
            option_type=contract.option_type,
            strike=contract.strike,
            expiry=contract.expiry,
            option_security_id=contract.security_id,
            underlying_price=underlying_price,
        )

        self._active_contract = contract

        opt_label = "CE" if contract.option_type == OptionType.CALL else "PE"
        logger.info(
            ">>> ENTRY: BUY %s %.0f%s @ %.2f | SL=%.2f TP=%.2f | Qty=%d | Reason=%s",
            self.config.symbol, contract.strike, opt_label,
            fill_premium, sl, tp, qty, signal.reason,
        )
        self.telegram.notify_entry(trade)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------
    def _manage_open_position(self, underlying_price: float, now: datetime,
                              candles=None) -> None:
        if self.risk_manager.should_time_exit(now):
            logger.info("Time-based exit triggered at %s", now.strftime("%H:%M"))
            self._exit_position(ExitReason.TIME_EXIT)
            return

        trade = self.position_manager.active_trade
        if not trade:
            return

        current_premium = self._get_current_premium(trade, underlying_price)

        if self.config.exit.trailing_sl.enabled:
            self.position_manager.update_trailing_sl(
                current_premium,
                self.config.exit.trailing_sl.trail_pct,
                self.config.exit.trailing_sl.activation_pct,
            )

        exit_reason = self.position_manager.check_sl_tp(current_premium)
        if exit_reason:
            self._exit_position(exit_reason, current_premium)
            return

        if self.config.exit.exit_on_opposite_signal and candles is not None and not candles.empty:
            signal = self.strategy.generate_signal(candles)
            if signal.is_entry:
                is_opposite = (
                    (trade.option_type == OptionType.CALL and signal.type == SignalType.SHORT)
                    or (trade.option_type == OptionType.PUT and signal.type == SignalType.LONG)
                )
                if is_opposite:
                    logger.info("Opposite signal detected — exiting position")
                    self._exit_position(ExitReason.OPPOSITE_SIGNAL, current_premium)

    def _get_current_premium(self, trade, underlying_price: float) -> float:
        if self._active_contract and self._active_contract.ltp > 0:
            return self._active_contract.ltp

        if trade.is_option:
            return estimate_option_premium(
                underlying_price, trade.strike, trade.option_type,
            )

        return trade.entry_price

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------
    def _exit_position(self, reason: ExitReason, premium: float | None = None) -> None:
        trade = self.position_manager.active_trade
        if not trade:
            return

        if premium is None:
            latest = self.market_data.get_latest_candle()
            if latest is not None and trade.is_option:
                underlying = float(latest["close"])
                premium = estimate_option_premium(underlying, trade.strike, trade.option_type)
            else:
                premium = trade.entry_price

        resp = self.order_manager.place_exit_order(
            premium, trade.quantity,
            contract=self._active_contract,
            option_security_id=trade.option_security_id,
        )
        exit_premium = resp.get("price", premium)

        closed = self.position_manager.close_trade(exit_premium, reason)
        self._active_contract = None

        if closed:
            opt_label = "CE" if closed.option_type == OptionType.CALL else "PE"
            logger.info(
                "<<< EXIT: SELL %s %.0f%s @ %.2f | PnL=%+.2f | Reason=%s",
                self.config.symbol, closed.strike, opt_label,
                exit_premium, closed.pnl, reason.value,
            )
            self.telegram.notify_exit(closed)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def _on_shutdown(self) -> None:
        logger.info("=" * 60)
        logger.info("Shutting down...")

        if self.position_manager.has_open_position:
            logger.warning("Force-closing open position on shutdown")
            self._exit_position(ExitReason.FORCE_EXIT)

        if self.webhook_server and self.webhook_server.is_running:
            self.webhook_server.stop()

        trades = self.position_manager.get_all_trades()
        total_pnl = sum(t.pnl for t in trades)
        if trades:
            self.telegram.notify_daily_summary(trades, total_pnl)
        self.telegram.notify_shutdown(len(trades), total_pnl)

        if self._pending_order_ids:
            logger.warning("Pending orders at shutdown: %s", self._pending_order_ids)

        logger.info("Session complete. Trades: %d, PnL: %+.2f", len(trades), total_pnl)
        logger.info("=" * 60)

    def _shutdown_handler(self, signum, frame) -> None:
        logger.info("Received shutdown signal (Ctrl+C)")
        self._running = False
