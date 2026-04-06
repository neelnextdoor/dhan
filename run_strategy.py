#!/usr/bin/env python3
"""
Dhan Algo — MA-EMA Crossover Options Strategy Runner

Usage:
  # Backtest on CSV data
  python run_strategy.py --mode backtest --csv data/nifty_intraday_5m.csv

  # Backtest from Dhan API
  python run_strategy.py --mode backtest --start 2025-01-01 --end 2025-06-30

  # Paper trading
  python run_strategy.py --mode paper

  # Live trading
  python run_strategy.py --mode live

  # With custom config
  python run_strategy.py --config config/default.yaml --mode backtest --csv data/nifty_5m.csv --plots --trades --export
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from src.backtest.options_backtester import OptionsBacktester
from src.backtest.report import BacktestReport
from src.core.config import AppConfig
from src.core.logger import setup_logging, get_logger
from src.strategy.option_ema_strategy import OptionEMAStrategy


def load_backtest_data(config: AppConfig) -> pd.DataFrame:
    logger = get_logger("data_loader")

    if config.backtest.data_source == "csv" and config.backtest.csv_path:
        logger.info("Loading CSV: %s", config.backtest.csv_path)
        df = pd.read_csv(config.backtest.csv_path, parse_dates=["timestamp"])
        if "timestamp" in df.columns:
            df.set_index("timestamp", inplace=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    logger.info("Loading from Dhan API: %s (%s -> %s)",
                config.symbol, config.backtest.start_date, config.backtest.end_date)
    from src.data.dhan_client import DhanClient
    client = DhanClient(config)
    df = client.get_historical_data(
        from_date=config.backtest.start_date,
        to_date=config.backtest.end_date,
    )
    if df.empty:
        logger.warning("Historical empty — trying intraday")
        df = client.get_intraday_data()
    return df


def run_backtest(config: AppConfig, args) -> None:
    logger = get_logger("backtest")

    logger.info("=" * 60)
    logger.info("  OPTIONS BACKTEST — MA(%d) / EMA(%d) Crossover",
                config.strategy.ma_period, config.strategy.ema_period)
    logger.info("  Symbol: %s | TF: %s | Confirmation: %s",
                config.symbol, config.strategy.entry_timeframe,
                config.strategy.confirmation_timeframe)
    logger.info("  OI: %s | Volume: %s | Grade: >= %s",
                "ON" if config.strategy.use_oi_confirmation else "OFF",
                "ON" if config.strategy.use_volume_filter else "OFF",
                config.strategy.min_grade)
    logger.info("  SL: %s%% | TP: %s%% | Trailing: %s",
                config.options.premium_sl_pct, config.options.premium_target_pct,
                "ON" if config.exit.trailing_sl.enabled else "OFF")
    logger.info("  Capital: %.0f | Lot: %d | Max trades/day: %d",
                config.backtest.initial_capital, config.risk.lot_size,
                config.risk.max_trades_per_day)
    logger.info("=" * 60)

    df = load_backtest_data(config)
    if df.empty:
        logger.error("No data available")
        sys.exit(1)

    logger.info("Data: %d candles (%s to %s)", len(df), df.index[0], df.index[-1])

    strategy = OptionEMAStrategy(config)
    engine = OptionsBacktester(config, strategy)
    trades = engine.run(df)

    report = BacktestReport(
        trades=trades,
        equity_curve=engine.equity_curve,
        initial_capital=config.backtest.initial_capital,
        commission=config.backtest.commission_per_trade,
    )

    report.print_summary()

    if args.trades:
        report.print_trade_log()

    if args.export:
        report.export_trades_csv()
        report.export_equity_csv()
        logger.info("Results exported to backtest_results/")

    if args.plots and config.visualization.enabled:
        try:
            from src.visualization.plotter import StrategyPlotter
            plotter = StrategyPlotter(config)
            paths = plotter.plot_all(
                spot_df=df,
                trades=trades,
                equity_curve=engine.equity_curve,
                ma_period=config.strategy.ma_period,
                ema_period=config.strategy.ema_period,
            )
            for p in paths:
                logger.info("Chart saved: %s", p)
        except ImportError:
            logger.warning("matplotlib not installed — skipping plots")


def run_live(config: AppConfig) -> None:
    logger = get_logger("live")

    from src.data.dhan_client import DhanClient
    from src.data.data_handler import DataHandler
    from src.execution.order_manager import OrderManager
    from src.execution.position_manager import PositionManager
    from src.notifications.telegram import TelegramNotifier
    from src.options.oi_analyzer import OIAnalyzer
    from src.options.option_selector import OptionSelector
    from src.risk.risk_manager import RiskManager

    import signal as sys_signal
    import time

    from src.core.constants import (
        ExitReason, OptionType, SignalType, TradeGrade, TradingMode, TIMEFRAME_MAP,
    )

    mode = TradingMode(config.trading_mode)
    client = DhanClient(config) if mode != TradingMode.BACKTEST else None
    data_handler = DataHandler(config, client)
    strategy = OptionEMAStrategy(config)
    position_manager = PositionManager()
    order_manager = OrderManager(config, client)
    risk_manager = RiskManager(config, position_manager)
    telegram = TelegramNotifier(config)
    oi_analyzer = OIAnalyzer(config) if config.strategy.use_oi_confirmation else None
    option_selector = OptionSelector(config, oi_analyzer)

    running = True
    last_signal_bar = None
    active_contract = None
    tick_count = 0
    last_candle_count = 0

    def shutdown_handler(signum, frame):
        nonlocal running
        logger.info("Shutdown signal received")
        running = False

    sys_signal.signal(sys_signal.SIGINT, shutdown_handler)
    sys_signal.signal(sys_signal.SIGTERM, shutdown_handler)

    logger.info("=" * 60)
    logger.info("  MA-EMA OPTIONS — %s MODE", mode.value.upper())
    logger.info("  Strategy: %s | Symbol: %s", strategy.name(), config.symbol)
    logger.info("  MA=%d EMA=%d | Confirm: %s",
                config.strategy.ma_period, config.strategy.ema_period,
                config.strategy.confirmation_timeframe)
    logger.info("=" * 60)

    candles = data_handler.initialize()
    if candles.empty:
        logger.error("Failed to load candle data — aborting")
        return

    logger.info("Loaded %d candles", len(candles))
    last_candle_count = len(candles)
    telegram.notify_startup(mode.value, config.symbol, strategy.name(),
                            config.risk.capital_per_trade, config.risk.lot_size)

    tf_minutes = TIMEFRAME_MAP.get(config.timeframe, 5)
    poll_interval = min(tf_minutes * 60 // 3, 30)

    from src.options.option_selector import estimate_option_premium

    while running:
        try:
            tick_count += 1
            now = __import__("datetime").datetime.now()

            if not risk_manager.is_within_trading_hours(now):
                if tick_count % 10 == 1:
                    logger.info("Outside trading hours. Waiting...")
                time.sleep(poll_interval)
                continue

            if risk_manager.should_force_exit(now):
                if position_manager.has_open_position:
                    trade = position_manager.active_trade
                    if trade and trade.is_option:
                        prem = estimate_option_premium(
                            float(candles["close"].iloc[-1]), trade.strike, trade.option_type,
                        )
                        order_manager.place_exit_order(prem, trade.quantity,
                                                       option_security_id=trade.option_security_id)
                        position_manager.close_trade(prem, ExitReason.FORCE_EXIT)
                time.sleep(poll_interval)
                continue

            candles = data_handler.update()
            if candles.empty:
                time.sleep(poll_interval)
                continue

            new_candles = len(candles) - last_candle_count
            last_candle_count = len(candles)
            underlying_price = float(candles["close"].iloc[-1])
            current_bar = candles.index[-1]

            # Manage open position
            if position_manager.has_open_position:
                trade = position_manager.active_trade
                if trade and trade.is_option:
                    prem = estimate_option_premium(underlying_price, trade.strike, trade.option_type)

                    if config.exit.trailing_sl.enabled:
                        position_manager.update_trailing_sl(
                            prem, config.exit.trailing_sl.trail_pct,
                            config.exit.trailing_sl.activation_pct,
                        )

                    exit_reason = position_manager.check_sl_tp(prem)
                    if exit_reason:
                        order_manager.place_exit_order(prem, trade.quantity,
                                                       option_security_id=trade.option_security_id)
                        closed = position_manager.close_trade(prem, exit_reason)
                        if closed:
                            telegram.notify_exit(closed)
                        active_contract = None

                    if risk_manager.should_time_exit(now) and position_manager.has_open_position:
                        order_manager.place_exit_order(prem, trade.quantity,
                                                       option_security_id=trade.option_security_id)
                        closed = position_manager.close_trade(prem, ExitReason.TIME_EXIT)
                        if closed:
                            telegram.notify_exit(closed)
                        active_contract = None

                time.sleep(poll_interval)
                continue

            if current_bar == last_signal_bar:
                time.sleep(poll_interval)
                continue

            can_trade, reason = risk_manager.can_open_trade()
            if not can_trade:
                time.sleep(poll_interval)
                continue

            htf_candles = data_handler.confirmation_candles
            signal = strategy.generate_signal(candles, htf_candles if not htf_candles.empty else None)

            if not signal.is_entry:
                time.sleep(poll_interval)
                continue

            avoid, avoid_reason = option_selector.should_avoid_entry(now)
            if avoid:
                logger.info("Entry blocked: %s", avoid_reason)
                time.sleep(poll_interval)
                continue

            # OI confirmation
            if oi_analyzer and config.strategy.use_oi_confirmation:
                chain = None
                if client and mode == TradingMode.LIVE:
                    chain = client.get_option_chain(
                        underlying_security_id=config.security_id,
                        expiry=config.expiry,
                    )
                    if chain:
                        oi_analyzer.ingest_option_chain(chain, underlying_price)

            last_signal_bar = current_bar
            logger.info("Signal: %s grade=%s conf=%.0f%%",
                        signal.type.value, signal.grade.value, signal.confidence * 100)

            chain = None
            if client and mode == TradingMode.LIVE:
                chain = client.get_option_chain(
                    underlying_security_id=config.security_id, expiry=config.expiry,
                )

            contract = option_selector.select_contract(signal.type, underlying_price, chain)
            premium = contract.ltp if contract.ltp > 0 else estimate_option_premium(
                underlying_price, contract.strike, contract.option_type,
            )

            sl = premium * (1 - config.options.premium_sl_pct / 100)
            tp = premium * (1 + config.options.premium_target_pct / 100)
            qty = config.risk.lot_size

            resp = order_manager.place_entry_order(signal.type, premium, qty, contract)
            if resp.get("status") != "success":
                logger.warning("Order failed: %s", resp)
                time.sleep(poll_interval)
                continue

            fill_premium = resp.get("price", premium)
            order_id = resp.get("orderId", "")

            sl = fill_premium * (1 - config.options.premium_sl_pct / 100)
            tp = fill_premium * (1 + config.options.premium_target_pct / 100)

            trade = position_manager.open_trade(
                symbol=config.symbol, signal_type=signal.type,
                entry_price=fill_premium, quantity=qty, stop_loss=sl, target=tp,
                order_id=order_id, option_type=contract.option_type,
                strike=contract.strike, expiry=contract.expiry,
                option_security_id=contract.security_id,
                underlying_price=underlying_price,
            )
            active_contract = contract

            opt_label = "CE" if contract.option_type == OptionType.CALL else "PE"
            logger.info("ENTRY: BUY %s %.0f%s @ %.2f | SL=%.2f TP=%.2f",
                        config.symbol, contract.strike, opt_label, fill_premium, sl, tp)
            telegram.notify_entry(trade)

        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Error in main loop")
            telegram.notify_error("Main loop exception")
            time.sleep(5)
            continue

        time.sleep(poll_interval)

    # Shutdown
    logger.info("Shutting down...")
    if position_manager.has_open_position:
        trade = position_manager.active_trade
        if trade and trade.is_option:
            prem = estimate_option_premium(
                float(candles["close"].iloc[-1]) if not candles.empty else 0,
                trade.strike, trade.option_type,
            )
            order_manager.place_exit_order(prem, trade.quantity,
                                           option_security_id=trade.option_security_id)
            position_manager.close_trade(prem, ExitReason.FORCE_EXIT)

    all_trades = position_manager.get_all_trades()
    total_pnl = sum(t.pnl for t in all_trades)
    telegram.notify_shutdown(len(all_trades), total_pnl)
    logger.info("Session done. Trades=%d PnL=%+.2f", len(all_trades), total_pnl)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MA-EMA Crossover Options Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default=None, help="Path to YAML config")
    parser.add_argument("--mode", choices=["backtest", "paper", "live"], default="backtest")
    parser.add_argument("--csv", default=None, help="CSV data file for backtest")
    parser.add_argument("--start", default=None, help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--trades", action="store_true", help="Print trade log")
    parser.add_argument("--export", action="store_true", help="Export CSV results")
    parser.add_argument("--plots", action="store_true", help="Generate charts")
    parser.add_argument("--ma", type=int, default=None, help="Override MA period")
    parser.add_argument("--ema", type=int, default=None, help="Override EMA period")
    parser.add_argument("--symbol", default=None, help="Override symbol")
    args = parser.parse_args()

    config = AppConfig.load(args.config)

    if args.csv:
        config.backtest.data_source = "csv"
        config.backtest.csv_path = args.csv
    if args.start:
        config.backtest.start_date = args.start
    if args.end:
        config.backtest.end_date = args.end
    if args.ma:
        config.strategy.ma_period = args.ma
    if args.ema:
        config.strategy.ema_period = args.ema
    if args.symbol:
        config.symbol = args.symbol

    if args.mode in ("paper", "live"):
        config.trading_mode = args.mode
        os.environ["TRADING_MODE"] = args.mode
    else:
        config.trading_mode = "backtest"

    setup_logging(config)

    if args.mode == "backtest":
        run_backtest(config, args)
    elif args.mode in ("paper", "live"):
        if args.mode == "live":
            logger = get_logger("main")
            if not config.dhan_client_id or not config.dhan_access_token:
                logger.error("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
                return
            logger.warning("=" * 50)
            logger.warning("  LIVE MODE — REAL MONEY AT RISK")
            logger.warning("=" * 50)
        run_live(config)


if __name__ == "__main__":
    main()
