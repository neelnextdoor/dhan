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
        return True
    atr = compute_atr(df, period)
    current_atr = float(atr.iloc[-1])
    current_price = float(df["close"].iloc[-1])
    if current_price == 0:
        return False
    atr_pct = (current_atr / current_price) * 100
    return atr_pct >= threshold_pct


def atr_expansion(df: pd.DataFrame, period: int = 14, lookback: int = 5,
                  expansion_factor: float = 1.2) -> bool:
    """True if current ATR is expanding vs its recent average (volatility pickup)."""
    if len(df) < period + lookback:
        return True
    atr = compute_atr(df, period)
    current = float(atr.iloc[-1])
    recent_avg = float(atr.iloc[-lookback - 1:-1].mean())
    if recent_avg == 0:
        return True
    return current >= recent_avg * expansion_factor


def atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 50) -> float:
    """Returns the percentile rank (0-100) of current ATR vs recent history."""
    if len(df) < period + lookback:
        return 50.0
    atr = compute_atr(df, period)
    current = float(atr.iloc[-1])
    history = atr.iloc[-lookback:].values
    rank = np.sum(history <= current) / len(history) * 100
    return float(rank)


def candle_range_filter(df: pd.DataFrame, min_range_pct: float = 0.3) -> bool:
    if df.empty:
        return False
    last = df.iloc[-1]
    candle_range = float(last["high"] - last["low"])
    mid_price = float((last["high"] + last["low"]) / 2)
    if mid_price == 0:
        return False
    range_pct = (candle_range / mid_price) * 100
    return range_pct >= min_range_pct


def is_range_bound(df: pd.DataFrame, lookback: int = 20, range_pct: float = 1.5) -> bool:
    """
    Detect consolidation: true if the price range over `lookback` bars
    is less than `range_pct` % of the midpoint.
    """
    if len(df) < lookback:
        return False
    recent = df.iloc[-lookback:]
    high = float(recent["high"].max())
    low = float(recent["low"].min())
    mid = (high + low) / 2
    if mid == 0:
        return False
    total_range = ((high - low) / mid) * 100
    return total_range < range_pct


def find_swing_high(df: pd.DataFrame, lookback: int = 10) -> float:
    if len(df) < lookback:
        lookback = len(df)
    return float(df["high"].iloc[-lookback:].max())


def find_swing_low(df: pd.DataFrame, lookback: int = 10) -> float:
    if len(df) < lookback:
        lookback = len(df)
    return float(df["low"].iloc[-lookback:].min())
