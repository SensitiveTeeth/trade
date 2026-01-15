"""Trading strategy logic."""

import logging
from dataclasses import dataclass
from typing import Optional

from config import config
from database import (
    get_position,
    get_all_positions,
    get_position_count,
    add_position,
    remove_position,
    update_position,
    log_trade,
    save_ai_score,
)
from danelfin import danelfin_client, DanelfinScore
from futu_trader import futu_trader, OrderResult
from telegram_bot import telegram_notifier

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Trading signal."""

    ticker: str
    action: str  # "BUY", "SELL", "HOLD"
    reason: str
    ai_score: Optional[int] = None
    current_price: Optional[float] = None
    target_price: Optional[float] = None


class TradingStrategy:
    """Trading strategy implementation."""

    def __init__(self):
        self.buy_threshold = config.BUY_SCORE_THRESHOLD
        self.sell_threshold = config.SELL_SCORE_THRESHOLD
        self.max_positions = config.MAX_POSITIONS
        self.take_profit_pct = config.TAKE_PROFIT_PCT
        self.stop_loss_pct = config.STOP_LOSS_PCT
        self.default_quantity = 100  # Default shares per trade
        self._last_daily_check_date: str = ""

    def sync_positions_with_broker(self) -> None:
        """Sync local position database with actual broker positions on startup."""
        logger.info("Syncing positions with broker...")

        # Get actual positions from Futu
        broker_positions = futu_trader.get_positions()
        broker_map = {p["ticker"]: p for p in broker_positions}
        broker_tickers = set(broker_map.keys())

        # Get local positions from database
        local_positions = get_all_positions()
        local_map = {p["ticker"]: p for p in local_positions}
        local_tickers = set(local_map.keys())

        # Track changes for notification
        added = []
        removed = []
        updated = []

        # Find positions missing locally (in broker but not in DB)
        missing_locally = broker_tickers - local_tickers
        if missing_locally:
            logger.warning(f"Positions in broker but not in DB: {missing_locally}")
            for ticker in missing_locally:
                pos = broker_map[ticker]
                add_position(
                    ticker=pos["ticker"],
                    quantity=pos["quantity"],
                    avg_cost=pos["avg_cost"],
                )
                added.append(ticker)
                logger.info(f"Added missing position: {ticker} (qty={pos['quantity']}, cost=${pos['avg_cost']:.2f})")

        # Find positions missing in broker (in DB but not in broker)
        missing_in_broker = local_tickers - broker_tickers
        if missing_in_broker:
            logger.warning(f"Positions in DB but not in broker: {missing_in_broker}")
            for ticker in missing_in_broker:
                remove_position(ticker)
                removed.append(ticker)
                logger.info(f"Removed stale position: {ticker}")

        # Check for quantity/cost differences in existing positions
        common_tickers = broker_tickers & local_tickers
        for ticker in common_tickers:
            broker_pos = broker_map[ticker]
            local_pos = local_map[ticker]

            broker_qty = broker_pos["quantity"]
            local_qty = local_pos["quantity"]
            broker_cost = broker_pos["avg_cost"]
            local_cost = local_pos["avg_cost"]

            # Update if quantity or avg_cost differs
            if broker_qty != local_qty or abs(broker_cost - local_cost) > 0.01:
                update_position(ticker, broker_qty, broker_cost)
                updated.append(ticker)
                logger.info(
                    f"Updated position {ticker}: qty {local_qty}->{broker_qty}, "
                    f"cost ${local_cost:.2f}->${broker_cost:.2f}"
                )

        # Notify if any changes were made
        if added or removed or updated:
            changes = []
            if added:
                changes.append(f"Added: {', '.join(added)}")
            if removed:
                changes.append(f"Removed: {', '.join(removed)}")
            if updated:
                changes.append(f"Updated: {', '.join(updated)}")
            telegram_notifier.notify_error(f"Position sync: {'; '.join(changes)}")

        logger.info(f"Position sync completed: {len(added)} added, {len(removed)} removed, {len(updated)} updated")

    def analyze_ticker(self, ticker: str) -> TradeSignal:
        """
        Analyze a single ticker and generate trading signal.

        Args:
            ticker: Stock ticker symbol

        Returns:
            TradeSignal with recommended action.
        """
        # Get AI score from Danelfin
        score = danelfin_client.get_score(ticker)
        if not score:
            logger.warning(f"Could not get AI score for {ticker}")
            return TradeSignal(ticker=ticker, action="HOLD", reason="No AI score available")

        # Save score to history
        save_ai_score(
            ticker=ticker,
            ai_score=score.ai_score,
            fundamental_score=score.fundamental_score,
            technical_score=score.technical_score,
            sentiment_score=score.sentiment_score,
            target_price=score.target_price,
        )

        # Get current position
        position = get_position(ticker)
        current_price = futu_trader.get_quote(ticker)

        # Generate signal based on rules
        if position:
            # Already holding - check for sell signals
            return self._check_sell_signal(ticker, score, position, current_price)
        else:
            # Not holding - check for buy signal
            return self._check_buy_signal(ticker, score, current_price)

    def _check_buy_signal(
        self,
        ticker: str,
        score: DanelfinScore,
        current_price: Optional[float],
    ) -> TradeSignal:
        """Check if we should buy."""
        # Check position limit
        if get_position_count() >= self.max_positions:
            return TradeSignal(
                ticker=ticker,
                action="HOLD",
                reason=f"Max positions ({self.max_positions}) reached",
                ai_score=score.ai_score,
                current_price=current_price,
            )

        # Check AI score threshold
        if score.ai_score >= self.buy_threshold:
            return TradeSignal(
                ticker=ticker,
                action="BUY",
                reason=f"AI Score = {score.ai_score} (Strong Buy)",
                ai_score=score.ai_score,
                current_price=current_price,
                target_price=score.target_price,
            )

        return TradeSignal(
            ticker=ticker,
            action="HOLD",
            reason=f"AI Score {score.ai_score} below buy threshold {self.buy_threshold}",
            ai_score=score.ai_score,
            current_price=current_price,
        )

    def _check_sell_signal(
        self,
        ticker: str,
        score: DanelfinScore,
        position: dict,
        current_price: Optional[float],
    ) -> TradeSignal:
        """Check if we should sell."""
        avg_cost = position["avg_cost"]

        # Check stop loss
        if current_price and current_price <= avg_cost * (1 - self.stop_loss_pct):
            return TradeSignal(
                ticker=ticker,
                action="SELL",
                reason=f"Stop loss triggered ({self.stop_loss_pct*100:.0f}% loss)",
                ai_score=score.ai_score,
                current_price=current_price,
            )

        # Check take profit
        if current_price and current_price >= avg_cost * (1 + self.take_profit_pct):
            return TradeSignal(
                ticker=ticker,
                action="SELL",
                reason=f"Take profit triggered ({self.take_profit_pct*100:.0f}% gain)",
                ai_score=score.ai_score,
                current_price=current_price,
            )

        # Check AI score drop
        if score.ai_score < self.sell_threshold:
            return TradeSignal(
                ticker=ticker,
                action="SELL",
                reason=f"AI Score dropped to {score.ai_score} (below {self.sell_threshold})",
                ai_score=score.ai_score,
                current_price=current_price,
            )

        return TradeSignal(
            ticker=ticker,
            action="HOLD",
            reason="No sell signal",
            ai_score=score.ai_score,
            current_price=current_price,
        )

    def execute_signal(self, signal: TradeSignal) -> Optional[OrderResult]:
        """
        Execute a trading signal.

        Args:
            signal: TradeSignal to execute

        Returns:
            OrderResult if trade executed, None otherwise.
        """
        if signal.action == "HOLD":
            logger.info(f"{signal.ticker}: HOLD - {signal.reason}")
            return None

        if signal.action == "BUY":
            return self._execute_buy(signal)
        elif signal.action == "SELL":
            return self._execute_sell(signal)

        return None

    def _execute_buy(self, signal: TradeSignal) -> Optional[OrderResult]:
        """Execute buy order."""
        ticker = signal.ticker
        quantity = self.default_quantity

        logger.info(f"Executing BUY: {quantity} {ticker}")

        result = futu_trader.buy(ticker, quantity)

        if result.success and result.price and result.filled_quantity:
            filled_qty = result.filled_quantity
            # Calculate target and stop loss
            target_price = result.price * (1 + self.take_profit_pct)
            stop_loss = result.price * (1 - self.stop_loss_pct)

            # Update database with actual filled quantity
            add_position(
                ticker=ticker,
                quantity=filled_qty,
                avg_cost=result.price,
                ai_score=signal.ai_score,
                target_price=target_price,
                stop_loss=stop_loss,
            )
            log_trade(
                ticker=ticker,
                action="BUY",
                quantity=filled_qty,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
                order_id=result.order_id,
            )

            # Send notification with partial fill info if applicable
            reason = signal.reason
            if result.partial_fill:
                reason = f"{signal.reason} (Partial fill: {filled_qty}/{quantity})"

            telegram_notifier.notify_trade(
                ticker=ticker,
                action="BUY",
                quantity=filled_qty,
                price=result.price,
                ai_score=signal.ai_score,
                reason=reason,
            )

            logger.info(f"BUY executed: {filled_qty}/{quantity} {ticker} @ ${result.price:.2f}")
            if result.partial_fill:
                logger.warning(f"Partial fill for {ticker}: {filled_qty}/{quantity} shares")
        else:
            logger.error(f"BUY failed for {ticker}: {result.message}")
            telegram_notifier.notify_error(f"Buy order failed for {ticker}: {result.message}")

        return result

    def _execute_sell(self, signal: TradeSignal) -> Optional[OrderResult]:
        """Execute sell order."""
        ticker = signal.ticker
        position = get_position(ticker)

        if not position:
            logger.warning(f"No position to sell for {ticker}")
            return None

        quantity = position["quantity"]
        logger.info(f"Executing SELL: {quantity} {ticker}")

        result = futu_trader.sell(ticker, quantity)

        if result.success and result.price and result.filled_quantity:
            filled_qty = result.filled_quantity

            # Update database based on fill status
            if result.partial_fill:
                # Partial fill: update remaining position
                remaining_qty = quantity - filled_qty
                self._update_position_quantity(ticker, remaining_qty, position["avg_cost"])
                logger.warning(f"Partial sell for {ticker}: {filled_qty}/{quantity} shares, {remaining_qty} remaining")
            else:
                # Full fill: remove position
                remove_position(ticker)

            log_trade(
                ticker=ticker,
                action="SELL",
                quantity=filled_qty,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
                order_id=result.order_id,
            )

            # Send notification with partial fill info if applicable
            reason = signal.reason
            if result.partial_fill:
                reason = f"{signal.reason} (Partial fill: {filled_qty}/{quantity})"

            telegram_notifier.notify_trade(
                ticker=ticker,
                action="SELL",
                quantity=filled_qty,
                price=result.price,
                ai_score=signal.ai_score,
                reason=reason,
                avg_cost=position["avg_cost"],
            )

            logger.info(f"SELL executed: {filled_qty}/{quantity} {ticker} @ ${result.price:.2f}")
        else:
            logger.error(f"SELL failed for {ticker}: {result.message}")
            telegram_notifier.notify_error(f"Sell order failed for {ticker}: {result.message}")

        return result

    def _update_position_quantity(self, ticker: str, new_quantity: int, avg_cost: float) -> None:
        """Update position with new quantity after partial sell."""
        from database import get_db_connection

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE positions SET quantity = ? WHERE ticker = ?",
                (new_quantity, ticker),
            )
            conn.commit()

    def run_daily_check(self) -> None:
        """Run daily check: buy AI Score 10 stocks, sell positions that dropped."""
        from datetime import datetime

        # Prevent duplicate runs on same day
        today = datetime.now().strftime("%Y-%m-%d")
        if today == self._last_daily_check_date:
            logger.info("Daily check already ran today, skipping")
            return
        self._last_daily_check_date = today

        logger.info("Running daily Danelfin check...")

        # 1. Check for BUY signals: Get AI Score = 10 stocks from Danelfin
        self._check_buy_signals()

        # 2. Check for SELL signals: Check current positions
        self._check_sell_signals()

        logger.info("Daily check completed")

    def _check_buy_signals(self) -> None:
        """Check Danelfin for AI Score 10 stocks to buy."""
        logger.info("Fetching AI Score 10 stocks from Danelfin...")

        # Get all stocks with AI Score = 10 from Danelfin API
        top_stocks = danelfin_client.get_top_stocks(ai_score=10)

        if not top_stocks:
            logger.info("No AI Score 10 stocks found")
            return

        logger.info(f"Found {len(top_stocks)} stocks with AI Score 10")

        for score in top_stocks:
            ticker = score.ticker
            try:
                # Skip if already holding
                if get_position(ticker):
                    logger.info(f"{ticker}: Already holding, skip")
                    continue

                # Check position limit
                if get_position_count() >= self.max_positions:
                    logger.info(f"Max positions ({self.max_positions}) reached, stopping buy check")
                    break

                # Get current price
                current_price = futu_trader.get_quote(ticker)
                if not current_price:
                    logger.warning(f"{ticker}: Could not get quote, skip")
                    continue

                logger.info(f"{ticker}: AI Score=10, Price=${current_price:.2f}, Action=BUY")

                signal = TradeSignal(
                    ticker=ticker,
                    action="BUY",
                    reason="AI Score = 10 (Strong Buy)",
                    ai_score=score.ai_score,
                    current_price=current_price,
                    target_price=score.target_price,
                )

                telegram_notifier.notify_signal(
                    ticker=ticker,
                    signal_type="BUY",
                    ai_score=score.ai_score,
                    current_price=current_price,
                    target_price=score.target_price,
                )

                self.execute_signal(signal)

                # Save score to history
                save_ai_score(
                    ticker=ticker,
                    ai_score=score.ai_score,
                    fundamental_score=score.fundamental_score,
                    technical_score=score.technical_score,
                    sentiment_score=score.sentiment_score,
                    target_price=score.target_price,
                )

            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")

    def _check_sell_signals(self) -> None:
        """Check current positions for sell signals based on AI score drop."""
        positions = get_all_positions()
        if not positions:
            logger.info("No positions to check for sell signals")
            return

        logger.info(f"Checking {len(positions)} positions for sell signals...")

        for position in positions:
            ticker = position["ticker"]
            try:
                # Get latest AI score
                score = danelfin_client.get_score(ticker)
                if not score:
                    logger.warning(f"{ticker}: Could not get AI score")
                    continue

                current_price = futu_trader.get_quote(ticker)

                logger.info(f"{ticker}: AI Score={score.ai_score}, Price=${current_price:.2f if current_price else 0}")

                # Check if AI score dropped below threshold
                if score.ai_score < self.sell_threshold:
                    logger.info(f"{ticker}: AI Score={score.ai_score} < {self.sell_threshold}, Action=SELL")

                    signal = TradeSignal(
                        ticker=ticker,
                        action="SELL",
                        reason=f"AI Score dropped to {score.ai_score} (below {self.sell_threshold})",
                        ai_score=score.ai_score,
                        current_price=current_price,
                    )

                    telegram_notifier.notify_signal(
                        ticker=ticker,
                        signal_type="SELL",
                        ai_score=score.ai_score,
                        current_price=current_price,
                    )

                    self.execute_signal(signal)

                # Save score to history
                save_ai_score(
                    ticker=ticker,
                    ai_score=score.ai_score,
                    fundamental_score=score.fundamental_score,
                    technical_score=score.technical_score,
                    sentiment_score=score.sentiment_score,
                    target_price=score.target_price,
                )

            except Exception as e:
                logger.error(f"Error checking {ticker}: {e}")

    def run_price_check(self) -> None:
        """Run price check for stop loss/take profit on current positions."""
        logger.info("Running price check for positions...")

        positions = get_all_positions()
        if not positions:
            logger.info("No positions to check")
            return

        for position in positions:
            ticker = position["ticker"]
            try:
                current_price = futu_trader.get_quote(ticker)
                if not current_price:
                    continue

                avg_cost = position["avg_cost"]

                # Check stop loss
                if current_price <= avg_cost * (1 - self.stop_loss_pct):
                    signal = TradeSignal(
                        ticker=ticker,
                        action="SELL",
                        reason=f"Stop loss triggered at ${current_price:.2f}",
                        current_price=current_price,
                    )
                    self.execute_signal(signal)

                # Check take profit
                elif current_price >= avg_cost * (1 + self.take_profit_pct):
                    signal = TradeSignal(
                        ticker=ticker,
                        action="SELL",
                        reason=f"Take profit triggered at ${current_price:.2f}",
                        current_price=current_price,
                    )
                    self.execute_signal(signal)

            except Exception as e:
                logger.error(f"Error checking price for {ticker}: {e}")

        logger.info("Price check completed")

    def run_daily_summary(self) -> None:
        """Send daily summary after market close."""
        logger.info("Generating daily summary...")

        # Get positions from broker for accurate market values
        broker_positions = futu_trader.get_positions()

        if not broker_positions:
            logger.info("No positions to summarize")
            return

        # Calculate totals
        total_value = sum(p.get("market_value", 0) for p in broker_positions)
        daily_pnl = sum(p.get("unrealized_pnl", 0) for p in broker_positions)

        # Send summary notification
        telegram_notifier.notify_daily_summary(
            positions=broker_positions,
            total_value=total_value,
            daily_pnl=daily_pnl,
        )

        logger.info(f"Daily summary sent: {len(broker_positions)} positions, total ${total_value:,.2f}")


# Singleton instance
trading_strategy = TradingStrategy()
