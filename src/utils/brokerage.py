from __future__ import annotations

from dataclasses import dataclass

from src.core.config import BrokerageConfig


@dataclass
class TradeCosts:
    """Breakdown of all costs for a single leg (entry or exit)."""
    brokerage: float = 0.0
    stt: float = 0.0
    exchange_txn: float = 0.0
    gst: float = 0.0
    sebi: float = 0.0
    stamp_duty: float = 0.0

    @property
    def total(self) -> float:
        return (self.brokerage + self.stt + self.exchange_txn +
                self.gst + self.sebi + self.stamp_duty)


def compute_option_buy_costs(
    premium: float,
    quantity: int,
    config: BrokerageConfig,
) -> TradeCosts:
    """
    Calculate costs for BUYING an option.
    STT on buy side: 0 (STT only on sell for options in India since Oct 2023).
    """
    if not config.enabled:
        return TradeCosts()

    turnover = premium * quantity
    brokerage = min(config.brokerage_per_order, turnover * 0.01)
    exchange_txn = turnover * (config.exchange_txn_pct / 100)
    gst = (brokerage + exchange_txn) * (config.gst_pct / 100)
    sebi = turnover * config.sebi_per_crore / 1e7
    stamp_duty = turnover * (config.stamp_duty_pct / 100)

    return TradeCosts(
        brokerage=brokerage,
        stt=0.0,
        exchange_txn=exchange_txn,
        gst=gst,
        sebi=sebi,
        stamp_duty=stamp_duty,
    )


def compute_option_sell_costs(
    premium: float,
    quantity: int,
    config: BrokerageConfig,
) -> TradeCosts:
    """
    Calculate costs for SELLING an option.
    STT on sell side for options = 0.0625% of (premium * quantity).
    """
    if not config.enabled:
        return TradeCosts()

    turnover = premium * quantity
    brokerage = min(config.brokerage_per_order, turnover * 0.01)
    stt = turnover * (config.stt_pct / 100)
    exchange_txn = turnover * (config.exchange_txn_pct / 100)
    gst = (brokerage + exchange_txn) * (config.gst_pct / 100)
    sebi = turnover * config.sebi_per_crore / 1e7
    stamp_duty = 0.0

    return TradeCosts(
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        gst=gst,
        sebi=sebi,
        stamp_duty=stamp_duty,
    )


def compute_round_trip_costs(
    entry_premium: float,
    exit_premium: float,
    quantity: int,
    config: BrokerageConfig,
) -> float:
    """Total cost for a full buy→sell option trade."""
    buy = compute_option_buy_costs(entry_premium, quantity, config)
    sell = compute_option_sell_costs(exit_premium, quantity, config)
    return buy.total + sell.total
