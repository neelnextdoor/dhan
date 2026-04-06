from __future__ import annotations

import time as _time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.core.config import AppConfig
from src.core.logger import get_logger

logger = get_logger("dhan_client")

DHAN_EPOCH_OFFSET = 315532800
IST_OFFSET = 19800


def dhan_ts_to_datetime(ts: int) -> datetime:
    """Convert Dhan custom epoch (1 Jan 1980 00:00 UTC) to IST datetime."""
    unix_ts = ts + DHAN_EPOCH_OFFSET
    return datetime.utcfromtimestamp(unix_ts + IST_OFFSET)


class DhanClient:
    """Wrapper around the dhanhq SDK with rate-limiting and parsing helpers."""

    _MIN_REQUEST_INTERVAL = 0.35

    def __init__(self, config: AppConfig):
        self.config = config
        self._last_request_time = 0.0

        from dhanhq import dhanhq as DhanHQ
        self._dhan = DhanHQ(config.dhan_client_id, config.dhan_access_token)
        self._DhanHQ = DhanHQ
        logger.info("DhanClient initialised (client_id=%s)", config.dhan_client_id[:6] + "***")

    def _rate_limit(self) -> None:
        elapsed = _time.time() - self._last_request_time
        if elapsed < self._MIN_REQUEST_INTERVAL:
            _time.sleep(self._MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = _time.time()

    def _get_exchange_segment(self) -> str:
        mapping = {
            "NSE": self._DhanHQ.NSE,
            "BSE": self._DhanHQ.BSE,
            "NSE_FNO": self._DhanHQ.NSE_FNO,
            "NFO": self._DhanHQ.NSE_FNO,
            "MCX": self._DhanHQ.MCX,
            "IDX_I": self._DhanHQ.INDEX,
            "IDX": self._DhanHQ.INDEX,
        }
        return mapping.get(self.config.exchange, self._DhanHQ.NSE)

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------
    def get_historical_data(self, from_date: str = "", to_date: str = "") -> pd.DataFrame:
        self._rate_limit()
        from_date = from_date or self.config.backtest.start_date
        to_date = to_date or self.config.backtest.end_date
        try:
            resp = self._dhan.historical_minute_charts(
                security_id=self.config.security_id,
                exchange_segment=self._get_exchange_segment(),
                instrument_type=self.config.instrument_type,
                from_date=from_date,
                to_date=to_date,
            )
            return self._parse_candle_response(resp)
        except AttributeError:
            return self.get_intraday_data(from_date=from_date, to_date=to_date)

    def get_historical_daily(self, from_date: str = "", to_date: str = "") -> pd.DataFrame:
        self._rate_limit()
        from_date = from_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        to_date = to_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            resp = self._dhan.historical_daily_charts(
                security_id=self.config.security_id,
                exchange_segment=self._get_exchange_segment(),
                instrument_type=self.config.instrument_type,
                from_date=from_date,
                to_date=to_date,
            )
            return self._parse_candle_response(resp)
        except Exception:
            logger.exception("Failed to fetch daily data")
            return pd.DataFrame()

    def get_intraday_data(self, from_date: str = "", to_date: str = "",
                          interval: int = 5) -> pd.DataFrame:
        self._rate_limit()
        from_date = from_date or (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        to_date = to_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            resp = self._dhan.intraday_minute_data(
                security_id=self.config.security_id,
                exchange_segment=self._get_exchange_segment(),
                instrument_type=self.config.instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
            )
            return self._parse_candle_response(resp)
        except Exception:
            logger.exception("Failed to fetch intraday data")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Option chain & expiry
    # ------------------------------------------------------------------
    def get_option_chain(self, underlying_security_id: str = "",
                         expiry: str = "") -> dict:
        self._rate_limit()
        sec_id = underlying_security_id or self.config.security_id
        try:
            resp = self._dhan.option_chain(
                under_security_id=int(sec_id),
                expiry=expiry or "",
            )
            if isinstance(resp, dict) and resp.get("status") == "success":
                return resp
            return resp if isinstance(resp, dict) else {"data": []}
        except Exception:
            logger.exception("Failed to fetch option chain")
            return {"data": []}

    def get_expiry_list(self, underlying_security_id: str = "") -> list[str]:
        self._rate_limit()
        sec_id = underlying_security_id or self.config.security_id
        try:
            resp = self._dhan.expiry_list(under_security_id=int(sec_id))
            if isinstance(resp, dict):
                return resp.get("data", [])
            return []
        except Exception:
            logger.exception("Failed to fetch expiry list")
            return []

    # ------------------------------------------------------------------
    # OI data
    # ------------------------------------------------------------------
    def get_oi_data(self, security_id: str = "") -> dict:
        """Fetch current OI snapshot for a security (option contract)."""
        self._rate_limit()
        sec_id = security_id or self.config.security_id
        try:
            resp = self._dhan.market_quote(
                security_id=sec_id,
                exchange_segment=self._DhanHQ.NSE_FNO,
            )
            return resp if isinstance(resp, dict) else {}
        except Exception:
            logger.exception("Failed to fetch OI data for %s", sec_id)
            return {}

    # ------------------------------------------------------------------
    # Market quotes / LTP
    # ------------------------------------------------------------------
    def get_ltp(self, security_id: str, exchange_segment: str = "") -> float:
        """Fetch real-time LTP for a single security."""
        self._rate_limit()
        seg = exchange_segment or self._get_exchange_segment()
        try:
            resp = self._dhan.get_ltp(
                security_id=security_id,
                exchange_segment=seg,
            )
            if isinstance(resp, dict):
                data = resp.get("data", resp)
                ltp = float(
                    data.get("lastPrice", 0)
                    or data.get("last_price", 0)
                    or data.get("LTP", 0)
                    or data.get("ltp", 0)
                )
                if ltp > 0:
                    return ltp
        except AttributeError:
            try:
                resp = self._dhan.get_market_quote(security_id, seg)
                if isinstance(resp, dict):
                    data = resp.get("data", resp)
                    ltp = float(data.get("last_price", 0) or data.get("LTP", 0) or data.get("ltp", 0))
                    if ltp > 0:
                        return ltp
            except Exception:
                pass
        except Exception:
            logger.debug("Failed to fetch LTP for %s", security_id, exc_info=True)
        return 0.0

    def get_option_ltp(self, security_id: str) -> float:
        """Convenience wrapper for option LTP."""
        return self.get_ltp(security_id, self._DhanHQ.NSE_FNO)

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------
    def place_order(self, security_id: str, exchange_segment: str,
                    transaction_type: str, quantity: int,
                    order_type: str = "MARKET", product_type: str = "INTRADAY",
                    price: float = 0.0, trigger_price: float = 0.0,
                    tag: str = "") -> dict[str, Any]:
        self._rate_limit()
        try:
            resp = self._dhan.place_order(
                security_id=security_id,
                exchange_segment=exchange_segment,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product_type=product_type,
                price=price,
                trigger_price=trigger_price,
                tag=tag,
            )
            logger.info("Order placed: %s %s qty=%d -> %s",
                        transaction_type, security_id, quantity, resp)
            if isinstance(resp, dict) and resp.get("orderId"):
                resp["status"] = "success"
            return resp if isinstance(resp, dict) else {"status": "error", "raw": str(resp)}
        except Exception:
            logger.exception("Order placement failed")
            return {"status": "error", "remarks": "exception"}

    def get_positions(self) -> list[dict]:
        self._rate_limit()
        try:
            resp = self._dhan.get_positions()
            if isinstance(resp, dict):
                return resp.get("data", [])
            return []
        except Exception:
            logger.exception("Failed to fetch positions")
            return []

    def get_order_list(self) -> list[dict]:
        self._rate_limit()
        try:
            resp = self._dhan.get_order_list()
            if isinstance(resp, dict):
                return resp.get("data", [])
            return []
        except Exception:
            logger.exception("Failed to fetch orders")
            return []

    def cancel_order(self, order_id: str) -> dict:
        self._rate_limit()
        try:
            resp = self._dhan.cancel_order(order_id=order_id)
            return resp if isinstance(resp, dict) else {"status": "error"}
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return {"status": "error"}

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_candle_response(self, resp: Any) -> pd.DataFrame:
        if not resp or not isinstance(resp, dict):
            return pd.DataFrame()

        data = resp.get("data", resp)
        if not isinstance(data, dict):
            return pd.DataFrame()

        timestamps = data.get("start_Time") or data.get("timestamp") or []
        opens = data.get("open") or []
        highs = data.get("high") or []
        lows = data.get("low") or []
        closes = data.get("close") or []
        volumes = data.get("volume") or []

        if not timestamps:
            return pd.DataFrame()

        dt_index = []
        for ts in timestamps:
            if isinstance(ts, (int, float)):
                dt_index.append(dhan_ts_to_datetime(int(ts)))
            elif isinstance(ts, str):
                try:
                    dt_index.append(datetime.fromisoformat(ts))
                except ValueError:
                    dt_index.append(datetime.now())
            else:
                dt_index.append(datetime.now())

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes if volumes else [0] * len(opens),
        }, index=pd.DatetimeIndex(dt_index, name="timestamp"))

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.sort_index(inplace=True)
        df.dropna(subset=["close"], inplace=True)
        return df
