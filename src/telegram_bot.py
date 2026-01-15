"""Telegram notification module."""

import html
import logging
import time
from typing import Optional

import requests

from config import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]  # seconds


class TelegramNotifier:
    """Telegram bot for sending notifications."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to Telegram.

        Args:
            message: Message text
            parse_mode: "HTML" or "Markdown"

        Returns:
            True if sent successfully.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(url, data=payload, timeout=10)
                response.raise_for_status()
                logger.debug(f"Telegram message sent: {message[:50]}...")
                return True
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(f"Telegram send failed, retrying in {delay}s: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to send Telegram message after {MAX_RETRIES} attempts: {e}")
                    return False
        return False

    def notify_trade(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        ai_score: Optional[int] = None,
        reason: Optional[str] = None,
        avg_cost: Optional[float] = None,
    ) -> bool:
        """Send trade notification."""
        total = quantity * price

        # Determine emoji and title based on action and reason
        if action.upper() == "BUY":
            emoji = "🟢"
            title = "Trade Executed"
        else:
            # Check for stop loss or take profit triggers
            reason_lower = (reason or "").lower()
            if "stop loss" in reason_lower:
                emoji = "🛑"
                title = "Stop Loss Triggered"
            elif "take profit" in reason_lower:
                emoji = "💰"
                title = "Take Profit Triggered"
            else:
                emoji = "🔴"
                title = "Trade Executed"

        message = f"""
{emoji} <b>{title}</b>

<b>Ticker:</b> {ticker}
<b>Action:</b> {action.upper()}
<b>Quantity:</b> {quantity} shares
<b>Price:</b> ${price:.2f}
<b>Total:</b> ${total:,.2f}
"""
        # Show P&L for sell orders
        if action.upper() == "SELL" and avg_cost is not None:
            pnl = (price - avg_cost) * quantity
            pnl_pct = ((price - avg_cost) / avg_cost) * 100
            pnl_emoji = "📈" if pnl >= 0 else "📉"
            pnl_sign = "+" if pnl >= 0 else ""
            message += f"<b>Avg Cost:</b> ${avg_cost:.2f}\n"
            message += f"<b>P&L:</b> {pnl_emoji} {pnl_sign}${pnl:,.2f} ({pnl_sign}{pnl_pct:.1f}%)\n"

        if ai_score is not None:
            message += f"<b>AI Score:</b> {ai_score}/10\n"
        if reason:
            message += f"<b>Reason:</b> {reason}\n"

        return self.send_message(message.strip())

    def notify_signal(
        self,
        ticker: str,
        signal_type: str,
        ai_score: int,
        current_price: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> bool:
        """Send trading signal notification."""
        emoji = "📈" if signal_type == "BUY" else "📉"

        message = f"""
{emoji} <b>Trading Signal: {signal_type}</b>

<b>Ticker:</b> {ticker}
<b>AI Score:</b> {ai_score}/10
"""
        if current_price:
            message += f"<b>Current Price:</b> ${current_price:.2f}\n"
        if target_price:
            message += f"<b>Target Price:</b> ${target_price:.2f}\n"

        return self.send_message(message.strip())

    def notify_error(self, error_message: str) -> bool:
        """Send error notification."""
        # Escape HTML in error message
        safe_message = html.escape(str(error_message))
        message = f"""
⚠️ <b>Trading System Error</b>

{safe_message}
"""
        return self.send_message(message.strip())

    def notify_daily_summary(
        self,
        positions: list[dict],
        total_value: float,
        daily_pnl: float,
    ) -> bool:
        """Send daily summary notification."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        pnl_sign = "+" if daily_pnl >= 0 else ""

        message = f"""
📊 <b>Daily Summary</b>

<b>Total Value:</b> ${total_value:,.2f}
<b>Daily P&L:</b> {pnl_emoji} {pnl_sign}${daily_pnl:,.2f}
<b>Positions:</b> {len(positions)}
"""
        if positions:
            message += "\n<b>Holdings:</b>\n"
            for pos in positions[:5]:  # Show top 5
                message += f"  • {pos['ticker']}: {pos['quantity']} shares\n"
            if len(positions) > 5:
                message += f"  ... and {len(positions) - 5} more\n"

        return self.send_message(message.strip())

    def notify_startup(self, is_simulation: bool) -> bool:
        """Send startup notification."""
        mode = "SIMULATION" if is_simulation else "LIVE"
        emoji = "🧪" if is_simulation else "🚀"

        message = f"""
{emoji} <b>Trading System Started</b>

<b>Mode:</b> {mode}
<b>Status:</b> Running
"""
        return self.send_message(message.strip())

    def notify_shutdown(self) -> bool:
        """Send shutdown notification."""
        message = """
🛑 <b>Trading System Stopped</b>

The trading system has been shut down.
"""
        return self.send_message(message.strip())


# Singleton instance
telegram_notifier = TelegramNotifier()
