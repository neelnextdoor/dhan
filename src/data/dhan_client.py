from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from dhanhq import dhanhq as DhanHQ

from src.core.config import AppConfig
from src.core.constants import TIMEFRAME_MAP
from src.core.logger import get_logger

logger = get_logger("dhan_client")

_RATE_LIMIT_DELAY = 0.35

_EXCHANGE_SEGMENT = {
    "NSE": DhanHQ.NSE,
    "BSE": DhanHQ.BSE,
    "NFO": DhanHQ.NSE_FNO,
    "NSE_FNO": DhanHQ.NSE_FNO,
    "MCX": DhanHQ.MCX,
    "IDX": "IDX_I",
    "IDX_I": "IDX_I",
}

# Dhan custom epoch: seconds from 1 Jan 1980 00:00:00 UTC
# (per JS converter in docs: base = new Date(1980, 0, 1, 5, 30, 0) in IST = midnight UTC)
_DHAN_EPOCH = datetime(1980, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


_IST = timezone(timedelta(hours=5, minutes=30))


def dhan_ts_to_datetime(ts: int) -> datetime:
    """Convert Dhan custom epoch timestamp (1980-based) to a naive IST datetime."""
    dt = _DHAN_EPOCH + timedelta(seconds=int(ts))
    return dt.astimezone(_IST).replace(tzinfo=None)


def _unix_ts_to_ist(ts: float) -> datetime:
    """Convert standard Unix timestamp to a naive IST datetime."""
    return datetime.fromtimestamp(float(ts), tz=_IST).replace(tzinfo=None)


class DhanClient:
    """Thin wrapper around the DhanHQ SDK with rate-limiting and error handling."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.dhan = DhanHQ(config.dhan_client_id, config.dhan_access_token)
        self._last_call_ts: float = 0.0
        logger.info("DhanHQ client initialized for %s", config.symbol)

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        if elapsed < _RATE_LIMIT_DELAY:
            time.sleep(_RATE_LIMIT_DELAY - elapsed)
        self._last_call_ts = time.time()

    def _get_exchange_segment(self) -> str:
        return _EXCHANGE_SEGMENT.get(self.config.exchange, DhanHQ.NSE)

    # ------------------------------------------------------------------
    # Historical daily candles (back to inception)
    # Endpoint: POST /charts/historical
    # ------------------------------------------------------------------
    def get_historical_daily(
        self,
        security_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        exchange_segment: str | None = None,
        instrument_type: str | None = None,
        expiry_code: int = 0,
    ) -> pd.DataFrame:
        """
        Fetch daily OHLCV candles.
        Dates are YYYY-MM-DD strings. to_date is non-inclusive per Dhan docs.
        expiry_code: 0=near, 1=next, 2=far, 3=very far (for derivatives).
        """
        sec_id = security_id or self.config.security_id
        exch = exchange_segment or self._get_exchange_segment()
        inst = instrument_type or self.config.instrument_type

        if to_date is None:
            to_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        self._throttle()
        logger.debug("Fetching daily historical: %s %s %s->%s", sec_id, exch, from_date, to_date)

        try:
            resp = self.dhan.historical_daily_data(
                security_id=sec_id,
                exchange_segment=exch,
                instrument_type=inst,
                from_date=from_date,
                to_date=to_date,
                expiry_code=expiry_code,
            )
            return self._parse_candle_response(resp)
        except Exception:
            logger.exception("Failed to fetch daily historical data")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Intraday minute candles (last 5 trading days)
    # Endpoint: POST /charts/intraday
    # ------------------------------------------------------------------
    def get_intraday_data(
        self,
        security_id: str | None = None,
        exchange_segment: str | None = None,
        instrument_type: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        interval: int | None = None,
    ) -> pd.DataFrame:
        """
        Fetch intraday minute candles (1m base, resampled to interval).
        interval: 1, 5, 15, 25, 60 (minutes). Defaults from config timeframe.
        from_date/to_date: YYYY-MM-DD — max 5 trading days range.
        """
        sec_id = security_id or self.config.security_id
        exch = exchange_segment or self._get_exchange_segment()
        inst = instrument_type or self.config.instrument_type

        if interval is None:
            interval = TIMEFRAME_MAP.get(self.config.timeframe, 5)
        if to_date is None:
            to_date = datetime.now().strftime("%Y-%m-%d")
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        self._throttle()
        logger.debug("Fetching intraday: %s %s interval=%dm %s->%s", sec_id, exch, interval, from_date, to_date)

        try:
            resp = self.dhan.intraday_minute_data(
                security_id=sec_id,
                exchange_segment=exch,
                instrument_type=inst,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
            )
            return self._parse_candle_response(resp)
        except Exception:
            logger.exception("Failed to fetch intraday data")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Convenience: get data based on config timeframe
    # ------------------------------------------------------------------
    def get_historical_data(
        self,
        security_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        exchange_segment: str | None = None,
        instrument_type: str | None = None,
    ) -> pd.DataFrame:
        """
        Smart fetch: uses intraday endpoint for minute timeframes (last 5 days),
        falls back to daily for longer ranges.
        """
        tf_minutes = TIMEFRAME_MAP.get(self.config.timeframe, 5)

        df = self.get_intraday_data(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
            from_date=from_date,
            to_date=to_date,
            interval=tf_minutes,
        )

        if not df.empty:
            return df

        logger.info("Intraday returned empty, falling back to daily historical")
        return self.get_historical_daily(
            security_id=security_id,
            from_date=from_date,
            to_date=to_date,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def place_order(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        product_type: str = "INTRADAY",
        tag: str = "",
    ) -> dict[str, Any]:
        self._throttle()
        logger.info("Placing order: %s %s qty=%d type=%s", transaction_type, security_id, quantity, order_type)

        txn = DhanHQ.BUY if transaction_type.upper() == "BUY" else DhanHQ.SELL
        o_type = getattr(DhanHQ, order_type.upper(), DhanHQ.MARKET)
        p_type = getattr(DhanHQ, product_type.upper(), DhanHQ.INTRA)

        try:
            resp = self.dhan.place_order(
                security_id=security_id,
                exchange_segment=exchange_segment,
                transaction_type=txn,
                quantity=quantity,
                order_type=o_type,
                product_type=p_type,
                price=price,
                tag=tag,
            )
            logger.info("Order response: %s", resp)
            return resp
        except Exception:
            logger.exception("Order placement failed")
            return {"status": "error", "remarks": "exception"}

    # ------------------------------------------------------------------
    # Option chain & expiry
    # ------------------------------------------------------------------
    def get_option_chain(
        self,
        underlying_security_id: str | None = None,
        exchange_segment: str | None = None,
        expiry: str = "",
    ) -> dict:
        sec_id = underlying_security_id or self.config.security_id
        exch = exchange_segment or self._get_exchange_segment()

        self._throttle()
        logger.debug("Fetching option chain for %s on %s", sec_id, exch)
        try:
            resp = self.dhan.option_chain(
                under_security_id=sec_id,
                under_exchange_segment=exch,
                expiry=expiry,
            )
            return resp if isinstance(resp, dict) else {"data": []}
        except Exception:
            logger.exception("Failed to fetch option chain")
            return {"data": []}

    def get_expiry_list(
        self,
        underlying_security_id: str | None = None,
        exchange_segment: str | None = None,
    ) -> list[str]:
        sec_id = underlying_security_id or self.config.security_id
        exch = exchange_segment or self._get_exchange_segment()

        self._throttle()
        try:
            resp = self.dhan.expiry_list(
                under_security_id=sec_id,
                under_exchange_segment=exch,
            )
            if isinstance(resp, dict):
                return resp.get("data", [])
            return []
        except Exception:
            logger.exception("Failed to fetch expiry list")
            return []

    # ------------------------------------------------------------------
    # Position & order management
    # ------------------------------------------------------------------
    def get_positions(self) -> list[dict]:
        self._throttle()
        try:
            resp = self.dhan.get_positions()
            return resp.get("data", []) if isinstance(resp, dict) else []
        except Exception:
            logger.exception("Failed to fetch positions")
            return []

    def get_order_list(self) -> list[dict]:
        self._throttle()
        try:
            resp = self.dhan.get_order_list()
            return resp.get("data", []) if isinstance(resp, dict) else []
        except Exception:
            logger.exception("Failed to fetch orders")
            return []

    def cancel_order(self, order_id: str) -> dict:
        self._throttle()
        try:
            return self.dhan.cancel_order(order_id)
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return {"status": "error"}

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_candle_response(resp: dict) -> pd.DataFrame:
        if not resp:
            logger.warning("Empty API response")
            return pd.DataFrame()

        status = resp.get("status", "")
        if status == "failure":
            logger.warning("API failure: %s", resp.get("remarks", ""))
            return pd.DataFrame()

        data = resp.get("data", resp)
        if isinstance(data, dict):
            # API may return either key depending on version:
            #   "timestamp"  — standard Unix epoch (current API)
            #   "start_Time" — Dhan custom epoch from 1980-01-01 UTC (older docs)
            use_dhan_epoch = False
            raw_ts = data.get("timestamp") or []
            if not raw_ts and "start_Time" in data:
                raw_ts = data["start_Time"]
                use_dhan_epoch = True

            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            volumes = data.get("volume", [])

            if not opens:
                logger.warning("No price data in response")
                return pd.DataFrame()

            if raw_ts:
                timestamps = (
                    [dhan_ts_to_datetime(ts) for ts in raw_ts]
                    if use_dhan_epoch
                    else [_unix_ts_to_ist(ts) for ts in raw_ts]
                )
            else:
                logger.warning("No timestamps in response; generating synthetic index")
                timestamps = pd.date_range(end=datetime.now(), periods=len(opens), freq="D")

            df = pd.DataFrame({
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }, index=pd.DatetimeIndex(timestamps, name="timestamp"))

        elif isinstance(data, list):
            df = pd.DataFrame(data)
            if "start_Time" in df.columns:
                df["timestamp"] = df["start_Time"].apply(dhan_ts_to_datetime)
                df.set_index("timestamp", inplace=True)
                df.drop(columns=["start_Time"], errors="ignore", inplace=True)
            elif "timestamp" in df.columns:
                df["timestamp"] = df["timestamp"].apply(_unix_ts_to_ist)
                df.set_index("timestamp", inplace=True)
        else:
            return pd.DataFrame()

        if df.empty:
            return df

        df.sort_index(inplace=True)

        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.debug("Parsed %d candles (%s to %s)", len(df), df.index[0], df.index[-1])
        return df
