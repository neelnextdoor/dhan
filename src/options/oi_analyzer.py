from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from src.core.config import AppConfig
from src.core.constants import OISignal, SignalType
from src.core.logger import get_logger

logger = get_logger("oi_analyzer")


@dataclass
class OISnapshot:
    timestamp: datetime
    security_id: str
    oi: int
    price: float
    volume: int = 0


@dataclass
class OIAnalysis:
    signal: OISignal
    oi_change_pct: float
    price_change_pct: float
    current_oi: int
    previous_oi: int
    is_valid_for_ce: bool = False
    is_valid_for_pe: bool = False
    reason: str = ""


class OIAnalyzer:
    """
    Analyzes Open Interest data to confirm option trade direction.

    OI Logic:
      CE BUY valid when: Price ↑ and OI ↑ → Long Buildup
      PE BUY valid when: Price ↓ and OI ↑ → Short Buildup

    Rejects trades when:
      - OI is decreasing (short covering / long unwinding)
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.oi_config = config.oi
        self._history: dict[str, list[OISnapshot]] = {}
        self._max_history = 50

    def record_snapshot(self, security_id: str, oi: int, price: float,
                        volume: int = 0, timestamp: datetime | None = None) -> None:
        ts = timestamp or datetime.now()
        snap = OISnapshot(timestamp=ts, security_id=security_id,
                          oi=oi, price=price, volume=volume)
        if security_id not in self._history:
            self._history[security_id] = []
        self._history[security_id].append(snap)
        if len(self._history[security_id]) > self._max_history:
            self._history[security_id] = self._history[security_id][-self._max_history:]

    def analyze(self, security_id: str) -> OIAnalysis:
        """Analyze OI buildup/unwinding for a given security."""
        history = self._history.get(security_id, [])
        lookback = self.oi_config.lookback_periods

        if len(history) < 2:
            return OIAnalysis(
                signal=OISignal.NEUTRAL,
                oi_change_pct=0.0,
                price_change_pct=0.0,
                current_oi=history[-1].oi if history else 0,
                previous_oi=0,
                reason="insufficient_data",
            )

        current = history[-1]
        ref_idx = max(0, len(history) - lookback - 1)
        reference = history[ref_idx]

        if reference.oi == 0:
            return OIAnalysis(
                signal=OISignal.NEUTRAL,
                oi_change_pct=0.0,
                price_change_pct=0.0,
                current_oi=current.oi,
                previous_oi=reference.oi,
                reason="zero_reference_oi",
            )

        oi_change_pct = ((current.oi - reference.oi) / reference.oi) * 100
        price_change_pct = 0.0
        if reference.price > 0:
            price_change_pct = ((current.price - reference.price) / reference.price) * 100

        oi_increasing = oi_change_pct >= self.oi_config.min_oi_change_pct
        oi_decreasing = oi_change_pct <= -self.oi_config.min_oi_change_pct
        price_up = price_change_pct > 0
        price_down = price_change_pct < 0

        if price_up and oi_increasing:
            signal = OISignal.LONG_BUILDUP
        elif price_down and oi_increasing:
            signal = OISignal.SHORT_BUILDUP
        elif price_up and oi_decreasing:
            signal = OISignal.SHORT_COVERING
        elif price_down and oi_decreasing:
            signal = OISignal.LONG_UNWINDING
        else:
            signal = OISignal.NEUTRAL

        is_valid_ce = signal == OISignal.LONG_BUILDUP
        is_valid_pe = signal == OISignal.SHORT_BUILDUP

        return OIAnalysis(
            signal=signal,
            oi_change_pct=round(oi_change_pct, 2),
            price_change_pct=round(price_change_pct, 2),
            current_oi=current.oi,
            previous_oi=reference.oi,
            is_valid_for_ce=is_valid_ce,
            is_valid_for_pe=is_valid_pe,
            reason=signal.value.lower(),
        )

    def validate_trade(self, signal_type: SignalType,
                       security_id: str) -> tuple[bool, str]:
        """
        Check if OI conditions support the proposed trade direction.
        Returns (is_valid, reason).
        """
        if not self.oi_config.enabled:
            return True, "oi_disabled"

        analysis = self.analyze(security_id)

        if analysis.signal == OISignal.NEUTRAL:
            if analysis.reason == "insufficient_data":
                return True, "oi_data_insufficient"
            return True, "oi_neutral"

        if signal_type == SignalType.LONG:
            if analysis.is_valid_for_ce:
                logger.info("OI confirms CE: %s (OI %+.1f%%, Price %+.1f%%)",
                            analysis.signal.value, analysis.oi_change_pct,
                            analysis.price_change_pct)
                return True, f"oi_confirmed_{analysis.signal.value}"

            if self.oi_config.reject_unwinding:
                if analysis.signal in (OISignal.LONG_UNWINDING, OISignal.SHORT_COVERING):
                    logger.info("OI rejects CE: %s", analysis.signal.value)
                    return False, f"oi_rejected_{analysis.signal.value}"

            return True, f"oi_weak_{analysis.signal.value}"

        if signal_type == SignalType.SHORT:
            if analysis.is_valid_for_pe:
                logger.info("OI confirms PE: %s (OI %+.1f%%, Price %+.1f%%)",
                            analysis.signal.value, analysis.oi_change_pct,
                            analysis.price_change_pct)
                return True, f"oi_confirmed_{analysis.signal.value}"

            if self.oi_config.reject_unwinding:
                if analysis.signal in (OISignal.LONG_UNWINDING, OISignal.SHORT_COVERING):
                    logger.info("OI rejects PE: %s", analysis.signal.value)
                    return False, f"oi_rejected_{analysis.signal.value}"

            return True, f"oi_weak_{analysis.signal.value}"

        return True, "unknown_signal"

    def ingest_option_chain(self, chain_data: dict, underlying_price: float) -> None:
        """
        Parse a Dhan option chain response and record OI snapshots
        for all strikes.
        """
        contracts = chain_data.get("data", [])
        now = datetime.now()

        for c in contracts:
            sec_id = str(c.get("securityId") or c.get("security_id", ""))
            oi = int(c.get("openInterest") or c.get("oi", 0))
            ltp = float(c.get("ltp") or c.get("last_price", 0))
            vol = int(c.get("volume", 0))

            if sec_id and oi > 0:
                self.record_snapshot(sec_id, oi, ltp, vol, now)

    def get_pcr(self, chain_data: dict) -> float:
        """Compute Put-Call Ratio from option chain OI."""
        contracts = chain_data.get("data", [])
        total_call_oi = 0
        total_put_oi = 0

        for c in contracts:
            opt_type = str(c.get("optionType") or c.get("drvOptionType", "")).upper()
            oi = int(c.get("openInterest") or c.get("oi", 0))
            if opt_type == "CALL":
                total_call_oi += oi
            elif opt_type == "PUT":
                total_put_oi += oi

        if total_call_oi == 0:
            return 0.0
        return total_put_oi / total_call_oi

    def clear_history(self, security_id: str | None = None) -> None:
        if security_id:
            self._history.pop(security_id, None)
        else:
            self._history.clear()
