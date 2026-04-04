from __future__ import annotations

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import EntryMode, SignalType, StopLossType, TargetType
from src.core.logger import get_logger
from src.indicators.atr import (
    candle_range_filter,
    compute_atr,
    find_swing_high,
    find_swing_low,
    is_market_trending,
)
from src.indicators.ema import (
    compute_emas,
    is_bearish_crossover,
    is_bullish_crossover,
    is_ema_trending_down,
    is_ema_trending_up,
    is_price_above_ema,
    is_price_below_ema,
)
from src.indicators.volume import is_volume_confirmed
from src.strategy.base import BaseStrategy
from src.strategy.signals import Signal

logger = get_logger("ema_strategy")


class EMAStrategy(BaseStrategy):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.primary = config.ema.primary_period
        self.short = config.ema.short_period
        self.long = config.ema.long_period

        self.primary_col = f"ema_{self.primary}"
        self.short_col = f"ema_{self.short}"
        self.long_col = f"ema_{self.long}"

    def name(self) -> str:
        return f"EMA({self.primary}/{self.short}/{self.long})"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = compute_emas(df, self.primary, self.short, self.long)
        df["atr"] = compute_atr(df, self.config.sideways_filter.atr_period)
        return df

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < max(self.primary, self.short, self.long) + 2:
            return self._no_signal(df)

        df = self.compute_indicators(df)
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        if not self._passes_sideways_filter(df):
            return Signal(SignalType.NO_SIGNAL, price, now, reason="sideways_market")

        if self.config.entry.volume_confirmation and not is_volume_confirmed(
            df, self.config.entry.volume_multiplier
        ):
            return Signal(SignalType.NO_SIGNAL, price, now, reason="low_volume")

        long_signal = self._check_long(df)
        if long_signal:
            sl = self.compute_stop_loss(df, long_signal)
            tp = self.compute_target(df, long_signal, sl)
            long_signal.stop_loss = sl
            long_signal.target = tp
            logger.info("LONG signal: %s", long_signal)
            return long_signal

        short_signal = self._check_short(df)
        if short_signal:
            sl = self.compute_stop_loss(df, short_signal)
            tp = self.compute_target(df, short_signal, sl)
            short_signal.stop_loss = sl
            short_signal.target = tp
            logger.info("SHORT signal: %s", short_signal)
            return short_signal

        return self._no_signal(df)

    def _check_long(self, df: pd.DataFrame) -> Signal | None:
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        if not is_price_above_ema(df, self.primary_col):
            return None

        if self.config.ema.use_crossover_confirmation:
            if not is_ema_trending_up(df, self.short_col, self.long_col):
                return None

        if not self._has_bullish_momentum(df):
            return None

        mode = EntryMode(self.config.entry.mode)
        reason = ""

        if mode in (EntryMode.BREAKOUT, EntryMode.BOTH):
            if self._is_breakout_long(df):
                reason = "breakout_long"
        if not reason and mode in (EntryMode.PULLBACK, EntryMode.BOTH):
            if self._is_pullback_long(df):
                reason = "pullback_long"

        if not reason:
            return None

        if not self._is_bullish_candle(df):
            return None

        confidence = 0.5
        if is_bullish_crossover(df, self.short_col, self.long_col):
            confidence += 0.3
        if is_price_above_ema(df, self.short_col):
            confidence += 0.1
        if self._has_strong_body(df):
            confidence += 0.1

        return Signal(
            type=SignalType.LONG,
            price=price,
            timestamp=now,
            reason=reason,
            confidence=min(confidence, 1.0),
        )

    def _check_short(self, df: pd.DataFrame) -> Signal | None:
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        if not is_price_below_ema(df, self.primary_col):
            return None

        if self.config.ema.use_crossover_confirmation:
            if not is_ema_trending_down(df, self.short_col, self.long_col):
                return None

        if not self._has_bearish_momentum(df):
            return None

        mode = EntryMode(self.config.entry.mode)
        reason = ""

        if mode in (EntryMode.BREAKOUT, EntryMode.BOTH):
            if self._is_breakdown_short(df):
                reason = "breakdown_short"
        if not reason and mode in (EntryMode.PULLBACK, EntryMode.BOTH):
            if self._is_rejection_short(df):
                reason = "rejection_short"

        if not reason:
            return None

        if not self._is_bearish_candle(df):
            return None

        confidence = 0.5
        if is_bearish_crossover(df, self.short_col, self.long_col):
            confidence += 0.3
        if is_price_below_ema(df, self.short_col):
            confidence += 0.1
        if self._has_strong_body(df):
            confidence += 0.1

        return Signal(
            type=SignalType.SHORT,
            price=price,
            timestamp=now,
            reason=reason,
            confidence=min(confidence, 1.0),
        )

    # ------------------------------------------------------------------
    # Momentum filters: require recent bars to align with direction
    # ------------------------------------------------------------------
    def _has_bullish_momentum(self, df: pd.DataFrame, lookback: int = 3) -> bool:
        """At least 2 of the last `lookback` candles should close above their open."""
        if len(df) < lookback:
            return True
        recent = df.iloc[-lookback:]
        bullish_count = (recent["close"] > recent["open"]).sum()
        return bullish_count >= 2

    def _has_bearish_momentum(self, df: pd.DataFrame, lookback: int = 3) -> bool:
        if len(df) < lookback:
            return True
        recent = df.iloc[-lookback:]
        bearish_count = (recent["close"] < recent["open"]).sum()
        return bearish_count >= 2

    # ------------------------------------------------------------------
    # Candle quality: the entry candle itself must be directional
    # ------------------------------------------------------------------
    def _is_bullish_candle(self, df: pd.DataFrame) -> bool:
        """Current candle closes in top 60% of its range (not a doji/reversal)."""
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng == 0:
            return False
        position = (float(bar["close"]) - float(bar["low"])) / rng
        return position >= 0.4

    def _is_bearish_candle(self, df: pd.DataFrame) -> bool:
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng == 0:
            return False
        position = (float(bar["high"]) - float(bar["close"])) / rng
        return position >= 0.4

    def _has_strong_body(self, df: pd.DataFrame) -> bool:
        """Candle body is >= 50% of total range (low wick ratio)."""
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng == 0:
            return False
        body = abs(float(bar["close"]) - float(bar["open"]))
        return (body / rng) >= 0.50

    # ------------------------------------------------------------------
    # Entry triggers
    # ------------------------------------------------------------------
    def _is_breakout_long(self, df: pd.DataFrame) -> bool:
        if len(df) < 2:
            return False
        curr_close = float(df["close"].iloc[-1])
        prev_high = float(df["high"].iloc[-2])
        if self.config.entry.confirm_candle_close:
            return curr_close > prev_high
        return float(df["high"].iloc[-1]) > prev_high

    def _is_breakdown_short(self, df: pd.DataFrame) -> bool:
        if len(df) < 2:
            return False
        curr_close = float(df["close"].iloc[-1])
        prev_low = float(df["low"].iloc[-2])
        if self.config.entry.confirm_candle_close:
            return curr_close < prev_low
        return float(df["low"].iloc[-1]) < prev_low

    def _is_pullback_long(self, df: pd.DataFrame) -> bool:
        """Price pulled back to EMA7 and bounced (low touched EMA, close above it)."""
        if len(df) < 2:
            return False
        ema_val = float(df[self.primary_col].iloc[-1])
        low = float(df["low"].iloc[-1])
        close = float(df["close"].iloc[-1])
        tolerance = ema_val * 0.002
        return low <= ema_val + tolerance and close > ema_val

    def _is_rejection_short(self, df: pd.DataFrame) -> bool:
        if len(df) < 2:
            return False
        ema_val = float(df[self.primary_col].iloc[-1])
        high = float(df["high"].iloc[-1])
        close = float(df["close"].iloc[-1])
        tolerance = ema_val * 0.002
        return high >= ema_val - tolerance and close < ema_val

    # ------------------------------------------------------------------
    # Sideways filter
    # ------------------------------------------------------------------
    def _passes_sideways_filter(self, df: pd.DataFrame) -> bool:
        if not self.config.sideways_filter.enabled:
            return True
        method = self.config.sideways_filter.method
        if method == "atr":
            return is_market_trending(
                df,
                self.config.sideways_filter.atr_period,
                self.config.sideways_filter.atr_threshold,
            )
        elif method == "candle_range":
            return candle_range_filter(df, self.config.sideways_filter.candle_range_min)
        return True

    # ------------------------------------------------------------------
    # Stop loss / target
    # ------------------------------------------------------------------
    def compute_stop_loss(self, df: pd.DataFrame, signal: Signal) -> float:
        sl_cfg = self.config.exit.stop_loss
        sl_type = StopLossType(sl_cfg.type)
        price = signal.price

        if sl_type == StopLossType.FIXED_POINTS:
            offset = sl_cfg.value
        elif sl_type == StopLossType.FIXED_PCT:
            offset = price * (sl_cfg.value / 100.0)
        elif sl_type == StopLossType.SWING:
            if signal.type == SignalType.LONG:
                return find_swing_low(df, lookback=10)
            else:
                return find_swing_high(df, lookback=10)
        elif sl_type == StopLossType.EMA_BREACH:
            ema_val = float(df[self.primary_col].iloc[-1])
            buffer = ema_val * 0.001
            if signal.type == SignalType.LONG:
                return ema_val - buffer
            else:
                return ema_val + buffer
        else:
            offset = sl_cfg.value

        if signal.type == SignalType.LONG:
            return price - offset
        else:
            return price + offset

    def compute_target(self, df: pd.DataFrame, signal: Signal, stop_loss: float) -> float:
        tp_cfg = self.config.exit.target
        tp_type = TargetType(tp_cfg.type)
        price = signal.price
        risk = abs(price - stop_loss)

        if tp_type == TargetType.RISK_REWARD:
            reward = risk * tp_cfg.risk_reward_ratio
        elif tp_type == TargetType.FIXED_POINTS:
            reward = tp_cfg.value
        elif tp_type == TargetType.FIXED_PCT:
            reward = price * (tp_cfg.value / 100.0)
        else:
            reward = risk * 2.0

        if signal.type == SignalType.LONG:
            return price + reward
        else:
            return price - reward

    def _no_signal(self, df: pd.DataFrame) -> Signal:
        price = float(df["close"].iloc[-1]) if not df.empty else 0.0
        ts = df.index[-1] if not df.empty else pd.Timestamp.now()
        return Signal(SignalType.NO_SIGNAL, price, ts, reason="no_setup")
