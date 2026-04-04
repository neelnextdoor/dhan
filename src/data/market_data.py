from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import TIMEFRAME_MAP
from src.core.logger import get_logger
from src.data.dhan_client import DhanClient

logger = get_logger("market_data")


class MarketDataManager:
    """Manages candle data: fetches, resamples, and maintains a rolling window."""

    def __init__(self, config: AppConfig, client: DhanClient):
        self.config = config
        self.client = client
        self.candles: pd.DataFrame = pd.DataFrame()
        self._tf_minutes = TIMEFRAME_MAP.get(config.timeframe, 5)

    def initialize(self) -> pd.DataFrame:
        logger.info("Initializing market data for %s (%s)", self.config.symbol, self.config.timeframe)
        raw = self.client.get_historical_data()
        if raw.empty:
            logger.warning("No historical data returned — trying intraday endpoint")
            raw = self.client.get_intraday_data()

        if raw.empty:
            logger.error("Could not load any candle data")
            return self.candles

        self.candles = self._resample(raw)
        logger.info("Loaded %d candles", len(self.candles))
        return self.candles

    def update(self) -> pd.DataFrame:
        """Fetch latest intraday data and merge with existing candles."""
        raw = self.client.get_intraday_data()
        if raw.empty:
            return self.candles

        new = self._resample(raw)
        if new.empty:
            return self.candles

        if self.candles.empty:
            self.candles = new
        else:
            combined = pd.concat([self.candles, new])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            tail = max(self.config.lookback_candles, 500)
            self.candles = combined.tail(tail)

        return self.candles

    def get_latest_candle(self) -> pd.Series | None:
        if self.candles.empty:
            return None
        return self.candles.iloc[-1]

    def get_previous_candle(self) -> pd.Series | None:
        if len(self.candles) < 2:
            return None
        return self.candles.iloc[-2]

    def is_candle_closed(self) -> bool:
        """Heuristic: the latest candle is considered closed if the next candle period has begun."""
        if self.candles.empty:
            return False
        last_ts = self.candles.index[-1]
        now = datetime.now()
        expected_next = last_ts + pd.Timedelta(minutes=self._tf_minutes)
        return now >= expected_next

    def _resample(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        if self._tf_minutes <= 1:
            return df

        rule = f"{self._tf_minutes}min"
        resampled = df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open"])
        return resampled
