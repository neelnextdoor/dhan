from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from src.core.config import AppConfig
from src.core.logger import get_logger
from src.execution.position_manager import Trade

if TYPE_CHECKING:
    from src.webhooks.handler import OrderUpdate

logger = get_logger("telegram")


class TelegramNotifier:
    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: AppConfig):
        self.config = config
        self.enabled = config.telegram.enabled and config.telegram_bot_token and config.telegram_chat_id
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id

        if self.enabled:
            logger.info("Telegram notifications enabled")
        else:
            logger.debug("Telegram notifications disabled")

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            url = self.BASE_URL.format(token=self.token)
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.warning("Telegram send failed: %s", resp.text)
                return False
            return True
        except Exception:
            logger.exception("Telegram notification error")
            return False

    def notify_startup(self, mode: str, symbol: str, strategy: str,
                       capital: float, lot_size: int) -> None:
        msg = (
            f"🤖 *BOT STARTED*\n"
            f"Mode: `{mode.upper()}`\n"
            f"Symbol: `{symbol}`\n"
            f"Strategy: `{strategy}`\n"
            f"Capital: `₹{capital:,.0f}`\n"
            f"Lot: `{lot_size}`"
        )
        self.send(msg)

    def notify_shutdown(self, trades_count: int, total_pnl: float) -> None:
        emoji = "📈" if total_pnl >= 0 else "📉"
        msg = (
            f"{emoji} *BOT STOPPED*\n"
            f"Trades: `{trades_count}`\n"
            f"PnL: `₹{total_pnl:+,.2f}`"
        )
        self.send(msg)

    def notify_entry(self, trade: Trade) -> None:
        if not self.config.telegram.on_entry:
            return
        name = trade.display_name()
        msg = (
            f"🟢 *BUY {name}*\n"
            f"Premium: `{trade.entry_price:.2f}`\n"
            f"Qty: `{trade.quantity}`\n"
            f"SL: `{trade.stop_loss:.2f}`\n"
            f"Target: `{trade.target:.2f}`\n"
            f"Time: `{trade.entry_time:%H:%M:%S}`"
        )
        if trade.is_option:
            msg += f"\nStrike: `{trade.strike:.0f}` | Underlying: `{trade.underlying_price_at_entry:.2f}`"
        self.send(msg)

    def notify_exit(self, trade: Trade) -> None:
        if not self.config.telegram.on_exit:
            return
        emoji = "🟩" if trade.pnl >= 0 else "🟥"
        name = trade.display_name()
        msg = (
            f"{emoji} *SELL {name}*\n"
            f"Entry: `{trade.entry_price:.2f}`\n"
            f"Exit: `{trade.exit_price:.2f}`\n"
            f"PnL: `{trade.pnl:+.2f}`\n"
            f"Reason: `{trade.exit_reason.value if trade.exit_reason else 'N/A'}`"
        )
        self.send(msg)

    def notify_error(self, error: str) -> None:
        if not self.config.telegram.on_error:
            return
        self.send(f"🚨 *ERROR*\n```\n{error}\n```")

    def notify_daily_summary(self, trades: list[Trade], total_pnl: float) -> None:
        if not self.config.telegram.daily_summary:
            return
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl <= 0)
        emoji = "📈" if total_pnl >= 0 else "📉"
        msg = (
            f"{emoji} *DAILY SUMMARY*\n"
            f"Trades: `{len(trades)}`\n"
            f"Wins: `{wins}` | Losses: `{losses}`\n"
            f"Total PnL: `{total_pnl:+.2f}`"
        )
        self.send(msg)

    def notify_order_update(self, update: OrderUpdate) -> None:
        status = update.order_status.value
        emoji_map = {
            "TRADED": "✅",
            "REJECTED": "❌",
            "CANCELLED": "🚫",
            "EXPIRED": "⏰",
            "PENDING": "⏳",
            "TRANSIT": "🔄",
        }
        emoji = emoji_map.get(status, "📋")
        msg = (
            f"{emoji} *ORDER {status}*\n"
            f"ID: `{update.order_id}`\n"
            f"Side: `{update.transaction_type}`\n"
            f"Symbol: `{update.trading_symbol or update.security_id}`\n"
            f"Qty: `{update.quantity}` @ `{update.price:.2f}`\n"
            f"Type: `{update.order_type}` | `{update.product_type}`"
        )
        if update.oms_error_description:
            msg += f"\nError: `{update.oms_error_description}`"
        self.send(msg)
