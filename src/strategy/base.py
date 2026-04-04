from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.core.config import AppConfig
from src.strategy.signals import Signal


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all required indicator columns to the DataFrame."""
        ...

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Evaluate current market state and return a Signal."""
        ...

    @abstractmethod
    def compute_stop_loss(self, df: pd.DataFrame, signal: Signal) -> float:
        ...

    @abstractmethod
    def compute_target(self, df: pd.DataFrame, signal: Signal, stop_loss: float) -> float:
        ...
