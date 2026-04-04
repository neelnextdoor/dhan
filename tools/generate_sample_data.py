#!/usr/bin/env python3
"""
Generate synthetic OHLCV data for backtesting without API access.
Usage: python tools/generate_sample_data.py [--output data/sample.csv] [--days 60]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def generate_market_data(
    days: int = 60,
    base_price: float = 22000.0,
    volatility: float = 0.8,
    trend_strength: float = 0.02,
    timeframe_minutes: int = 5,
) -> pd.DataFrame:
    candles_per_day = int(6 * 60 / timeframe_minutes)  # ~6 hours of trading
    total_candles = days * candles_per_day

    np.random.seed(None)

    dates = []
    for d in range(days):
        day_start = pd.Timestamp("2025-01-02") + pd.Timedelta(days=d)
        if day_start.weekday() >= 5:
            continue
        for c in range(candles_per_day):
            ts = day_start + pd.Timedelta(hours=9, minutes=15 + c * timeframe_minutes)
            dates.append(ts)

    n = len(dates)
    if n == 0:
        return pd.DataFrame()

    returns = np.random.normal(trend_strength / candles_per_day, volatility / 100, n)

    # Add mean-reversion + momentum regimes
    regime = np.zeros(n)
    regime_state = 0
    for i in range(n):
        if np.random.random() < 0.02:
            regime_state = np.random.choice([-1, 0, 1])
        regime[i] = regime_state * 0.0003

    returns += regime

    prices = base_price * np.exp(np.cumsum(returns))

    high_offset = np.abs(np.random.normal(0, volatility * 0.3, n))
    low_offset = np.abs(np.random.normal(0, volatility * 0.3, n))
    open_offset = np.random.normal(0, volatility * 0.1, n)

    closes = prices
    highs = closes + high_offset
    lows = closes - low_offset
    opens = closes + open_offset

    lows = np.minimum(lows, np.minimum(opens, closes))
    highs = np.maximum(highs, np.maximum(opens, closes))

    base_vol = np.random.lognormal(10, 0.5, n)
    volume_spikes = np.where(np.abs(returns) > np.std(returns) * 1.5, 2.5, 1.0)
    volumes = (base_vol * volume_spikes).astype(int)

    df = pd.DataFrame({
        "timestamp": dates[:n],
        "open": np.round(opens, 2),
        "high": np.round(highs, 2),
        "low": np.round(lows, 2),
        "close": np.round(closes, 2),
        "volume": volumes,
    })
    df.set_index("timestamp", inplace=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="Generate sample OHLCV data")
    parser.add_argument("--output", default="data/sample_nifty.csv", help="Output CSV path")
    parser.add_argument("--days", type=int, default=60, help="Number of trading days")
    parser.add_argument("--base-price", type=float, default=22000.0, help="Starting price")
    parser.add_argument("--timeframe", type=int, default=5, help="Candle timeframe in minutes")
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    df = generate_market_data(
        days=args.days,
        base_price=args.base_price,
        timeframe_minutes=args.timeframe,
    )

    df.to_csv(out)
    print(f"Generated {len(df)} candles -> {out}")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    print(f"Price range: {df['low'].min():.2f} - {df['high'].max():.2f}")


if __name__ == "__main__":
    main()
