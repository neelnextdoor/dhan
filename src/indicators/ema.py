from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_emas(df: pd.DataFrame, primary: int, short: int, long: int,
                 trend: int = 50) -> pd.DataFrame:
    """Add EMA columns including the slow trend EMA."""
    df = df.copy()
    df[f"ema_{primary}"] = ema(df["close"], primary)
    df[f"ema_{short}"] = ema(df["close"], short)
    df[f"ema_{long}"] = ema(df["close"], long)
    df[f"ema_{trend}"] = ema(df["close"], trend)
    return df


def is_bullish_crossover(df: pd.DataFrame, short_col: str, long_col: str) -> bool:
    if len(df) < 2:
        return False
    prev_short, prev_long = df[short_col].iloc[-2], df[long_col].iloc[-2]
    curr_short, curr_long = df[short_col].iloc[-1], df[long_col].iloc[-1]
    return prev_short <= prev_long and curr_short > curr_long


def is_bearish_crossover(df: pd.DataFrame, short_col: str, long_col: str) -> bool:
    if len(df) < 2:
        return False
    prev_short, prev_long = df[short_col].iloc[-2], df[long_col].iloc[-2]
    curr_short, curr_long = df[short_col].iloc[-1], df[long_col].iloc[-1]
    return prev_short >= prev_long and curr_short < curr_long


def is_price_above_ema(df: pd.DataFrame, ema_col: str) -> bool:
    if df.empty:
        return False
    return float(df["close"].iloc[-1]) > float(df[ema_col].iloc[-1])


def is_price_below_ema(df: pd.DataFrame, ema_col: str) -> bool:
    if df.empty:
        return False
    return float(df["close"].iloc[-1]) < float(df[ema_col].iloc[-1])


def is_ema_trending_up(df: pd.DataFrame, short_col: str, long_col: str) -> bool:
    if df.empty:
        return False
    return float(df[short_col].iloc[-1]) > float(df[long_col].iloc[-1])


def is_ema_trending_down(df: pd.DataFrame, short_col: str, long_col: str) -> bool:
    if df.empty:
        return False
    return float(df[short_col].iloc[-1]) < float(df[long_col].iloc[-1])


# ------------------------------------------------------------------
# Advanced EMA analysis
# ------------------------------------------------------------------

def ema_alignment_score(df: pd.DataFrame, primary_col: str, short_col: str,
                        long_col: str, trend_col: str) -> float:
    """
    Score from -1.0 (fully bearish aligned) to +1.0 (fully bullish aligned).
    Perfect bullish: price > EMA7 > EMA9 > EMA21 > EMA50
    """
    if df.empty or len(df) < 2:
        return 0.0

    price = float(df["close"].iloc[-1])
    ema_p = float(df[primary_col].iloc[-1])
    ema_s = float(df[short_col].iloc[-1])
    ema_l = float(df[long_col].iloc[-1])
    ema_t = float(df[trend_col].iloc[-1])

    score = 0.0
    checks = [
        (price > ema_p, price < ema_p),
        (ema_p > ema_s, ema_p < ema_s),
        (ema_s > ema_l, ema_s < ema_l),
        (ema_l > ema_t, ema_l < ema_t),
    ]
    for bullish, bearish in checks:
        if bullish:
            score += 0.25
        elif bearish:
            score -= 0.25

    return score


def ema_slope(df: pd.DataFrame, ema_col: str, lookback: int = 5) -> float:
    """
    Normalised slope of an EMA over `lookback` bars.
    Returns percentage change per bar (positive = rising, negative = falling).
    """
    if len(df) < lookback + 1:
        return 0.0
    current = float(df[ema_col].iloc[-1])
    past = float(df[ema_col].iloc[-lookback])
    if past == 0:
        return 0.0
    return ((current - past) / past) * 100 / lookback


def is_ema_flat(df: pd.DataFrame, ema_col: str, lookback: int = 10,
                flat_threshold: float = 0.005) -> bool:
    """
    True if the EMA is essentially flat (sideways).
    flat_threshold: max absolute slope % per bar to be considered flat.
    """
    slope = abs(ema_slope(df, ema_col, lookback))
    return slope < flat_threshold


def resample_higher_tf(df: pd.DataFrame, tf_minutes: int) -> pd.DataFrame:
    """
    Resample a lower-timeframe DataFrame to a higher timeframe.
    E.g., 5m candles -> 15m candles for multi-timeframe analysis.
    """
    if df.empty:
        return df

    rule = f"{tf_minutes}min"
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    return resampled
