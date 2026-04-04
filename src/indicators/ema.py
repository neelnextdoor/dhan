from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_emas(df: pd.DataFrame, primary: int, short: int, long: int) -> pd.DataFrame:
    """Add EMA columns to a DataFrame with OHLCV data."""
    df = df.copy()
    df[f"ema_{primary}"] = ema(df["close"], primary)
    df[f"ema_{short}"] = ema(df["close"], short)
    df[f"ema_{long}"] = ema(df["close"], long)
    return df


def is_bullish_crossover(df: pd.DataFrame, short_col: str, long_col: str) -> bool:
    """True when short EMA just crossed above long EMA (current bar)."""
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
