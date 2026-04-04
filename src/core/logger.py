from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style, init as colorama_init

from src.core.config import AppConfig

colorama_init(autoreset=True)

_CONFIGURED = False


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname:<8}{Style.RESET_ALL}"
        return super().format(record)


def setup_logging(config: AppConfig) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("dhan_algo")

    if _CONFIGURED:
        return logger

    logger.setLevel(getattr(logging, config.logging.level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if config.logging.console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(ColorFormatter(fmt, datefmt=datefmt))
        logger.addHandler(console)

    if config.logging.file:
        log_dir = Path(config.logging.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        file_handler = logging.FileHandler(log_dir / f"trading_{today}.log")
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        logger.addHandler(file_handler)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "dhan_algo") -> logging.Logger:
    return logging.getLogger("dhan_algo").getChild(name)
