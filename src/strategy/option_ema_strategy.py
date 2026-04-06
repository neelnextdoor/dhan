from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import SignalType, TradeGrade
from src.core.logger import get_logger
from src.indicators.atr import compute_atr, is_market_trending
from src.indicators.ema import (
    compute_ma_ema,
    is_ma_above_ema,
    is_ma_below_ema,
    is_ma_ema_bearish_crossover,
    is_ma_ema_bullish_crossover,
    resample_higher_tf,
)
from src.indicators.volume import compute_avg_volume, is_volume_confirmed
from src.strategy.base import BaseStrategy
from src.strategy.signals import Signal

logger = get_logger("option_ema_strategy")


class OptionEMAStrategy(BaseStrategy):
    """
    MA-EMA Crossover Strategy for Options Trading.

    Indicators (computed on SPOT index candles):
      MA  = SMA(close, ma_period)
      EMA = EMA(MA, ema_period)

    Signal generation (on entry timeframe, e.g. 5m):
      BUY  -> MA crosses above EMA  -> Buy CE
      SELL -> MA crosses below EMA  -> Buy PE

    Multi-timeframe confirmation (e.g. 15m):
      CE only if 15m MA > EMA (bullish trend)
      PE only if 15m MA < EMA (bearish trend)

    Volume filter:
      current_volume > volume_multiplier * rolling_avg_volume

    OI confirmation handled externally by OIAnalyzer.
    """

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.ma_period = config.strategy.ma_period
        self.ema_period = config.strategy.ema_period
        self.use_mtf = config.strategy.use_multi_timeframe
        self.use_volume = config.strategy.use_volume_filter
        self.volume_mult = config.strategy.volume_multiplier
        self.volume_lookback = config.strategy.volume_lookback
        self.cooldown_bars = config.entry.cooldown_bars
        self.min_grade = TradeGrade(config.strategy.min_grade)

        self._htf_cache: Optional[pd.DataFrame] = None
        self._htf_cache_len: int = 0
        self._bars_since_signal: int = 999

    def name(self) -> str:
        return f"OptMA({self.ma_period})_EMA({self.ema_period})"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = compute_ma_ema(df, self.ma_period, self.ema_period)
        df["atr"] = compute_atr(df, self.config.sideways_filter.atr_period)
        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        htf_df: pd.DataFrame | None = None,
    ) -> Signal:
        min_bars = max(self.ma_period, self.ema_period) + 5
        if len(df) < min_bars:
            return self._no_signal(df)

        df = self.compute_indicators(df)
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        self._bars_since_signal += 1

        if "ma" not in df.columns or "ema_of_ma" not in df.columns:
            return self._no_signal(df)

        last_ma = df["ma"].iloc[-1]
        last_ema = df["ema_of_ma"].iloc[-1]
        if pd.isna(last_ma) or pd.isna(last_ema):
            return self._no_signal(df)

        # Gate: cooldown
        if self._bars_since_signal < self.cooldown_bars:
            return Signal(SignalType.NO_SIGNAL, price, now, reason="cooldown")

        # Gate: sideways filter
        if self.config.sideways_filter.enabled:
            if not is_market_trending(
                df,
                self.config.sideways_filter.atr_period,
                self.config.sideways_filter.atr_threshold,
            ):
                return Signal(SignalType.NO_SIGNAL, price, now, reason="sideways_market")

        # Gate: volume filter
        if self.use_volume:
            if not is_volume_confirmed(df, self.volume_mult, self.volume_lookback):
                return Signal(SignalType.NO_SIGNAL, price, now, reason="low_volume")

        # Determine higher-timeframe bias
        htf_bias = self._get_htf_bias(df, htf_df)

        # Check for crossover signals
        bullish_cross = is_ma_ema_bullish_crossover(df)
        bearish_cross = is_ma_ema_bearish_crossover(df)

        if bullish_cross:
            if self.use_mtf and htf_bias == "bearish":
                return Signal(SignalType.NO_SIGNAL, price, now, reason="htf_bearish_blocks_ce")

            score, breakdown, grade = self._score_signal(df, "long", htf_bias)
            if not self._passes_grade(grade):
                return Signal(SignalType.NO_SIGNAL, price, now, reason=f"grade_{grade.value}_rejected")

            sl = self._compute_premium_sl(price)
            tp = self._compute_premium_tp(price)
            self._bars_since_signal = 0

            sig = Signal(
                type=SignalType.LONG,
                price=price,
                timestamp=now,
                stop_loss=sl,
                target=tp,
                reason="ma_ema_bullish_crossover",
                confidence=score / 10.0,
                grade=grade,
                score_breakdown=breakdown,
                htf_bias=htf_bias,
            )
            logger.info("BUY CE signal: %s", sig)
            return sig

        if bearish_cross:
            if self.use_mtf and htf_bias == "bullish":
                return Signal(SignalType.NO_SIGNAL, price, now, reason="htf_bullish_blocks_pe")

            score, breakdown, grade = self._score_signal(df, "short", htf_bias)
            if not self._passes_grade(grade):
                return Signal(SignalType.NO_SIGNAL, price, now, reason=f"grade_{grade.value}_rejected")

            sl = self._compute_premium_sl(price)
            tp = self._compute_premium_tp(price)
            self._bars_since_signal = 0

            sig = Signal(
                type=SignalType.SHORT,
                price=price,
                timestamp=now,
                stop_loss=sl,
                target=tp,
                reason="ma_ema_bearish_crossover",
                confidence=score / 10.0,
                grade=grade,
                score_breakdown=breakdown,
                htf_bias=htf_bias,
            )
            logger.info("BUY PE signal: %s", sig)
            return sig

        return self._no_signal(df)

    # ------------------------------------------------------------------
    # Multi-timeframe
    # ------------------------------------------------------------------
    def _get_htf_bias(self, df: pd.DataFrame,
                      htf_df: pd.DataFrame | None = None) -> str | None:
        if not self.use_mtf:
            return None

        htf_minutes = int(self.config.strategy.confirmation_timeframe.replace("m", ""))

        if htf_df is not None and not htf_df.empty:
            htf = htf_df
        else:
            if self._htf_cache is not None and len(df) - self._htf_cache_len < 3:
                htf = self._htf_cache
            else:
                htf = resample_higher_tf(df, htf_minutes)
                self._htf_cache = htf
                self._htf_cache_len = len(df)

        if len(htf) < max(self.ma_period, self.ema_period) + 2:
            return None

        htf = compute_ma_ema(htf, self.ma_period, self.ema_period)
        if "ma" not in htf.columns or "ema_of_ma" not in htf.columns:
            return None

        if is_ma_above_ema(htf):
            return "bullish"
        elif is_ma_below_ema(htf):
            return "bearish"
        return None

    # ------------------------------------------------------------------
    # Signal scoring
    # ------------------------------------------------------------------
    def _score_signal(
        self, df: pd.DataFrame, direction: str, htf_bias: str | None,
    ) -> tuple[float, dict, TradeGrade]:
        scores: dict[str, float] = {}

        # 1. MA-EMA separation strength (0-2)
        ma_val = float(df["ma"].iloc[-1])
        ema_val = float(df["ema_of_ma"].iloc[-1])
        separation = abs(ma_val - ema_val) / ema_val * 100 if ema_val else 0
        scores["crossover_strength"] = min(2.0, separation * 2)

        # 2. HTF alignment (0-2.5)
        if htf_bias:
            aligned = (
                (direction == "long" and htf_bias == "bullish")
                or (direction == "short" and htf_bias == "bearish")
            )
            scores["htf_alignment"] = 2.5 if aligned else 0.0
        else:
            scores["htf_alignment"] = 1.0

        # 3. Volume confirmation (0-2)
        if self.use_volume and is_volume_confirmed(df, self.volume_mult, self.volume_lookback):
            scores["volume"] = 2.0
        elif not self.use_volume:
            scores["volume"] = 1.0
        else:
            scores["volume"] = 0.0

        # 4. Candle quality (0-1.5)
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng > 0:
            body = abs(float(bar["close"]) - float(bar["open"]))
            body_ratio = body / rng
            if direction == "long":
                close_position = (float(bar["close"]) - float(bar["low"])) / rng
            else:
                close_position = (float(bar["high"]) - float(bar["close"])) / rng
            scores["candle_quality"] = min(1.5, (body_ratio + close_position) * 0.75)
        else:
            scores["candle_quality"] = 0.0

        # 5. ATR trending (0-2)
        if "atr" in df.columns:
            atr_val = float(df["atr"].iloc[-1])
            price = float(df["close"].iloc[-1])
            atr_pct = (atr_val / price) * 100 if price > 0 else 0
            scores["atr_trending"] = min(2.0, atr_pct * 10)
        else:
            scores["atr_trending"] = 1.0

        total = min(10.0, sum(scores.values()))

        if total >= 8.0:
            grade = TradeGrade.A_PLUS
        elif total >= 6.0:
            grade = TradeGrade.A
        elif total >= 4.0:
            grade = TradeGrade.B
        else:
            grade = TradeGrade.C

        return total, scores, grade

    def _passes_grade(self, grade: TradeGrade) -> bool:
        rank = {TradeGrade.A_PLUS: 4, TradeGrade.A: 3, TradeGrade.B: 2, TradeGrade.C: 1}
        return rank.get(grade, 0) >= rank.get(self.min_grade, 0)

    # ------------------------------------------------------------------
    # SL / TP (premium-based)
    # ------------------------------------------------------------------
    def _compute_premium_sl(self, price: float) -> float:
        return price * (1 - self.config.options.premium_sl_pct / 100)

    def _compute_premium_tp(self, price: float) -> float:
        return price * (1 + self.config.options.premium_target_pct / 100)

    def compute_stop_loss(self, df: pd.DataFrame, signal: Signal) -> float:
        return self._compute_premium_sl(signal.price)

    def compute_target(self, df: pd.DataFrame, signal: Signal, stop_loss: float) -> float:
        return self._compute_premium_tp(signal.price)

    def _no_signal(self, df: pd.DataFrame) -> Signal:
        price = float(df["close"].iloc[-1]) if not df.empty else 0.0
        ts = df.index[-1] if not df.empty else pd.Timestamp.now()
        return Signal(SignalType.NO_SIGNAL, price, ts, reason="no_crossover")
