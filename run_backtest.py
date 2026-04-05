#!/usr/bin/env python3
"""
Dhan Algo Trading — Backtest Runner
Usage: python run_backtest.py [--config path/to/config.yaml]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.backtest.report import BacktestReport
from src.core.config import AppConfig
from src.core.logger import setup_logging, get_logger
from src.data.dhan_client import DhanClient
from src.strategy.ema_strategy import EMAStrategy


def load_data(config: AppConfig) -> pd.DataFrame:
    logger = get_logger("backtest_loader")

    if config.backtest.data_source == "csv" and config.backtest.csv_path:
        logger.info("Loading data from CSV: %s", config.backtest.csv_path)
        df = pd.read_csv(config.backtest.csv_path, parse_dates=["timestamp"])
        if "timestamp" in df.columns:
            df.set_index("timestamp", inplace=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    logger.info("Loading data from Dhan API: %s (%s -> %s)",
                config.symbol, config.backtest.start_date, config.backtest.end_date)
    client = DhanClient(config)
    df = client.get_historical_data(
        from_date=config.backtest.start_date,
        to_date=config.backtest.end_date,
    )
    if df.empty:
        logger.warning("Historical API returned empty — trying intraday")
        df = client.get_intraday_data()
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EMA strategy backtest")
    parser.add_argument("--config", default=None, help="Path to YAML config file")
    parser.add_argument("--csv", default=None, help="Override: path to CSV data file")
    parser.add_argument("--start", default=None, help="Override: start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override: end date YYYY-MM-DD")
    parser.add_argument("--trades", action="store_true", help="Print trade log")
    parser.add_argument("--export", action="store_true", help="Export results to CSV")
    args = parser.parse_args()

    config = AppConfig.load(args.config)

    if args.csv:
        config.backtest.data_source = "csv"
        config.backtest.csv_path = args.csv
    if args.start:
        config.backtest.start_date = args.start
    if args.end:
        config.backtest.end_date = args.end

    config.trading_mode = "backtest"
    setup_logging(config)
    logger = get_logger("backtest_main")

    logger.info("=" * 50)
    logger.info("BACKTEST MODE")
    logger.info("Symbol: %s | Timeframe: %s", config.symbol, config.timeframe)
    logger.info("Period: %s to %s", config.backtest.start_date, config.backtest.end_date)
    logger.info("Capital: %.0f | Lot size: %d", config.backtest.initial_capital, config.risk.lot_size)
    logger.info("=" * 50)

    df = load_data(config)
    if df.empty:
        logger.error("No data available for backtesting")
        sys.exit(1)

    logger.info("Data loaded: %d candles (%s to %s)", len(df), df.index[0], df.index[-1])

    strategy = EMAStrategy(config)
    engine = BacktestEngine(config, strategy)
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


if __name__ == "__main__":
    main()
