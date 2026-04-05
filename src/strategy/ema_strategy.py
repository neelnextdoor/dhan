from __future__ import annotations

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import EntryMode, SignalType, StopLossType, TargetType, TradeGrade
from src.core.logger import get_logger
from src.indicators.atr import (
    atr_expansion,
    atr_percentile,
    candle_range_filter,
    compute_atr,
    find_swing_high,
    find_swing_low,
    is_market_trending,
    is_range_bound,
)
from src.indicators.ema import (
    compute_emas,
    ema,
    ema_alignment_score,
    ema_slope,
    is_bearish_crossover,
    is_bullish_crossover,
    is_ema_flat,
    is_ema_trending_down,
    is_ema_trending_up,
    is_price_above_ema,
    is_price_below_ema,
    resample_higher_tf,
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
        self.trend = config.ema.trend_period

        self.primary_col = f"ema_{self.primary}"
        self.short_col = f"ema_{self.short}"
        self.long_col = f"ema_{self.long}"
        self.trend_col = f"ema_{self.trend}"

        self._last_signal_bar = None
        self._bars_since_signal = 999
        self._consecutive_losses = 0
        self._htf_cache: pd.DataFrame | None = None
        self._htf_cache_len: int = 0

    def name(self) -> str:
        return f"EMA({self.primary}/{self.short}/{self.long}/{self.trend})"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = compute_emas(df, self.primary, self.short, self.long, self.trend)
        df["atr"] = compute_atr(df, self.config.sideways_filter.atr_period)
        return df

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        min_bars = max(self.primary, self.short, self.long, self.trend) + 5
        if len(df) < min_bars:
            return self._no_signal(df)

        df = self.compute_indicators(df)
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        self._bars_since_signal += 1

        # ── Gate 1: Sideways / consolidation filter ──
        sideways_result = self._passes_sideways_filter(df)
        if not sideways_result:
            return Signal(SignalType.NO_SIGNAL, price, now, reason="sideways_market")

        # ── Gate 2: Cooldown after signal (prevent rapid re-entry) ──
        if self._bars_since_signal < self.config.entry.cooldown_bars:
            return Signal(SignalType.NO_SIGNAL, price, now, reason="cooldown")

        # ── Gate 3: Volume (optional) ──
        if self.config.entry.volume_confirmation and not is_volume_confirmed(
            df, self.config.entry.volume_multiplier
        ):
            return Signal(SignalType.NO_SIGNAL, price, now, reason="low_volume")

        # ── Gate 4: Higher timeframe bias ──
        htf_bias = self._get_htf_bias(df)

        # ── Check signals ──
        long_signal = self._check_long(df, htf_bias)
        if long_signal and long_signal.passes_grade_filter(
            TradeGrade(self.config.entry.min_grade)
        ):
            sl = self.compute_stop_loss(df, long_signal)
            tp = self.compute_target(df, long_signal, sl)
            long_signal.stop_loss = sl
            long_signal.target = tp
            self._bars_since_signal = 0
            logger.info("LONG %s: %s", long_signal.grade.value, long_signal)
            return long_signal

        short_signal = self._check_short(df, htf_bias)
        if short_signal and short_signal.passes_grade_filter(
            TradeGrade(self.config.entry.min_grade)
        ):
            sl = self.compute_stop_loss(df, short_signal)
            tp = self.compute_target(df, short_signal, sl)
            short_signal.stop_loss = sl
            short_signal.target = tp
            self._bars_since_signal = 0
            logger.info("SHORT %s: %s", short_signal.grade.value, short_signal)
            return short_signal

        return self._no_signal(df)

    # ==================================================================
    # Multi-timeframe analysis
    # ==================================================================
    def _get_htf_bias(self, df: pd.DataFrame) -> str | None:
        """Determine higher-timeframe trend bias."""
        mtf = self.config.multi_timeframe
        if not mtf.enabled:
            return None

        if self._htf_cache is not None and len(df) - self._htf_cache_len < 3:
            htf = self._htf_cache
        else:
            htf = resample_higher_tf(df, mtf.higher_tf_minutes)
            if len(htf) < mtf.htf_ema_period + 5:
                return None
            htf[f"htf_ema_{mtf.htf_ema_period}"] = ema(htf["close"], mtf.htf_ema_period)
            self._htf_cache = htf
            self._htf_cache_len = len(df)

        htf_ema_col = f"htf_ema_{mtf.htf_ema_period}"
        if htf_ema_col not in htf.columns:
            return None

        htf_price = float(htf["close"].iloc[-1])
        htf_ema_val = float(htf[htf_ema_col].iloc[-1])
        htf_slope = ema_slope(htf, htf_ema_col, lookback=3)

        if htf_price > htf_ema_val and htf_slope > 0:
            return "bullish"
        elif htf_price < htf_ema_val and htf_slope < 0:
            return "bearish"
        return None

    # ==================================================================
    # Signal scoring & grading
    # ==================================================================
    def _score_signal(self, df: pd.DataFrame, direction: str,
                      htf_bias: str | None) -> tuple[float, dict, TradeGrade]:
        """
        Multi-factor scoring system. Returns (total_score, breakdown, grade).
        Max score = 10. Grade thresholds: A+ >= 8, A >= 6, B >= 4, C < 4.
        """
        scores: dict[str, float] = {}

        # 1. EMA alignment (0-2 pts)
        alignment = ema_alignment_score(
            df, self.primary_col, self.short_col, self.long_col, self.trend_col
        )
        if direction == "long":
            scores["ema_alignment"] = max(0, alignment * 2)
        else:
            scores["ema_alignment"] = max(0, -alignment * 2)

        # 2. EMA slope strength (0-1.5 pts)
        slope_primary = ema_slope(df, self.primary_col, lookback=5)
        slope_long = ema_slope(df, self.long_col, lookback=5)
        if direction == "long":
            slope_score = min(1.5, max(0, (slope_primary + slope_long) * 5))
        else:
            slope_score = min(1.5, max(0, (-slope_primary - slope_long) * 5))
        scores["ema_slope"] = slope_score

        # 3. Higher timeframe alignment (0-2 pts)
        if htf_bias:
            if (direction == "long" and htf_bias == "bullish") or \
               (direction == "short" and htf_bias == "bearish"):
                scores["htf_alignment"] = 2.0
            elif htf_bias is None:
                scores["htf_alignment"] = 0.5
            else:
                scores["htf_alignment"] = 0.0
        else:
            scores["htf_alignment"] = 1.0 if not self.config.multi_timeframe.enabled else 0.5

        # 4. Crossover confirmation (0-1.5 pts)
        if direction == "long":
            if is_bullish_crossover(df, self.short_col, self.long_col):
                scores["crossover"] = 1.5
            elif is_ema_trending_up(df, self.short_col, self.long_col):
                scores["crossover"] = 0.75
            else:
                scores["crossover"] = 0.0
        else:
            if is_bearish_crossover(df, self.short_col, self.long_col):
                scores["crossover"] = 1.5
            elif is_ema_trending_down(df, self.short_col, self.long_col):
                scores["crossover"] = 0.75
            else:
                scores["crossover"] = 0.0

        # 5. Candle quality (0-1.5 pts)
        candle_score = 0.0
        if self._has_strong_body(df):
            candle_score += 0.75
        if direction == "long" and self._is_bullish_candle(df):
            candle_score += 0.75
        elif direction == "short" and self._is_bearish_candle(df):
            candle_score += 0.75
        scores["candle_quality"] = min(1.5, candle_score)

        # 6. Momentum (0-1.5 pts)
        if direction == "long":
            mom = self._bullish_momentum_score(df)
        else:
            mom = self._bearish_momentum_score(df)
        scores["momentum"] = min(1.5, mom)

        total = sum(scores.values())
        total = min(10.0, total)

        if total >= 8.0:
            grade = TradeGrade.A_PLUS
        elif total >= 6.0:
            grade = TradeGrade.A
        elif total >= 4.0:
            grade = TradeGrade.B
        else:
            grade = TradeGrade.C

        return total, scores, grade

    # ==================================================================
    # Long / Short signal detection
    # ==================================================================
    def _check_long(self, df: pd.DataFrame, htf_bias: str | None) -> Signal | None:
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        if not is_price_above_ema(df, self.primary_col):
            return None

        if self.config.ema.use_crossover_confirmation:
            if not is_ema_trending_up(df, self.short_col, self.long_col):
                return None

        # Require price above trend EMA for strong longs
        if not is_price_above_ema(df, self.trend_col):
            return None

        # HTF filter: block longs in bearish HTF
        if self.config.multi_timeframe.require_htf_alignment and htf_bias == "bearish":
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

        total_score, breakdown, grade = self._score_signal(df, "long", htf_bias)
        confidence = total_score / 10.0

        return Signal(
            type=SignalType.LONG,
            price=price,
            timestamp=now,
            reason=reason,
            confidence=confidence,
            grade=grade,
            score_breakdown=breakdown,
            htf_bias=htf_bias,
        )

    def _check_short(self, df: pd.DataFrame, htf_bias: str | None) -> Signal | None:
        now = df.index[-1]
        price = float(df["close"].iloc[-1])

        if not is_price_below_ema(df, self.primary_col):
            return None

        if self.config.ema.use_crossover_confirmation:
            if not is_ema_trending_down(df, self.short_col, self.long_col):
                return None

        if not is_price_below_ema(df, self.trend_col):
            return None

        if self.config.multi_timeframe.require_htf_alignment and htf_bias == "bullish":
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

        total_score, breakdown, grade = self._score_signal(df, "short", htf_bias)
        confidence = total_score / 10.0

        return Signal(
            type=SignalType.SHORT,
            price=price,
            timestamp=now,
            reason=reason,
            confidence=confidence,
            grade=grade,
            score_breakdown=breakdown,
            htf_bias=htf_bias,
        )

    # ==================================================================
    # Momentum scoring (graduated, not binary)
    # ==================================================================
    def _has_bullish_momentum(self, df: pd.DataFrame, lookback: int = 3) -> bool:
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

    def _bullish_momentum_score(self, df: pd.DataFrame, lookback: int = 5) -> float:
        """Graduated momentum: how strongly are recent candles bullish? (0-1.5)"""
        if len(df) < lookback:
            return 0.5
        recent = df.iloc[-lookback:]
        bullish = (recent["close"] > recent["open"]).sum()
        bodies = (recent["close"] - recent["open"]).abs()
        ranges = recent["high"] - recent["low"]
        avg_body_ratio = float((bodies / ranges.replace(0, 1)).mean())
        return min(1.5, (bullish / lookback) * avg_body_ratio * 2)

    def _bearish_momentum_score(self, df: pd.DataFrame, lookback: int = 5) -> float:
        if len(df) < lookback:
            return 0.5
        recent = df.iloc[-lookback:]
        bearish = (recent["close"] < recent["open"]).sum()
        bodies = (recent["close"] - recent["open"]).abs()
        ranges = recent["high"] - recent["low"]
        avg_body_ratio = float((bodies / ranges.replace(0, 1)).mean())
        return min(1.5, (bearish / lookback) * avg_body_ratio * 2)

    # ==================================================================
    # Candle quality
    # ==================================================================
    def _is_bullish_candle(self, df: pd.DataFrame) -> bool:
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
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng == 0:
            return False
        body = abs(float(bar["close"]) - float(bar["open"]))
        return (body / rng) >= 0.50

    def _is_doji(self, df: pd.DataFrame) -> bool:
        """Detect doji/indecision candles to avoid."""
        bar = df.iloc[-1]
        rng = float(bar["high"] - bar["low"])
        if rng == 0:
            return True
        body = abs(float(bar["close"]) - float(bar["open"]))
        return (body / rng) < 0.20

    # ==================================================================
    # Entry triggers
    # ==================================================================
    def _is_breakout_long(self, df: pd.DataFrame) -> bool:
        if len(df) < 3:
            return False
        curr_close = float(df["close"].iloc[-1])
        prev_high = float(df["high"].iloc[-2])
        if self.config.entry.confirm_candle_close:
            return curr_close > prev_high
        return float(df["high"].iloc[-1]) > prev_high

    def _is_breakdown_short(self, df: pd.DataFrame) -> bool:
        if len(df) < 3:
            return False
        curr_close = float(df["close"].iloc[-1])
        prev_low = float(df["low"].iloc[-2])
        if self.config.entry.confirm_candle_close:
            return curr_close < prev_low
        return float(df["low"].iloc[-1]) < prev_low

    def _is_pullback_long(self, df: pd.DataFrame) -> bool:
        if len(df) < 3:
            return False
        ema_val = float(df[self.primary_col].iloc[-1])
        low = float(df["low"].iloc[-1])
        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        tolerance = ema_val * 0.003
        touched_ema = low <= ema_val + tolerance
        bounced = close > ema_val
        was_above = prev_close > ema_val
        return touched_ema and bounced and was_above

    def _is_rejection_short(self, df: pd.DataFrame) -> bool:
        if len(df) < 3:
            return False
        ema_val = float(df[self.primary_col].iloc[-1])
        high = float(df["high"].iloc[-1])
        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        tolerance = ema_val * 0.003
        touched_ema = high >= ema_val - tolerance
        rejected = close < ema_val
        was_below = prev_close < ema_val
        return touched_ema and rejected and was_below

    # ==================================================================
    # Sideways / volatility filter (combined multi-method)
    # ==================================================================
    def _passes_sideways_filter(self, df: pd.DataFrame) -> bool:
        if not self.config.sideways_filter.enabled:
            return True

        sf = self.config.sideways_filter
        method = sf.method

        if method == "atr":
            return is_market_trending(df, sf.atr_period, sf.atr_threshold)

        elif method == "candle_range":
            return candle_range_filter(df, sf.candle_range_min)

        elif method == "combined":
            # Multi-method: must pass at least 2 of 3 checks
            checks_passed = 0

            if is_market_trending(df, sf.atr_period, sf.atr_threshold):
                checks_passed += 1

            if not is_ema_flat(df, self.long_col, sf.ema_flat_lookback, sf.ema_flat_threshold):
                checks_passed += 1

            if not is_range_bound(df, sf.range_bound_lookback, sf.range_bound_pct):
                checks_passed += 1

            return checks_passed >= 2

        return True

    # ==================================================================
    # Stop loss / target
    # ==================================================================
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
