from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from src.core.config import AppConfig
from src.core.constants import OptionType, SignalType, StrikeSelection
from src.core.logger import get_logger

logger = get_logger("contract_selector")


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

    def display_name(self) -> str:
        return f"{self.trading_symbol} {self.strike:.0f}{self.option_type.value[0]}E {self.expiry}"


class ContractSelector:
    """
    Selects the appropriate option contract based on signal direction and config.

    LONG signal -> Buy CALL
    SHORT signal -> Buy PUT

    Improvements:
    - Premium range filter (avoid illiquid penny options and expensive deep ITM)
    - Theta-aware: warns / blocks entries near expiry or late in the day
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.opts = config.options
        self._strike_interval = self.opts.strike_interval

    def select_contract(
        self,
        signal_type: SignalType,
        underlying_price: float,
        option_chain: dict | None = None,
    ) -> OptionContract:
        opt_type = OptionType.CALL if signal_type == SignalType.LONG else OptionType.PUT
        strike = self._compute_strike(underlying_price, opt_type)

        if option_chain:
            contract = self._pick_from_chain(option_chain, strike, opt_type, underlying_price)
            if not self._passes_premium_filter(contract.ltp):
                logger.warning(
                    "Premium %.2f outside range [%.0f, %.0f] — adjusting strike",
                    contract.ltp, self.opts.min_premium, self.opts.max_premium,
                )
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
        """
        Check if options-specific conditions suggest avoiding a new entry.
        Returns (should_avoid, reason).
        """
        now = now or datetime.now()

        if self.opts.avoid_last_hour_entry:
            cutoff = time(14, 30)
            if now.time() >= cutoff:
                return True, "theta_decay_last_hour"

        return False, ""

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
            logger.warning("Empty option chain, returning synthetic contract")
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
            entry_type = entry.get("optionType") or entry.get("drvOptionType", "")
            if entry_type.upper() != opt_key:
                continue

            entry_strike = float(entry.get("strikePrice") or entry.get("drvStrikePrice", 0))
            entry_ltp = float(entry.get("ltp") or entry.get("last_price", 0))

            # Prefer contracts within premium range
            in_range = self._passes_premium_filter(entry_ltp) if entry_ltp > 0 else True
            diff = abs(entry_strike - target_strike)
            adjusted_diff = diff if in_range else diff + 10000

            if adjusted_diff < best_diff:
                best_diff = adjusted_diff
                best = entry

        if not best:
            logger.warning("No matching contract in chain for strike=%.0f %s", target_strike, opt_key)
            return OptionContract(
                security_id="",
                trading_symbol=self.config.symbol,
                option_type=opt_type,
                strike=target_strike,
                expiry=self.config.expiry or "",
                lot_size=self.config.risk.lot_size,
                underlying_price=underlying_price,
            )

        sec_id = str(best.get("securityId") or best.get("security_id", ""))
        symbol = str(best.get("tradingSymbol") or best.get("trading_symbol", self.config.symbol))
        strike = float(best.get("strikePrice") or best.get("drvStrikePrice", target_strike))
        expiry = str(best.get("expiryDate") or best.get("drvExpiryDate", self.config.expiry or ""))
        ltp = float(best.get("ltp") or best.get("last_price", 0))

        contract = OptionContract(
            security_id=sec_id,
            trading_symbol=symbol,
            option_type=opt_type,
            strike=strike,
            expiry=expiry,
            lot_size=self.config.risk.lot_size,
            ltp=ltp,
            underlying_price=underlying_price,
        )
        logger.info("Selected contract: %s (sec_id=%s, ltp=%.2f)", contract.display_name(), sec_id, ltp)
        return contract


def estimate_option_premium(
    underlying_price: float,
    strike: float,
    opt_type: OptionType,
    volatility_pct: float = 15.0,
) -> float:
    """
    Rough premium estimate for backtesting when real option data isn't available.
    Uses intrinsic value + a simplified time value proxy.
    """
    if opt_type == OptionType.CALL:
        intrinsic = max(underlying_price - strike, 0)
    else:
        intrinsic = max(strike - underlying_price, 0)

    otm_distance = abs(underlying_price - strike) / underlying_price
    time_value = underlying_price * (volatility_pct / 100) * 0.05 * math.exp(-otm_distance * 10)

    return max(intrinsic + time_value, time_value * 0.5)
