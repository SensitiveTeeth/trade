"""Futu OpenAPI trading module."""

import logging
import time
from typing import Optional
from dataclasses import dataclass

from futu import (
    OpenSecTradeContext,
    OpenQuoteContext,
    TrdSide,
    TrdEnv,
    OrderType,
    OrderStatus,
    RET_OK,
    SubType,
)

from config import config

logger = logging.getLogger(__name__)

# Order status polling settings
ORDER_POLL_INTERVAL = 1  # seconds
ORDER_POLL_TIMEOUT = 30  # seconds


@dataclass
class OrderResult:
    """Order execution result."""

    success: bool
    order_id: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    filled_quantity: Optional[int] = None
    message: Optional[str] = None
    partial_fill: bool = False


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

    def _subscribe(self, code: str) -> bool:
        """Subscribe to stock data. Required before getting quotes."""
        try:
            ret, data = self._quote_ctx.subscribe(code, [SubType.QUOTE], subscribe_push=False)
            if ret == RET_OK:
                return True
            logger.warning(f"Failed to subscribe {code}: {data}")
            return False
        except Exception as e:
            logger.warning(f"Error subscribing {code}: {e}")
            return False

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
            # Subscribe first (required for NASDAQ Basic)
            self._subscribe(code)

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

    def _get_order_status(self, order_id: str) -> Optional[dict]:
        """Get order status by order ID."""
        try:
            ret, data = self._trd_ctx.order_list_query(
                order_id=order_id,
                trd_env=self.trd_env,
            )
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                return {
                    "order_id": str(row["order_id"]),
                    "status": row["order_status"],
                    "qty": int(row["qty"]),
                    "filled_qty": int(row.get("dealt_qty", 0)),
                    "avg_price": float(row.get("dealt_avg_price", 0)),
                }
            return None
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return None

    def _wait_for_order_fill(
        self,
        order_id: str,
        requested_qty: int,
        timeout: int = ORDER_POLL_TIMEOUT,
    ) -> dict:
        """
        Poll order status until filled or timeout.

        Returns:
            dict with filled_qty, avg_price, partial_fill, status
        """
        start_time = time.time()
        final_statuses = [
            OrderStatus.FILLED_ALL,
            OrderStatus.FILLED_PART,
            OrderStatus.CANCELLED_ALL,
            OrderStatus.CANCELLED_PART,
            OrderStatus.FAILED,
            OrderStatus.DELETED,
        ]

        while time.time() - start_time < timeout:
            status_info = self._get_order_status(order_id)
            if not status_info:
                time.sleep(ORDER_POLL_INTERVAL)
                continue

            order_status = status_info["status"]

            # Check if order reached final status
            if order_status in final_statuses:
                filled_qty = status_info["filled_qty"]
                avg_price = status_info["avg_price"]
                partial_fill = filled_qty > 0 and filled_qty < requested_qty

                logger.info(
                    f"Order {order_id} final status: {order_status}, "
                    f"filled: {filled_qty}/{requested_qty} @ ${avg_price:.2f}"
                )

                return {
                    "filled_qty": filled_qty,
                    "avg_price": avg_price,
                    "partial_fill": partial_fill,
                    "status": order_status,
                }

            time.sleep(ORDER_POLL_INTERVAL)

        # Timeout - get last known status
        logger.warning(f"Order {order_id} polling timeout after {timeout}s")
        status_info = self._get_order_status(order_id)
        if status_info:
            return {
                "filled_qty": status_info["filled_qty"],
                "avg_price": status_info["avg_price"],
                "partial_fill": status_info["filled_qty"] < requested_qty,
                "status": status_info["status"],
            }

        return {
            "filled_qty": 0,
            "avg_price": 0,
            "partial_fill": False,
            "status": "UNKNOWN",
        }

    def place_order(
        self,
        ticker: str,
        quantity: int,
        side: str,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> OrderResult:
        """
        Place an order and wait for fill confirmation.

        Args:
            ticker: Stock ticker (e.g., "BAC")
            quantity: Number of shares
            side: "BUY" or "SELL"
            order_type: "MARKET" or "LIMIT"
            price: Limit price (required for LIMIT orders)

        Returns:
            OrderResult with actual execution details.
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

                if order_id:
                    # Wait for order to fill and get actual execution details
                    fill_info = self._wait_for_order_fill(order_id, quantity)

                    filled_qty = fill_info["filled_qty"]
                    avg_price = fill_info["avg_price"]
                    partial_fill = fill_info["partial_fill"]

                    if filled_qty > 0:
                        logger.info(
                            f"Order executed: {side} {filled_qty}/{quantity} {ticker} @ ${avg_price:.2f}"
                        )
                        return OrderResult(
                            success=True,
                            order_id=order_id,
                            price=avg_price,
                            quantity=quantity,
                            filled_quantity=filled_qty,
                            partial_fill=partial_fill,
                            message=f"Filled {filled_qty}/{quantity}" if partial_fill else None,
                        )
                    else:
                        logger.error(f"Order {order_id} not filled: {fill_info['status']}")
                        return OrderResult(
                            success=False,
                            order_id=order_id,
                            filled_quantity=0,
                            message=f"Order not filled: {fill_info['status']}",
                        )
                else:
                    # Fallback if no order_id (shouldn't happen)
                    filled_price = self.get_quote(ticker)
                    return OrderResult(
                        success=True,
                        price=filled_price,
                        quantity=quantity,
                        filled_quantity=quantity,
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
