"""Unit tests for the EMA strategy and supporting modules."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.core.config import AppConfig
from src.core.constants import ExitReason, OptionType, OrderSide, SignalType
from src.execution.position_manager import PositionManager
from src.indicators.ema import ema, is_bullish_crossover, is_bearish_crossover
from src.indicators.atr import compute_atr, is_market_trending
from src.options.contract_selector import ContractSelector, estimate_option_premium
from src.risk.risk_manager import RiskManager
from src.strategy.ema_strategy import EMAStrategy


def _make_candles(n: int = 100, trend: str = "up", base: float = 20000.0) -> pd.DataFrame:
    np.random.seed(42)
    timestamps = pd.date_range(start="2025-06-01 09:15", periods=n, freq="5min")

    if trend == "up":
        noise = np.random.randn(n) * 20
        closes = base + np.cumsum(np.abs(noise) * 0.5 + 2)
    elif trend == "down":
        noise = np.random.randn(n) * 20
        closes = base - np.cumsum(np.abs(noise) * 0.5 + 2)
    else:
        closes = base + np.random.randn(n) * 10

    highs = closes + np.abs(np.random.randn(n)) * 15
    lows = closes - np.abs(np.random.randn(n)) * 15
    opens = closes + np.random.randn(n) * 10
    volumes = np.random.randint(1000, 50000, n).astype(float)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=timestamps)
    return df


class TestEMAIndicator(unittest.TestCase):
    def test_ema_length(self):
        s = pd.Series(range(100), dtype=float)
        result = ema(s, 7)
        self.assertEqual(len(result), 100)

    def test_ema_smoothing(self):
        s = pd.Series([10.0] * 50 + [20.0] * 50)
        result = ema(s, 7)
        self.assertAlmostEqual(result.iloc[49], 10.0, places=1)
        self.assertGreater(result.iloc[99], 19.0)

    def test_bullish_crossover(self):
        df_down = _make_candles(60, trend="down", base=20500.0)
        df_up = _make_candles(60, trend="up", base=float(df_down["close"].iloc[-1]))
        df_up.index = pd.date_range(start=df_down.index[-1] + pd.Timedelta(minutes=5), periods=len(df_up), freq="5min")
        df = pd.concat([df_down, df_up])

        from src.indicators.ema import compute_emas
        df = compute_emas(df, 7, 9, 21)
        found = False
        for i in range(2, len(df)):
            window = df.iloc[:i+1]
            if is_bullish_crossover(window, "ema_9", "ema_21"):
                found = True
                break
        self.assertTrue(found, "Expected at least one bullish crossover in down-to-up transition")


class TestATR(unittest.TestCase):
    def test_atr_positive(self):
        df = _make_candles(50)
        atr = compute_atr(df, 14)
        self.assertTrue((atr.iloc[14:] > 0).all())

    def test_trending_market(self):
        df = _make_candles(100, trend="up")
        result = is_market_trending(df, 14, 0.01)
        self.assertTrue(result)


class TestPositionManager(unittest.TestCase):
    def test_open_close_option_trade(self):
        pm = PositionManager()
        self.assertFalse(pm.has_open_position)

        trade = pm.open_trade(
            "NIFTY", SignalType.LONG, entry_price=200.0, quantity=50,
            stop_loss=140.0, target=320.0,
            option_type=OptionType.CALL, strike=22000, expiry="2025-06-19",
        )
        self.assertTrue(pm.has_open_position)
        self.assertEqual(trade.side, OrderSide.BUY)
        self.assertEqual(trade.option_type, OptionType.CALL)
        self.assertEqual(trade.strike, 22000)
        self.assertTrue(trade.is_option)

        closed = pm.close_trade(300.0, ExitReason.TARGET)
        self.assertFalse(pm.has_open_position)
        # P&L = (300 - 200) * 50 = 5000
        self.assertAlmostEqual(closed.pnl, 5000.0)

    def test_put_trade_pnl(self):
        pm = PositionManager()
        trade = pm.open_trade(
            "NIFTY", SignalType.SHORT, entry_price=150.0, quantity=50,
            stop_loss=105.0, target=240.0,
            option_type=OptionType.PUT, strike=22000,
        )
        self.assertEqual(trade.option_type, OptionType.PUT)
        self.assertEqual(trade.side, OrderSide.BUY)

        closed = pm.close_trade(100.0, ExitReason.STOP_LOSS)
        # P&L = (100 - 150) * 50 = -2500 (premium dropped)
        self.assertAlmostEqual(closed.pnl, -2500.0)

    def test_no_duplicate_positions(self):
        pm = PositionManager()
        pm.open_trade("NIFTY", SignalType.LONG, 200.0, 50, 140.0, 320.0, option_type=OptionType.CALL, strike=22000)
        with self.assertRaises(RuntimeError):
            pm.open_trade("NIFTY", SignalType.SHORT, 180.0, 50, 126.0, 288.0, option_type=OptionType.PUT, strike=22000)

    def test_sl_tp_check_premium_based(self):
        pm = PositionManager()
        pm.open_trade(
            "NIFTY", SignalType.LONG, entry_price=200.0, quantity=50,
            stop_loss=140.0, target=320.0,
            option_type=OptionType.CALL, strike=22000,
        )

        # Premium at 250 — no exit
        self.assertIsNone(pm.check_sl_tp(250.0))

        # Premium dropped to 130 — SL hit
        self.assertEqual(pm.check_sl_tp(130.0), ExitReason.STOP_LOSS)

        pm.close_trade(130.0, ExitReason.STOP_LOSS)

        pm.open_trade(
            "NIFTY", SignalType.LONG, entry_price=200.0, quantity=50,
            stop_loss=140.0, target=320.0,
            option_type=OptionType.CALL, strike=22000,
        )
        # Premium rose to 330 — TP hit
        self.assertEqual(pm.check_sl_tp(330.0), ExitReason.TARGET)


class TestRiskManager(unittest.TestCase):
    def test_max_trades_per_day(self):
        config = AppConfig.load()
        config.risk.max_trades_per_day = 2
        pm = PositionManager()
        rm = RiskManager(config, pm)

        for i in range(2):
            pm.open_trade("NIFTY", SignalType.LONG, 200.0, 50, 140.0, 320.0,
                          option_type=OptionType.CALL, strike=22000)
            pm.close_trade(250.0, ExitReason.TARGET)

        can, reason = rm.can_open_trade()
        self.assertFalse(can)
        self.assertIn("max_daily_trades", reason)

    def test_kill_switch(self):
        config = AppConfig.load()
        config.risk.max_loss_per_day = 100
        pm = PositionManager()
        rm = RiskManager(config, pm)

        pm.open_trade("NIFTY", SignalType.LONG, 200.0, 50, 140.0, 320.0,
                       option_type=OptionType.CALL, strike=22000)
        pm.close_trade(190.0, ExitReason.STOP_LOSS)  # PnL = -500

        can, reason = rm.can_open_trade()
        self.assertFalse(can)
        self.assertIn("max_daily_loss", reason)
        self.assertTrue(rm.is_kill_switch_active)


class TestContractSelector(unittest.TestCase):
    def test_atm_strike_selection(self):
        config = AppConfig.load()
        config.options.strike_selection = "atm"
        config.options.strike_interval = 50
        selector = ContractSelector(config)

        contract = selector.select_contract(SignalType.LONG, 22123.0)
        self.assertEqual(contract.option_type, OptionType.CALL)
        self.assertEqual(contract.strike, 22100.0)  # rounded to nearest 50

    def test_short_gives_put(self):
        config = AppConfig.load()
        selector = ContractSelector(config)

        contract = selector.select_contract(SignalType.SHORT, 22000.0)
        self.assertEqual(contract.option_type, OptionType.PUT)

    def test_otm_strike(self):
        config = AppConfig.load()
        config.options.strike_selection = "otm_1"
        config.options.strike_interval = 50
        selector = ContractSelector(config)

        # OTM CALL = strike ABOVE ATM
        contract = selector.select_contract(SignalType.LONG, 22100.0)
        self.assertEqual(contract.strike, 22150.0)

        # OTM PUT = strike BELOW ATM
        contract = selector.select_contract(SignalType.SHORT, 22100.0)
        self.assertEqual(contract.strike, 22050.0)


class TestOptionPremiumEstimate(unittest.TestCase):
    def test_atm_call_premium(self):
        premium = estimate_option_premium(22000, 22000, OptionType.CALL)
        self.assertGreater(premium, 0)

    def test_itm_greater_than_otm(self):
        itm = estimate_option_premium(22100, 22000, OptionType.CALL)
        otm = estimate_option_premium(21900, 22000, OptionType.CALL)
        self.assertGreater(itm, otm)

    def test_put_premium(self):
        premium = estimate_option_premium(22000, 22000, OptionType.PUT)
        self.assertGreater(premium, 0)


class TestEMAStrategy(unittest.TestCase):
    def test_compute_indicators(self):
        config = AppConfig.load()
        strategy = EMAStrategy(config)
        df = _make_candles(100, trend="up")
        result = strategy.compute_indicators(df)
        self.assertIn("ema_7", result.columns)
        self.assertIn("ema_9", result.columns)
        self.assertIn("ema_21", result.columns)

    def test_generates_signals(self):
        config = AppConfig.load()
        config.ema.use_crossover_confirmation = False
        config.sideways_filter.enabled = False
        strategy = EMAStrategy(config)

        df = _make_candles(200, trend="up")
        signal = strategy.generate_signal(df)
        self.assertIsNotNone(signal)
        self.assertIn(signal.type, [SignalType.LONG, SignalType.NO_SIGNAL])


class TestDhanTimestampConversion(unittest.TestCase):
    """Verify Dhan custom epoch (1 Jan 1980 00:00 UTC) conversion."""

    def test_daily_timestamp(self):
        from src.data.dhan_client import dhan_ts_to_datetime
        # From Dhan docs: TCS daily data starting 2022-01-08
        # First entry = 1326220200, expected Mon 2022-01-10 (midnight IST)
        dt = dhan_ts_to_datetime(1326220200)
        self.assertEqual(dt.date(), datetime(2022, 1, 10).date())
        self.assertEqual(dt.hour, 0)

    def test_intraday_timestamp(self):
        from src.data.dhan_client import dhan_ts_to_datetime
        # Intraday 9:15 candle
        dt = dhan_ts_to_datetime(1328845500)
        self.assertEqual(dt.date(), datetime(2022, 2, 9).date())
        self.assertEqual(dt.hour, 9)
        self.assertEqual(dt.minute, 15)

    def test_consecutive_daily(self):
        from src.data.dhan_client import dhan_ts_to_datetime
        dt1 = dhan_ts_to_datetime(1326220200)
        dt2 = dhan_ts_to_datetime(1326306600)
        delta = dt2 - dt1
        self.assertEqual(delta.total_seconds(), 86400)


if __name__ == "__main__":
    unittest.main()
