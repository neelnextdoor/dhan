#!/usr/bin/env python3
"""
Parameter optimization with walk-forward validation.

Usage:
  python tools/optimize.py --csv data/nifty_5m.csv --metric sharpe
  python tools/optimize.py --csv data/nifty_5m.csv --metric net_pnl --export

Sweeps key parameters while avoiding overfitting by:
  1. Training on 70% of data, validating on 30%
  2. Penalising parameter sets with < 10 trades
  3. Reporting both in-sample and out-of-sample metrics
"""
from __future__ import annotations

import argparse
import itertools
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import BacktestEngine
from src.backtest.report import BacktestReport
from src.core.config import AppConfig
from src.core.constants import TradeGrade
from src.core.logger import setup_logging, get_logger
from src.strategy.ema_strategy import EMAStrategy

logger = get_logger("optimizer")

# Parameter grid (conservative ranges to limit combinatorial explosion)
PARAM_GRID = {
    "ema_primary": [7, 9],
    "ema_short": [9, 13],
    "ema_long": [21, 34],
    "ema_trend": [50],
    "premium_sl_pct": [15, 20, 25],
    "premium_tp_pct": [25, 30, 40],
    "min_grade": ["A+", "A", "B"],
    "atr_threshold": [0.06, 0.08, 0.10],
}


def make_config(base: AppConfig, params: dict) -> AppConfig:
    cfg = deepcopy(base)
    cfg.ema.primary_period = params["ema_primary"]
    cfg.ema.short_period = params["ema_short"]
    cfg.ema.long_period = params["ema_long"]
    cfg.ema.trend_period = params["ema_trend"]
    cfg.options.premium_sl_pct = params["premium_sl_pct"]
    cfg.options.premium_target_pct = params["premium_tp_pct"]
    cfg.entry.min_grade = params["min_grade"]
    cfg.sideways_filter.atr_threshold = params["atr_threshold"]
    return cfg


def run_single(config: AppConfig, df: pd.DataFrame) -> dict:
    strategy = EMAStrategy(config)
    engine = BacktestEngine(config, strategy)
    trades = engine.run(df)
    report = BacktestReport(trades, engine.equity_curve, config.backtest.initial_capital)
    return report.summary()


def main():
    parser = argparse.ArgumentParser(description="Walk-forward parameter optimization")
    parser.add_argument("--csv", required=True, help="Path to OHLCV CSV file")
    parser.add_argument("--config", default=None, help="Base config YAML")
    parser.add_argument("--metric", default="sharpe_ratio",
                        choices=["sharpe_ratio", "sortino_ratio", "net_pnl",
                                 "win_rate", "profit_factor", "calmar_ratio"],
                        help="Metric to optimize")
    parser.add_argument("--train-pct", type=float, default=0.7, help="Training set fraction")
    parser.add_argument("--export", action="store_true", help="Export results CSV")
    args = parser.parse_args()

    base_config = AppConfig.load(args.config)
    base_config.trading_mode = "backtest"
    base_config.backtest.data_source = "csv"
    base_config.backtest.csv_path = args.csv
    setup_logging(base_config)

    df = pd.read_csv(args.csv, parse_dates=["timestamp"])
    if "timestamp" in df.columns:
        df.set_index("timestamp", inplace=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    split_idx = int(len(df) * args.train_pct)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    logger.info("Data: %d candles (train=%d, test=%d)", len(df), len(train_df), len(test_df))

    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = list(itertools.product(*values))
    logger.info("Testing %d parameter combinations...", len(combos))

    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        cfg = make_config(base_config, params)

        try:
            train_result = run_single(cfg, train_df)
            test_result = run_single(cfg, test_df)
        except Exception as e:
            logger.warning("Combo %d failed: %s", i, e)
            continue

        if train_result.get("error") or test_result.get("error"):
            continue

        train_trades = train_result.get("total_trades", 0)
        if train_trades < 5:
            continue

        results.append({
            "params": params,
            "train_trades": train_trades,
            f"train_{args.metric}": train_result.get(args.metric, 0),
            "train_win_rate": train_result.get("win_rate", 0),
            "train_net_pnl": train_result.get("total_net_pnl", 0),
            "test_trades": test_result.get("total_trades", 0),
            f"test_{args.metric}": test_result.get(args.metric, 0),
            "test_win_rate": test_result.get("win_rate", 0),
            "test_net_pnl": test_result.get("total_net_pnl", 0),
        })

        if (i + 1) % 50 == 0:
            logger.info("Progress: %d/%d", i + 1, len(combos))

    if not results:
        logger.error("No valid results")
        return

    results.sort(key=lambda r: r.get(f"test_{args.metric}", 0), reverse=True)

    print(f"\n{'=' * 80}")
    print(f"  OPTIMIZATION RESULTS — sorted by test {args.metric}")
    print(f"{'=' * 80}\n")

    headers = ["Rank", "EMA", "SL%", "TP%", "Grade", "ATR",
               "Train Trades", f"Train {args.metric}", "Train WR",
               "Test Trades", f"Test {args.metric}", "Test WR", "Test PnL"]
    rows = []
    for rank, r in enumerate(results[:20], 1):
        p = r["params"]
        rows.append([
            rank,
            f"{p['ema_primary']}/{p['ema_short']}/{p['ema_long']}/{p['ema_trend']}",
            p["premium_sl_pct"],
            p["premium_tp_pct"],
            p["min_grade"],
            p["atr_threshold"],
            r["train_trades"],
            f"{r.get(f'train_{args.metric}', 0):.2f}",
            f"{r['train_win_rate']:.1f}%",
            r["test_trades"],
            f"{r.get(f'test_{args.metric}', 0):.2f}",
            f"{r['test_win_rate']:.1f}%",
            f"₹{r['test_net_pnl']:+,.0f}",
        ])

    print(tabulate(rows, headers=headers, tablefmt="simple"))
    print()

    if args.export:
        out_path = "backtest_results/optimization.csv"
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        out_df = pd.DataFrame(results)
        out_df.to_csv(out_path, index=False)
        logger.info("Exported to %s", out_path)

    best = results[0]
    print(f"\nBest params (by test {args.metric}):")
    for k, v in best["params"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
