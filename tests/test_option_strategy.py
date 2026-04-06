"""Tests for the MA-EMA crossover options strategy and supporting modules."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.core.config import AppConfig
from src.core.constants import (
    ExitReason, OISignal, OptionType, OrderSide, SignalType, TradeGrade,
)
from src.indicators.ema import (
    sma, ema, ema_of_sma, compute_ma_ema,
    is_ma_ema_bullish_crossover, is_ma_ema_bearish_crossover,
    is_ma_above_ema, is_ma_below_ema,
)
from src.options.oi_analyzer import OIAnalyzer, OISnapshot
from src.options.option_selector import OptionSelector, estimate_option_premium
from src.strategy.option_ema_strategy import OptionEMAStrategy
from src.strategy.signals import Signal


def _make_candles(n: int = 200, trend: str = "up", base: float = 22000.0) -> pd.DataFrame:
    np.random.seed(42)
    timestamps = pd.date_range(start="2025-06-01 09:15", periods=n, freq="5min")

    if trend == "up":
        noise = np.random.randn(n) * 20
        closes = base + np.cumsum(np.abs(noise) * 0.5 + 2)
    elif trend == "down":
        noise = np.random.randn(n) * 20
        closes = base - np.cumsum(np.abs(noise) * 0.5 + 2)
    elif trend == "cross_up":
        first = int(n * 0.6)
        second = n - first
        noise1 = np.random.randn(first) * 15
        down = base - np.cumsum(np.abs(noise1) * 0.3 + 1)
        noise2 = np.random.randn(second) * 15
        up = down[-1] + np.cumsum(np.abs(noise2) * 0.8 + 3)
        closes = np.concatenate([down, up])
    elif trend == "cross_down":
        first = int(n * 0.6)
        second = n - first
        noise1 = np.random.randn(first) * 15
        up = base + np.cumsum(np.abs(noise1) * 0.3 + 1)
        noise2 = np.random.randn(second) * 15
        down = up[-1] - np.cumsum(np.abs(noise2) * 0.8 + 3)
        closes = np.concatenate([up, down])
    else:
        closes = base + np.random.randn(n) * 10

    highs = closes + np.abs(np.random.randn(n)) * 15
    lows = closes - np.abs(np.random.randn(n)) * 15
    opens = closes + np.random.randn(n) * 10
    volumes = np.random.randint(5000, 100000, n).astype(float)

    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=timestamps)


class TestSMAFunction(unittest.TestCase):
    def test_sma_length(self):
        s = pd.Series(range(100), dtype=float)
        result = sma(s, 20)
        self.assertEqual(len(result), 100)
        self.assertTrue(result.iloc[:19].isna().all())
        self.assertFalse(result.iloc[19:].isna().any())

    def test_sma_correctness(self):
        s = pd.Series([10.0] * 20)
        result = sma(s, 10)
        self.assertAlmostEqual(result.iloc[-1], 10.0)

    def test_sma_rolling_average(self):
        s = pd.Series(range(1, 11), dtype=float)
        result = sma(s, 5)
        self.assertAlmostEqual(result.iloc[4], 3.0)  # avg(1,2,3,4,5)
        self.assertAlmostEqual(result.iloc[9], 8.0)  # avg(6,7,8,9,10)


class TestEMAOfSMA(unittest.TestCase):
    def test_returns_two_series(self):
        s = pd.Series(range(100), dtype=float)
        ma, ema_ma = ema_of_sma(s, 20, 50)
        self.assertEqual(len(ma), 100)
        self.assertEqual(len(ema_ma), 100)

    def test_ema_smooths_sma(self):
        np.random.seed(1)
        s = pd.Series(np.random.randn(200).cumsum() + 100)
        ma, ema_ma = ema_of_sma(s, 20, 50)
        ma_std = ma.dropna().diff().std()
        ema_std = ema_ma.dropna().diff().std()
        self.assertLess(ema_std, ma_std)


class TestMaEmaCrossover(unittest.TestCase):
    def test_bullish_crossover_detection(self):
        df = _make_candles(300, trend="cross_up")
        df = compute_ma_ema(df, 20, 50)
        found = False
        for i in range(60, len(df)):
            window = df.iloc[:i + 1]
            if is_ma_ema_bullish_crossover(window):
                found = True
                break
        self.assertTrue(found, "Should detect bullish crossover in down-to-up data")

    def test_bearish_crossover_detection(self):
        df = _make_candles(300, trend="cross_down")
        df = compute_ma_ema(df, 20, 50)
        found = False
        for i in range(60, len(df)):
            window = df.iloc[:i + 1]
            if is_ma_ema_bearish_crossover(window):
                found = True
                break
        self.assertTrue(found, "Should detect bearish crossover in up-to-down data")

    def test_ma_above_ema_in_uptrend(self):
        df = _make_candles(200, trend="up")
        df = compute_ma_ema(df, 20, 50)
        self.assertTrue(is_ma_above_ema(df))

    def test_ma_below_ema_in_downtrend(self):
        df = _make_candles(200, trend="down")
        df = compute_ma_ema(df, 20, 50)
        self.assertTrue(is_ma_below_ema(df))


class TestOIAnalyzer(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig.load()
        self.config.oi.enabled = True
        self.config.oi.min_oi_change_pct = 1.0
        self.config.oi.lookback_periods = 3
        self.analyzer = OIAnalyzer(self.config)

    def test_long_buildup(self):
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT1", oi=10000 + i * 200, price=200 + i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        analysis = self.analyzer.analyze("OPT1")
        self.assertEqual(analysis.signal, OISignal.LONG_BUILDUP)
        self.assertTrue(analysis.is_valid_for_ce)

    def test_short_buildup(self):
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT2", oi=10000 + i * 200, price=200 - i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        analysis = self.analyzer.analyze("OPT2")
        self.assertEqual(analysis.signal, OISignal.SHORT_BUILDUP)
        self.assertTrue(analysis.is_valid_for_pe)

    def test_long_unwinding(self):
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT3", oi=10000 - i * 200, price=200 - i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        analysis = self.analyzer.analyze("OPT3")
        self.assertEqual(analysis.signal, OISignal.LONG_UNWINDING)

    def test_short_covering(self):
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT4", oi=10000 - i * 200, price=200 + i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        analysis = self.analyzer.analyze("OPT4")
        self.assertEqual(analysis.signal, OISignal.SHORT_COVERING)

    def test_validate_ce_with_long_buildup(self):
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT5", oi=10000 + i * 200, price=200 + i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        valid, reason = self.analyzer.validate_trade(SignalType.LONG, "OPT5")
        self.assertTrue(valid)
        self.assertIn("confirmed", reason)

    def test_reject_ce_on_unwinding(self):
        self.config.oi.reject_unwinding = True
        base = datetime.now()
        for i in range(5):
            self.analyzer.record_snapshot(
                "OPT6", oi=10000 - i * 200, price=200 - i * 2,
                timestamp=base + timedelta(minutes=i * 5),
            )
        valid, reason = self.analyzer.validate_trade(SignalType.LONG, "OPT6")
        self.assertFalse(valid)
        self.assertIn("rejected", reason)

    def test_insufficient_data_passes(self):
        valid, reason = self.analyzer.validate_trade(SignalType.LONG, "UNKNOWN")
        self.assertTrue(valid)

    def test_pcr_calculation(self):
        chain = {"data": [
            {"optionType": "CALL", "openInterest": 5000},
            {"optionType": "CALL", "openInterest": 3000},
            {"optionType": "PUT", "openInterest": 6000},
            {"optionType": "PUT", "openInterest": 4000},
        ]}
        pcr = self.analyzer.get_pcr(chain)
        self.assertAlmostEqual(pcr, 10000 / 8000, places=2)


class TestOptionSelector(unittest.TestCase):
    def test_atm_strike(self):
        config = AppConfig.load()
        config.options.strike_selection = "atm"
        config.options.strike_interval = 50
        selector = OptionSelector(config)
        contract = selector.select_contract(SignalType.LONG, 22123.0)
        self.assertEqual(contract.option_type, OptionType.CALL)
        self.assertEqual(contract.strike, 22100.0)

    def test_short_gives_put(self):
        config = AppConfig.load()
        selector = OptionSelector(config)
        contract = selector.select_contract(SignalType.SHORT, 22000.0)
        self.assertEqual(contract.option_type, OptionType.PUT)

    def test_with_oi_analyzer(self):
        config = AppConfig.load()
        config.oi.enabled = True
        oi_analyzer = OIAnalyzer(config)
        selector = OptionSelector(config, oi_analyzer)
        contract = selector.select_contract(SignalType.LONG, 22000.0)
        self.assertIsNotNone(contract)

    def test_premium_filter(self):
        config = AppConfig.load()
        config.options.min_premium = 50
        config.options.max_premium = 500
        selector = OptionSelector(config)
        self.assertTrue(selector._passes_premium_filter(200))
        self.assertFalse(selector._passes_premium_filter(10))
        self.assertFalse(selector._passes_premium_filter(600))


class TestOptionEMAStrategy(unittest.TestCase):
    def test_compute_indicators(self):
        config = AppConfig.load()
        strategy = OptionEMAStrategy(config)
        df = _make_candles(200, trend="up")
        result = strategy.compute_indicators(df)
        self.assertIn("ma", result.columns)
        self.assertIn("ema_of_ma", result.columns)
        self.assertIn("atr", result.columns)

    def test_name(self):
        config = AppConfig.load()
        strategy = OptionEMAStrategy(config)
        name = strategy.name()
        self.assertIn("OptMA", name)

    def test_generates_no_signal_insufficient_data(self):
        config = AppConfig.load()
        strategy = OptionEMAStrategy(config)
        df = _make_candles(10, trend="up")
        signal = strategy.generate_signal(df)
        self.assertEqual(signal.type, SignalType.NO_SIGNAL)

    def test_generates_signals_on_crossover_data(self):
        config = AppConfig.load()
        config.strategy.use_multi_timeframe = False
        config.strategy.use_volume_filter = False
        config.sideways_filter.enabled = False
        config.strategy.min_grade = "C"
        config.entry.cooldown_bars = 0
        strategy = OptionEMAStrategy(config)

        df = _make_candles(300, trend="cross_up")
        found_long = False
        for i in range(60, len(df)):
            window = df.iloc[:i + 1]
            signal = strategy.generate_signal(window)
            if signal.type == SignalType.LONG:
                found_long = True
                self.assertGreater(signal.confidence, 0)
                self.assertIn("bullish", signal.reason)
                break

        self.assertTrue(found_long, "Should find a LONG signal in cross_up data")

    def test_htf_blocks_wrong_direction(self):
        config = AppConfig.load()
        config.strategy.use_multi_timeframe = True
        config.strategy.use_volume_filter = False
        config.sideways_filter.enabled = False
        config.strategy.min_grade = "C"
        strategy = OptionEMAStrategy(config)

        df = _make_candles(100, trend="down")
        signal = strategy.generate_signal(df)
        if signal.type == SignalType.LONG:
            self.fail("Should not generate LONG in bearish HTF context")


class TestOptionsBacktester(unittest.TestCase):
    def test_backtest_runs(self):
        from src.backtest.options_backtester import OptionsBacktester

        config = AppConfig.load()
        config.strategy.use_multi_timeframe = False
        config.strategy.use_volume_filter = False
        config.sideways_filter.enabled = False
        config.strategy.min_grade = "C"
        config.entry.cooldown_bars = 0
        config.backtest.next_candle_entry = True
        config.backtest.slippage_pct = 0.0

        df = _make_candles(300, trend="cross_up")
        engine = OptionsBacktester(config)
        trades = engine.run(df)

        self.assertIsInstance(trades, list)
        self.assertGreater(len(engine.equity_curve), 0)

    def test_backtest_on_flat_market_few_trades(self):
        from src.backtest.options_backtester import OptionsBacktester

        config = AppConfig.load()
        config.strategy.use_multi_timeframe = False
        config.strategy.use_volume_filter = False
        config.sideways_filter.enabled = True
        config.sideways_filter.atr_threshold = 0.5
        config.strategy.min_grade = "A"

        df = _make_candles(200, trend="sideways")
        engine = OptionsBacktester(config)
        trades = engine.run(df)

        self.assertLessEqual(len(trades), 5)


class TestPremiumEstimate(unittest.TestCase):
    def test_atm_premium(self):
        p = estimate_option_premium(22000, 22000, OptionType.CALL)
        self.assertGreater(p, 0)

    def test_itm_call_more_expensive(self):
        itm = estimate_option_premium(22100, 22000, OptionType.CALL)
        otm = estimate_option_premium(21900, 22000, OptionType.CALL)
        self.assertGreater(itm, otm)

    def test_put_premium(self):
        p = estimate_option_premium(22000, 22000, OptionType.PUT)
        self.assertGreater(p, 0)

    def test_deep_otm_cheap(self):
        deep_otm = estimate_option_premium(22000, 23000, OptionType.CALL)
        atm = estimate_option_premium(22000, 22000, OptionType.CALL)
        self.assertLess(deep_otm, atm)


if __name__ == "__main__":
    unittest.main()
