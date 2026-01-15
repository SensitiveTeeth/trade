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
        broker_tickers = {p["ticker"] for p in broker_positions}

        # Get local positions from database
        local_positions = get_all_positions()
        local_tickers = {p["ticker"] for p in local_positions}

        # Find discrepancies
        missing_locally = broker_tickers - local_tickers
        missing_in_broker = local_tickers - broker_tickers

        # Log and handle discrepancies
        if missing_locally:
            logger.warning(f"Positions in broker but not in DB: {missing_locally}")
            for pos in broker_positions:
                if pos["ticker"] in missing_locally:
                    # Add missing position to database
                    add_position(
                        ticker=pos["ticker"],
                        quantity=pos["quantity"],
                        avg_cost=pos["avg_cost"],
                    )
                    logger.info(f"Added missing position: {pos['ticker']}")

        if missing_in_broker:
            logger.warning(f"Positions in DB but not in broker: {missing_in_broker}")
            for ticker in missing_in_broker:
                # Remove stale position from database
                remove_position(ticker)
                logger.info(f"Removed stale position: {ticker}")

        # Notify if any discrepancies found
        if missing_locally or missing_in_broker:
            telegram_notifier.notify_error(
                f"Position sync: Added {len(missing_locally)}, Removed {len(missing_in_broker)}"
            )

        logger.info("Position sync completed")

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

        if result.success and result.price:
            # Calculate target and stop loss
            target_price = result.price * (1 + self.take_profit_pct)
            stop_loss = result.price * (1 - self.stop_loss_pct)

            # Update database
            add_position(
                ticker=ticker,
                quantity=quantity,
                avg_cost=result.price,
                ai_score=signal.ai_score,
                target_price=target_price,
                stop_loss=stop_loss,
            )
            log_trade(
                ticker=ticker,
                action="BUY",
                quantity=quantity,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
                order_id=result.order_id,
            )

            # Send notification
            telegram_notifier.notify_trade(
                ticker=ticker,
                action="BUY",
                quantity=quantity,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
            )

            logger.info(f"BUY executed: {quantity} {ticker} @ ${result.price:.2f}")
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

        if result.success and result.price:
            # Update database
            remove_position(ticker)
            log_trade(
                ticker=ticker,
                action="SELL",
                quantity=quantity,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
                order_id=result.order_id,
            )

            # Send notification
            telegram_notifier.notify_trade(
                ticker=ticker,
                action="SELL",
                quantity=quantity,
                price=result.price,
                ai_score=signal.ai_score,
                reason=signal.reason,
            )

            logger.info(f"SELL executed: {quantity} {ticker} @ ${result.price:.2f}")
        else:
            logger.error(f"SELL failed for {ticker}: {result.message}")
            telegram_notifier.notify_error(f"Sell order failed for {ticker}: {result.message}")

        return result

    def run_daily_check(self) -> None:
        """Run daily AI score check for all watchlist stocks."""
        from datetime import datetime

        # Prevent duplicate runs on same day
        today = datetime.now().strftime("%Y-%m-%d")
        if today == self._last_daily_check_date:
            logger.info("Daily check already ran today, skipping")
            return
        self._last_daily_check_date = today

        logger.info("Running daily AI score check...")

        for ticker in config.WATCHLIST:
            try:
                signal = self.analyze_ticker(ticker)
                if signal.action != "HOLD":
                    telegram_notifier.notify_signal(
                        ticker=ticker,
                        signal_type=signal.action,
                        ai_score=signal.ai_score or 0,
                        current_price=signal.current_price,
                        target_price=signal.target_price,
                    )
                    self.execute_signal(signal)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")
                telegram_notifier.notify_error(f"Error analyzing {ticker}: {e}")

        logger.info("Daily AI score check completed")

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


# Singleton instance
trading_strategy = TradingStrategy()
