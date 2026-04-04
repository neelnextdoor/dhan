from __future__ import annotations

import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def is_market_trending(df: pd.DataFrame, period: int = 14, threshold_pct: float = 0.5) -> bool:
    """Returns True if ATR as a percentage of price exceeds threshold."""
    if len(df) < period + 1:
        return True  # default to allowing trades when insufficient data
    atr = compute_atr(df, period)
    current_atr = float(atr.iloc[-1])
    current_price = float(df["close"].iloc[-1])
    if current_price == 0:
        return False
    atr_pct = (current_atr / current_price) * 100
    return atr_pct >= threshold_pct


def candle_range_filter(df: pd.DataFrame, min_range_pct: float = 0.3) -> bool:
    """Returns True if the last candle's range exceeds minimum percentage."""
    if df.empty:
        return False
    last = df.iloc[-1]
    candle_range = float(last["high"] - last["low"])
    mid_price = float((last["high"] + last["low"]) / 2)
    if mid_price == 0:
        return False
    range_pct = (candle_range / mid_price) * 100
    return range_pct >= min_range_pct


def find_swing_high(df: pd.DataFrame, lookback: int = 10) -> float:
    if len(df) < lookback:
        lookback = len(df)
    return float(df["high"].iloc[-lookback:].max())


def find_swing_low(df: pd.DataFrame, lookback: int = 10) -> float:
    if len(df) < lookback:
        lookback = len(df)
    return float(df["low"].iloc[-lookback:].min())
