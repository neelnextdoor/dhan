from __future__ import annotations

from typing import Any

from src.core.config import AppConfig
from src.core.constants import OptionType, OrderSide, SignalType, TradingMode
from src.core.logger import get_logger
from src.data.dhan_client import DhanClient
from src.options.contract_selector import OptionContract

logger = get_logger("order_manager")


class OrderManager:
    """
    Handles order placement for option buying.

    Entry: always BUY (buy CE for LONG, buy PE for SHORT)
    Exit: always SELL (sell whatever was bought)
    """

    def __init__(self, config: AppConfig, client: DhanClient | None = None):
        self.config = config
        self.client = client
        self.mode = TradingMode(config.trading_mode)
        self._paper_order_counter = 0

    def place_entry_order(
        self,
        signal_type: SignalType,
        premium: float,
        quantity: int,
        contract: OptionContract | None = None,
    ) -> dict[str, Any]:
        """Buy a CE (LONG signal) or PE (SHORT signal)."""
        opt_type = "CE" if signal_type == SignalType.LONG else "PE"

        if self.mode == TradingMode.PAPER:
            return self._paper_order("BUY", premium, quantity, opt_type, contract)

        if self.mode == TradingMode.LIVE:
            if not contract or not contract.security_id:
                logger.error("No valid option contract for live order")
                return {"status": "error", "remarks": "no_contract"}
            return self._live_order("BUY", premium, quantity, contract)

        return {"status": "skipped", "mode": self.mode.value}

    def place_exit_order(
        self,
        premium: float,
        quantity: int,
        contract: OptionContract | None = None,
        option_security_id: str = "",
    ) -> dict[str, Any]:
        """Sell the option to exit the position."""
        if self.mode == TradingMode.PAPER:
            return self._paper_order("SELL", premium, quantity)

        if self.mode == TradingMode.LIVE:
            sec_id = option_security_id
            if contract and contract.security_id:
                sec_id = contract.security_id
            if not sec_id:
                logger.error("No security ID for exit order")
                return {"status": "error", "remarks": "no_security_id"}
            return self._live_option_exit(sec_id, premium, quantity)

        return {"status": "skipped", "mode": self.mode.value}

    def _live_order(
        self,
        side: str,
        price: float,
        qty: int,
        contract: OptionContract,
    ) -> dict[str, Any]:
        if not self.client:
            logger.error("DhanClient not available for live orders")
            return {"status": "error", "remarks": "no_client"}

        from dhanhq import dhanhq as DhanHQ
        resp = self.client.place_order(
            security_id=contract.security_id,
            exchange_segment=DhanHQ.NSE_FNO,
            transaction_type=side,
            quantity=qty,
            order_type="MARKET",
            product_type="INTRADAY",
            tag="dhan_algo_opt",
        )
        return resp

    def _live_option_exit(self, security_id: str, price: float, qty: int) -> dict[str, Any]:
        if not self.client:
            return {"status": "error", "remarks": "no_client"}

        from dhanhq import dhanhq as DhanHQ
        resp = self.client.place_order(
            security_id=security_id,
            exchange_segment=DhanHQ.NSE_FNO,
            transaction_type="SELL",
            quantity=qty,
            order_type="MARKET",
            product_type="INTRADAY",
            tag="dhan_algo_opt",
        )
        return resp

    def _paper_order(
        self,
        side: str,
        price: float,
        qty: int,
        opt_type: str = "",
        contract: OptionContract | None = None,
    ) -> dict[str, Any]:
        self._paper_order_counter += 1
        slippage = price * (self.config.paper_trading.slippage_pct / 100)
        fill_price = price + slippage if side == "BUY" else price - slippage
        fill_price = max(fill_price, 0.05)

        order = {
            "status": "success",
            "orderId": f"PAPER-{self._paper_order_counter:06d}",
            "side": side,
            "quantity": qty,
            "price": round(fill_price, 2),
            "mode": "paper",
            "optionType": opt_type,
        }
        if contract:
            order["securityId"] = contract.security_id
            order["strike"] = contract.strike
            order["expiry"] = contract.expiry
        logger.info("Paper order: %s", order)
        return order
