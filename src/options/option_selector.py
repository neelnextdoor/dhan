from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from src.core.config import AppConfig
from src.core.constants import OptionType, SignalType, StrikeSelection
from src.core.logger import get_logger
from src.options.oi_analyzer import OIAnalyzer

logger = get_logger("option_selector")


@dataclass
class OptionContract:
    security_id: str
    trading_symbol: str
    option_type: OptionType
    strike: float
    expiry: str
    lot_size: int
    ltp: float = 0.0
    underlying_price: float = 0.0
    oi: int = 0
    volume: int = 0
    iv: float = 0.0

    def display_name(self) -> str:
        ot = "CE" if self.option_type == OptionType.CALL else "PE"
        return f"{self.trading_symbol} {self.strike:.0f}{ot} {self.expiry}"


class OptionSelector:
    """
    Enhanced option contract selector with OI integration.

    Selects ATM/ITM/OTM strikes, validates against OI buildup,
    filters by premium range and liquidity.
    """

    def __init__(self, config: AppConfig, oi_analyzer: OIAnalyzer | None = None):
        self.config = config
        self.opts = config.options
        self.oi_analyzer = oi_analyzer
        self._strike_interval = self.opts.strike_interval

    def select_contract(
        self,
        signal_type: SignalType,
        underlying_price: float,
        option_chain: dict | None = None,
    ) -> OptionContract:
        opt_type = OptionType.CALL if signal_type == SignalType.LONG else OptionType.PUT
        strike = self._compute_strike(underlying_price, opt_type)

        if option_chain and option_chain.get("data"):
            if self.oi_analyzer:
                self.oi_analyzer.ingest_option_chain(option_chain, underlying_price)

            contract = self._pick_from_chain(option_chain, strike, opt_type, underlying_price)

            if not self._passes_premium_filter(contract.ltp):
                logger.warning(
                    "Premium %.2f outside [%.0f, %.0f] — searching for better strike",
                    contract.ltp, self.opts.min_premium, self.opts.max_premium,
                )
                alt = self._find_best_premium_contract(option_chain, opt_type, underlying_price)
                if alt:
                    contract = alt

            return contract

        return OptionContract(
            security_id="",
            trading_symbol=self.config.symbol,
            option_type=opt_type,
            strike=strike,
            expiry=self.config.expiry or "weekly",
            lot_size=self.config.risk.lot_size,
            underlying_price=underlying_price,
        )

    def should_avoid_entry(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now()
        if self.opts.avoid_last_hour_entry:
            cutoff = time(14, 30)
            if now.time() >= cutoff:
                return True, "theta_decay_last_hour"
        return False, ""

    def validate_with_oi(self, signal_type: SignalType,
                         security_id: str) -> tuple[bool, str]:
        if not self.oi_analyzer or not self.config.oi.enabled:
            return True, "oi_not_configured"
        return self.oi_analyzer.validate_trade(signal_type, security_id)

    def _passes_premium_filter(self, premium: float) -> bool:
        if premium <= 0:
            return True
        return self.opts.min_premium <= premium <= self.opts.max_premium

    def _compute_strike(self, price: float, opt_type: OptionType) -> float:
        interval = self._strike_interval
        selection = StrikeSelection(self.opts.strike_selection)

        if selection == StrikeSelection.FIXED:
            return self.opts.fixed_strike

        atm_strike = round(price / interval) * interval

        offset_steps = self.opts.strike_offset
        if selection == StrikeSelection.ATM:
            offset_steps = 0
        elif selection == StrikeSelection.ITM_1:
            offset_steps = 1
        elif selection == StrikeSelection.ITM_2:
            offset_steps = 2
        elif selection == StrikeSelection.OTM_1:
            offset_steps = -1
        elif selection == StrikeSelection.OTM_2:
            offset_steps = -2

        if opt_type == OptionType.CALL:
            return atm_strike - (offset_steps * interval)
        else:
            return atm_strike + (offset_steps * interval)

    def _pick_from_chain(
        self,
        chain: dict,
        target_strike: float,
        opt_type: OptionType,
        underlying_price: float,
    ) -> OptionContract:
        contracts = chain.get("data", [])
        if not contracts:
            return OptionContract(
                security_id="",
                trading_symbol=self.config.symbol,
                option_type=opt_type,
                strike=target_strike,
                expiry=self.config.expiry or "",
                lot_size=self.config.risk.lot_size,
                underlying_price=underlying_price,
            )

        opt_key = "CALL" if opt_type == OptionType.CALL else "PUT"
        best = None
        best_diff = float("inf")

        for entry in contracts:
            entry_type = str(entry.get("optionType") or entry.get("drvOptionType", "")).upper()
            if entry_type != opt_key:
                continue

            entry_strike = float(entry.get("strikePrice") or entry.get("drvStrikePrice", 0))
            entry_ltp = float(entry.get("ltp") or entry.get("last_price", 0))

            in_range = self._passes_premium_filter(entry_ltp) if entry_ltp > 0 else True
            diff = abs(entry_strike - target_strike)
            adjusted_diff = diff if in_range else diff + 10000

            if adjusted_diff < best_diff:
                best_diff = adjusted_diff
                best = entry

        if not best:
            return OptionContract(
                security_id="",
                trading_symbol=self.config.symbol,
                option_type=opt_type,
                strike=target_strike,
                expiry=self.config.expiry or "",
                lot_size=self.config.risk.lot_size,
                underlying_price=underlying_price,
            )

        return self._entry_to_contract(best, opt_type, target_strike, underlying_price)

    def _find_best_premium_contract(
        self, chain: dict, opt_type: OptionType, underlying_price: float,
    ) -> OptionContract | None:
        contracts = chain.get("data", [])
        opt_key = "CALL" if opt_type == OptionType.CALL else "PUT"
        best = None
        best_score = float("inf")

        mid_premium = (self.opts.min_premium + self.opts.max_premium) / 2

        for entry in contracts:
            entry_type = str(entry.get("optionType") or entry.get("drvOptionType", "")).upper()
            if entry_type != opt_key:
                continue

            ltp = float(entry.get("ltp") or entry.get("last_price", 0))
            if ltp <= 0 or not self._passes_premium_filter(ltp):
                continue

            score = abs(ltp - mid_premium)
            if score < best_score:
                best_score = score
                best = entry

        if best:
            atm = round(underlying_price / self._strike_interval) * self._strike_interval
            return self._entry_to_contract(best, opt_type, atm, underlying_price)
        return None

    def _entry_to_contract(self, entry: dict, opt_type: OptionType,
                           target_strike: float, underlying_price: float) -> OptionContract:
        sec_id = str(entry.get("securityId") or entry.get("security_id", ""))
        symbol = str(entry.get("tradingSymbol") or entry.get("trading_symbol", self.config.symbol))
        strike = float(entry.get("strikePrice") or entry.get("drvStrikePrice", target_strike))
        expiry = str(entry.get("expiryDate") or entry.get("drvExpiryDate", self.config.expiry or ""))
        ltp = float(entry.get("ltp") or entry.get("last_price", 0))
        oi = int(entry.get("openInterest") or entry.get("oi", 0))
        volume = int(entry.get("volume", 0))

        contract = OptionContract(
            security_id=sec_id,
            trading_symbol=symbol,
            option_type=opt_type,
            strike=strike,
            expiry=expiry,
            lot_size=self.config.risk.lot_size,
            ltp=ltp,
            underlying_price=underlying_price,
            oi=oi,
            volume=volume,
        )
        logger.info("Selected: %s (sec=%s, ltp=%.2f, oi=%d)",
                     contract.display_name(), sec_id, ltp, oi)
        return contract


def estimate_option_premium(
    underlying_price: float,
    strike: float,
    opt_type: OptionType,
    volatility_pct: float = 15.0,
) -> float:
    """Rough premium estimate for backtesting."""
    if opt_type == OptionType.CALL:
        intrinsic = max(underlying_price - strike, 0)
    else:
        intrinsic = max(strike - underlying_price, 0)

    otm_distance = abs(underlying_price - strike) / underlying_price
    time_value = underlying_price * (volatility_pct / 100) * 0.05 * math.exp(-otm_distance * 10)

    return max(intrinsic + time_value, time_value * 0.5)
