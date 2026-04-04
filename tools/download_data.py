#!/usr/bin/env python3
"""
Download historical data from Dhan API.

Usage:
  # NIFTY daily (last 1 year)
  python tools/download_data.py

  # BANKNIFTY daily (last 6 months)
  python tools/download_data.py --symbol BANKNIFTY --security-id 25 --exchange IDX_I --days 180

  # SENSEX daily
  python tools/download_data.py --symbol SENSEX --security-id 1 --exchange IDX_I --instrument INDEX

  # NIFTY intraday 5m (last 5 trading days)
  python tools/download_data.py --intraday --interval 5

  # RELIANCE equity daily
  python tools/download_data.py --symbol RELIANCE --security-id 2885 --exchange NSE --instrument EQUITY

Common security IDs:
  NIFTY 50     = 13    (IDX_I, INDEX)
  BANKNIFTY    = 25    (IDX_I, INDEX)
  SENSEX       = 1     (IDX_I, INDEX)
  FINNIFTY     = 27    (IDX_I, INDEX)
  RELIANCE     = 2885  (NSE,   EQUITY)
  TCS          = 11536 (NSE,   EQUITY)
  HDFCBANK     = 1333  (NSE,   EQUITY)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import AppConfig
from src.data.dhan_client import DhanClient

_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NSE_FNO",
    "NSE_FNO": "NSE_FNO",
    "IDX": "IDX_I",
    "IDX_I": "IDX_I",
    "MCX": "MCX",
}


def main():
    parser = argparse.ArgumentParser(
        description="Download historical OHLCV data from Dhan API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol", default=None, help="Symbol name (default: from config)")
    parser.add_argument("--security-id", default=None, help="Dhan security ID")
    parser.add_argument("--exchange", default=None, help="Exchange segment: NSE, BSE, IDX_I, NFO, MCX")
    parser.add_argument("--instrument", default=None, help="Instrument type: INDEX, EQUITY, FUTIDX, etc.")
    parser.add_argument("--from-date", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to-date", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=365, help="Days of history (if --from-date not set)")
    parser.add_argument("--intraday", action="store_true", help="Fetch intraday minute data (max 5 days)")
    parser.add_argument("--interval", type=int, default=5, choices=[1, 5, 15, 25, 60],
                        help="Candle interval in minutes (for --intraday)")
    parser.add_argument("--output", default=None, help="Output CSV path (auto-generated if not set)")
    args = parser.parse_args()

    config = AppConfig.load()

    if args.security_id:
        config.security_id = args.security_id
    if args.exchange:
        config.exchange = _EXCHANGE_MAP.get(args.exchange.upper(), args.exchange)
    if args.instrument:
        config.instrument_type = args.instrument.upper()
    if args.symbol:
        config.symbol = args.symbol

    symbol = config.symbol
    client = DhanClient(config)

    to_date = args.to_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    if args.intraday:
        from_date = args.from_date or (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        print(f"Fetching intraday {args.interval}m data for {symbol} ({from_date} to {to_date})...")
        df = client.get_intraday_data(
            from_date=from_date,
            to_date=to_date,
            interval=args.interval,
        )
        suffix = f"intraday_{args.interval}m"
    else:
        from_date = args.from_date or (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        print(f"Fetching daily data for {symbol} ({from_date} to {to_date})...")
        df = client.get_historical_daily(
            from_date=from_date,
            to_date=to_date,
        )
        suffix = "daily"

    if df.empty:
        print("ERROR: No data returned. Check security ID, exchange, and API subscription.")
        sys.exit(1)

    output = args.output or f"data/{symbol.lower()}_{suffix}.csv"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output)

    print(f"Saved {len(df)} candles -> {output}")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    print(f"Price range: {df['low'].min():.2f} - {df['high'].max():.2f}")


if __name__ == "__main__":
    main()
