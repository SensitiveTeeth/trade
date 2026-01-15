"""Main entry point for the trading system."""

import logging
import os
import signal
import sys
import time
from pathlib import Path

import schedule

from config import config
from database import init_database
from futu_trader import futu_trader
from telegram_bot import telegram_notifier
from strategy import trading_strategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/trading.log"),
    ],
)
logger = logging.getLogger(__name__)

# Set timezone to Hong Kong
os.environ["TZ"] = "Asia/Hong_Kong"
time.tzset()


def setup_signal_handlers() -> None:
    """Setup graceful shutdown handlers."""

    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received")
        telegram_notifier.notify_shutdown()
        futu_trader.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)


def setup_schedule() -> None:
    """Setup scheduled tasks."""
    # Daily AI score check (before US market open, HKT 21:00)
    schedule.every().day.at(config.DAILY_CHECK_TIME).do(trading_strategy.run_daily_check)

    # Daily summary (after US market close, HKT 05:00)
    schedule.every().day.at(config.DAILY_SUMMARY_TIME).do(trading_strategy.run_daily_summary)

    # Price check every N minutes during market hours
    schedule.every(config.PRICE_CHECK_INTERVAL_MINUTES).minutes.do(
        trading_strategy.run_price_check
    )

    logger.info(f"Scheduled daily check at {config.DAILY_CHECK_TIME} HKT")
    logger.info(f"Scheduled daily summary at {config.DAILY_SUMMARY_TIME} HKT")
    logger.info(f"Scheduled price check every {config.PRICE_CHECK_INTERVAL_MINUTES} minutes")


def ensure_directories() -> None:
    """Ensure required directories exist."""
    Path("/app/data").mkdir(parents=True, exist_ok=True)
    Path("/app/logs").mkdir(parents=True, exist_ok=True)


def validate_config() -> bool:
    """Validate required configuration."""
    errors = []

    if not config.DANELFIN_API_KEY:
        errors.append("DANELFIN_API_KEY is not set")
    if not config.TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if not config.TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is not set")

    if errors:
        for error in errors:
            logger.error(f"Config error: {error}")
        return False
    return True


def connect_with_retry(max_retries: int = 10, retry_delay: int = 30) -> bool:
    """Connect to FutuOpenD with retry logic."""
    for attempt in range(1, max_retries + 1):
        logger.info(f"Connecting to FutuOpenD (attempt {attempt}/{max_retries})...")
        if futu_trader.connect():
            return True
        if attempt < max_retries:
            logger.warning(f"Connection failed, retrying in {retry_delay}s...")
            time.sleep(retry_delay)
    return False


def main() -> None:
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("Starting Trading System")
    logger.info("=" * 50)

    # Ensure directories exist
    ensure_directories()

    # Validate config
    logger.info("Validating configuration...")
    if not validate_config():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    # Initialize database
    logger.info("Initializing database...")
    init_database()

    # Connect to Futu with retry
    if not connect_with_retry():
        logger.error("Failed to connect to FutuOpenD after retries. Exiting.")
        telegram_notifier.notify_error("Failed to connect to FutuOpenD after multiple retries")
        sys.exit(1)

    # Setup signal handlers
    setup_signal_handlers()

    # Setup schedule
    setup_schedule()

    # Send startup notification
    mode = "SIMULATION" if config.IS_SIMULATION else "LIVE"
    logger.info(f"Trading mode: {mode}")
    telegram_notifier.notify_startup(config.IS_SIMULATION)

    # Sync positions with broker on startup
    logger.info("Syncing positions with broker...")
    trading_strategy.sync_positions_with_broker()

    # Run initial check (will skip if already ran today)
    logger.info("Running initial check...")
    trading_strategy.run_daily_check()

    # Main loop
    logger.info("Entering main loop...")
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            telegram_notifier.notify_error(f"Main loop error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
