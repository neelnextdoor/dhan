"""Backwards-compatible alias — imports redirect to data_handler."""
from src.data.data_handler import DataHandler as MarketDataManager

__all__ = ["MarketDataManager"]
