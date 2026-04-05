from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.core.constants import SignalType, TradeGrade


@dataclass
class Signal:
    type: SignalType
    price: float
    timestamp: datetime
    stop_loss: float = 0.0
    target: float = 0.0
    reason: str = ""
    confidence: float = 0.0
    grade: TradeGrade = TradeGrade.C
    score_breakdown: dict = field(default_factory=dict)
    htf_bias: Optional[str] = None  # "bullish", "bearish", or None

    @property
    def is_entry(self) -> bool:
        return self.type in (SignalType.LONG, SignalType.SHORT)

    @property
    def is_exit(self) -> bool:
        return self.type in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT)

    def passes_grade_filter(self, min_grade: TradeGrade = TradeGrade.A) -> bool:
        grade_rank = {TradeGrade.A_PLUS: 4, TradeGrade.A: 3, TradeGrade.B: 2, TradeGrade.C: 1}
        return grade_rank.get(self.grade, 0) >= grade_rank.get(min_grade, 0)

    def __repr__(self) -> str:
        return (
            f"Signal({self.type.value} @ {self.price:.2f}, "
            f"SL={self.stop_loss:.2f}, TP={self.target:.2f}, "
            f"grade={self.grade.value}, conf={self.confidence:.0%}, "
            f"reason={self.reason})"
        )
