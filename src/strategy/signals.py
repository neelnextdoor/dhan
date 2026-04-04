from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.core.constants import SignalType


@dataclass
class Signal:
    type: SignalType
    price: float
    timestamp: datetime
    stop_loss: float = 0.0
    target: float = 0.0
    reason: str = ""
    confidence: float = 0.0  # 0-1 scale

    @property
    def is_entry(self) -> bool:
        return self.type in (SignalType.LONG, SignalType.SHORT)

    @property
    def is_exit(self) -> bool:
        return self.type in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT)

    def __repr__(self) -> str:
        return (
            f"Signal({self.type.value} @ {self.price:.2f}, "
            f"SL={self.stop_loss:.2f}, TP={self.target:.2f}, "
            f"reason={self.reason})"
        )
