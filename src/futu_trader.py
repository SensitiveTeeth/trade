"""Futu OpenAPI trading module."""

import logging
from typing import Optional
from dataclasses import dataclass

from futu import (
    OpenSecTradeContext,
    OpenQuoteContext,
    TrdSide,
    TrdEnv,
    OrderType,
    RET_OK,
)

from config import config

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Order execution result."""

    success: bool
    order_id: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    message: Optional[str] = None


class FutuTrader:
    """Futu OpenAPI trading client."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        is_simulation: Optional[bool] = None,
    ):
        self.host = host or config.FUTU_HOST
        self.port = port or config.FUTU_PORT
        self.is_simulation = is_simulation if is_simulation is not None else config.IS_SIMULATION
        self.trd_env = TrdEnv.SIMULATE if self.is_simulation else TrdEnv.REAL

        self._trd_ctx: Optional[OpenSecTradeContext] = None
        self._quote_ctx: Optional[OpenQuoteContext] = None

    def connect(self) -> bool:
        """Connect to FutuOpenD."""
        try:
            self._trd_ctx = OpenSecTradeContext(
                host=self.host,
                port=self.port,
                filter_trdmarket=None,
            )
            self._quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
            logger.info(f"Connected to FutuOpenD at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to FutuOpenD: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from FutuOpenD."""
        if self._trd_ctx:
            self._trd_ctx.close()
            self._trd_ctx = None
        if self._quote_ctx:
            self._quote_ctx.close()
            self._quote_ctx = None
        logger.info("Disconnected from FutuOpenD")

    def _ensure_connected(self) -> bool:
        """Ensure connection is established."""
        if not self._trd_ctx or not self._quote_ctx:
            return self.connect()
        return True

    def get_quote(self, ticker: str) -> Optional[float]:
        """
        Get current price for a ticker.

        Args:
            ticker: Stock ticker (e.g., "BAC")

        Returns:
            Current price or None if failed.
        """
        if not self._ensure_connected():
            return None

        code = f"US.{ticker}"
        try:
            ret, data = self._quote_ctx.get_stock_quote(code)
            if ret == RET_OK and not data.empty:
                return float(data["last_price"].iloc[0])
            logger.error(f"Failed to get quote for {ticker}: {data}")
        except Exception as e:
            logger.error(f"Error getting quote for {ticker}: {e}")

        return None

    def get_quotes_batch(self, tickers: list[str]) -> dict[str, float]:
        """Get quotes for multiple tickers."""
        results = {}
        for ticker in tickers:
            price = self.get_quote(ticker)
            if price:
                results[ticker] = price
        return results

    def place_order(
        self,
        ticker: str,
        quantity: int,
        side: str,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> OrderResult:
        """
        Place an order.

        Args:
            ticker: Stock ticker (e.g., "BAC")
            quantity: Number of shares
            side: "BUY" or "SELL"
            order_type: "MARKET" or "LIMIT"
            price: Limit price (required for LIMIT orders)

        Returns:
            OrderResult with execution details.
        """
        if not self._ensure_connected():
            return OrderResult(success=False, message="Not connected to FutuOpenD")

        code = f"US.{ticker}"
        trd_side = TrdSide.BUY if side.upper() == "BUY" else TrdSide.SELL

        if order_type.upper() == "MARKET":
            futu_order_type = OrderType.MARKET
            order_price = 0
        else:
            futu_order_type = OrderType.NORMAL
            if price is None:
                return OrderResult(success=False, message="Price required for limit order")
            order_price = price

        try:
            ret, data = self._trd_ctx.place_order(
                price=order_price,
                qty=quantity,
                code=code,
                trd_side=trd_side,
                order_type=futu_order_type,
                trd_env=self.trd_env,
            )

            if ret == RET_OK:
                order_id = str(data["order_id"].iloc[0]) if "order_id" in data.columns else None
                filled_price = self.get_quote(ticker)  # Get approximate fill price
                logger.info(f"Order placed: {side} {quantity} {ticker} @ {filled_price}")
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    price=filled_price,
                    quantity=quantity,
                )
            else:
                logger.error(f"Order failed: {data}")
                return OrderResult(success=False, message=str(data))

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return OrderResult(success=False, message=str(e))

    def buy(self, ticker: str, quantity: int) -> OrderResult:
        """Place a market buy order."""
        return self.place_order(ticker, quantity, "BUY", "MARKET")

    def sell(self, ticker: str, quantity: int) -> OrderResult:
        """Place a market sell order."""
        return self.place_order(ticker, quantity, "SELL", "MARKET")

    def get_positions(self) -> list[dict]:
        """Get current positions from Futu."""
        if not self._ensure_connected():
            return []

        try:
            ret, data = self._trd_ctx.position_list_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                positions = []
                for _, row in data.iterrows():
                    positions.append({
                        "ticker": row["code"].replace("US.", ""),
                        "quantity": int(row["qty"]),
                        "avg_cost": float(row["cost_price"]),
                        "market_value": float(row["market_val"]),
                        "unrealized_pnl": float(row["pl_val"]),
                    })
                return positions
            return []
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_account_info(self) -> Optional[dict]:
        """Get account information."""
        if not self._ensure_connected():
            return None

        try:
            ret, data = self._trd_ctx.accinfo_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                return {
                    "total_assets": float(data["total_assets"].iloc[0]),
                    "cash": float(data["cash"].iloc[0]),
                    "market_value": float(data["market_val"].iloc[0]),
                }
            return None
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return None


# Singleton instance
futu_trader = FutuTrader()
