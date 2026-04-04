from __future__ import annotations

import pandas as pd


def compute_avg_volume(df: pd.DataFrame, period: int = 20) -> float:
    if len(df) < period:
        period = len(df)
    if period == 0:
        return 0.0
    return float(df["volume"].iloc[-period:].mean())


def is_volume_confirmed(df: pd.DataFrame, multiplier: float = 1.5, period: int = 20) -> bool:
    """True if current candle volume exceeds multiplier * average volume."""
    if df.empty:
        return False
    avg = compute_avg_volume(df.iloc[:-1], period) if len(df) > 1 else 0.0
    if avg <= 0:
        return True  # pass-through when no volume data
    current = float(df["volume"].iloc[-1])
    return current >= multiplier * avg
