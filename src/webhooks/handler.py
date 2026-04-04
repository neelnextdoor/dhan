from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from src.core.logger import get_logger

logger = get_logger("webhook_handler")


class OrderStatus(str, Enum):
    TRANSIT = "TRANSIT"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TRADED = "TRADED"
    EXPIRED = "EXPIRED"


@dataclass
class OrderUpdate:
    """Parsed representation of a Dhan postback payload."""
    dhan_client_id: str
    order_id: str
    correlation_id: str
    order_status: OrderStatus
    transaction_type: str
    exchange_segment: str
    product_type: str
    order_type: str
    validity: str
    trading_symbol: str
    security_id: str
    quantity: int
    disclosed_quantity: int
    price: float
    trigger_price: float
    after_market_order: bool
    bo_profit_value: float
    bo_stop_loss_value: float
    leg_name: str
    create_time: str
    update_time: str
    exchange_time: str
    drv_expiry_date: Optional[str]
    drv_option_type: Optional[str]
    drv_strike_price: float
    oms_error_code: Optional[str]
    oms_error_description: Optional[str]
    raw_payload: dict

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> OrderUpdate:
        return cls(
            dhan_client_id=str(data.get("dhanClientId", "")),
            order_id=str(data.get("orderId", "")),
            correlation_id=str(data.get("correlationId", "")),
            order_status=OrderStatus(data.get("orderStatus", "PENDING")),
            transaction_type=str(data.get("transactionType", "")),
            exchange_segment=str(data.get("exchangeSegment", "")),
            product_type=str(data.get("productType", "")),
            order_type=str(data.get("orderType", "")),
            validity=str(data.get("validity", "")),
            trading_symbol=str(data.get("tradingSymbol", "")),
            security_id=str(data.get("securityId", "")),
            quantity=int(data.get("quantity", 0)),
            disclosed_quantity=int(data.get("disclosedQuantity", 0)),
            price=float(data.get("price", 0.0)),
            trigger_price=float(data.get("triggerPrice", 0.0)),
            after_market_order=bool(data.get("afterMarketOrder", False)),
            bo_profit_value=float(data.get("boProfitValue", 0.0)),
            bo_stop_loss_value=float(data.get("boStopLossValue", 0.0)),
            leg_name=str(data.get("legName", "") or ""),
            create_time=str(data.get("createTime", "")),
            update_time=str(data.get("updateTime", "")),
            exchange_time=str(data.get("exchangeTime", "")),
            drv_expiry_date=data.get("drvExpiryDate"),
            drv_option_type=data.get("drvOptionType"),
            drv_strike_price=float(data.get("drvStrikePrice", 0.0)),
            oms_error_code=data.get("omsErrorCode"),
            oms_error_description=data.get("omsErrorDescription"),
            raw_payload=data,
        )


# Type alias for subscriber callbacks
OrderUpdateCallback = Callable[[OrderUpdate], None]


class WebhookHandler:
    """
    Processes Dhan postback payloads and dispatches to registered subscribers.

    Maintains an order state ledger to detect duplicates and track transitions.
    Subscribers register callbacks per order status (TRADED, REJECTED, etc.)
    or a catch-all for every update.
    """

    def __init__(self):
        self._subscribers: dict[str, list[OrderUpdateCallback]] = {}
        self._catch_all: list[OrderUpdateCallback] = []
        self._seen_updates: dict[str, str] = {}  # order_id -> last status
        self._order_history: list[OrderUpdate] = []

    def subscribe(self, status: str | OrderStatus, callback: OrderUpdateCallback) -> None:
        key = status.value if isinstance(status, OrderStatus) else status.upper()
        self._subscribers.setdefault(key, []).append(callback)
        logger.debug("Subscriber registered for status=%s", key)

    def subscribe_all(self, callback: OrderUpdateCallback) -> None:
        self._catch_all.append(callback)

    def process(self, payload: dict[str, Any]) -> OrderUpdate | None:
        """Parse a raw postback payload, deduplicate, and dispatch to subscribers."""
        try:
            update = OrderUpdate.from_payload(payload)
        except (KeyError, ValueError):
            logger.exception("Failed to parse postback payload: %s", payload)
            return None

        oid = update.order_id
        last_status = self._seen_updates.get(oid)

        if last_status == update.order_status.value:
            logger.debug("Duplicate update ignored: order=%s status=%s", oid, last_status)
            return update

        self._seen_updates[oid] = update.order_status.value
        self._order_history.append(update)

        logger.info(
            "Order update: id=%s status=%s side=%s qty=%d price=%.2f symbol=%s",
            oid, update.order_status.value, update.transaction_type,
            update.quantity, update.price, update.trading_symbol,
        )

        for cb in self._catch_all:
            self._safe_call(cb, update)

        status_key = update.order_status.value
        for cb in self._subscribers.get(status_key, []):
            self._safe_call(cb, update)

        return update

    def get_order_status(self, order_id: str) -> str | None:
        return self._seen_updates.get(order_id)

    def get_history(self, order_id: str | None = None) -> list[OrderUpdate]:
        if order_id:
            return [u for u in self._order_history if u.order_id == order_id]
        return list(self._order_history)

    @staticmethod
    def _safe_call(cb: OrderUpdateCallback, update: OrderUpdate) -> None:
        try:
            cb(update)
        except Exception:
            logger.exception("Webhook subscriber callback error")
