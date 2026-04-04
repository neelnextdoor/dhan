#!/usr/bin/env python3
"""
Dhan Algo Trading — Live / Paper Trading Runner
Usage: python run_live.py [--config path/to/config.yaml] [--mode live|paper]
"""
from __future__ import annotations

import argparse
import os

from src.core.config import AppConfig
from src.core.logger import setup_logging, get_logger
from src.live.engine import LiveEngine
from src.strategy.ema_strategy import EMAStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EMA strategy live/paper trading")
    parser.add_argument("--config", default=None, help="Path to YAML config file")
    parser.add_argument("--mode", choices=["live", "paper"], default=None,
                        help="Override trading mode (default: from .env)")
    args = parser.parse_args()

    config = AppConfig.load(args.config)

    if args.mode:
        config.trading_mode = args.mode
        os.environ["TRADING_MODE"] = args.mode

    setup_logging(config)
    logger = get_logger("main")

    if config.trading_mode == "live":
        if not config.dhan_client_id or not config.dhan_access_token:
            logger.error("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be set in .env for live trading")
            return
        logger.warning("=" * 50)
        logger.warning("  LIVE TRADING MODE — REAL MONEY AT RISK")
        logger.warning("=" * 50)
    else:
        logger.info("=" * 50)
        logger.info("  PAPER TRADING MODE")
        logger.info("=" * 50)

    strategy = EMAStrategy(config)
    engine = LiveEngine(config, strategy)
    engine.start()


if __name__ == "__main__":
    main()
