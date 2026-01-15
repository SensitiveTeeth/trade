"""Configuration and environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # Danelfin API
    DANELFIN_API_KEY: str = os.getenv("DANELFIN_API_KEY", "")
    DANELFIN_API_URL: str = "https://apirest.danelfin.com/ranking"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Futu OpenD
    FUTU_HOST: str = os.getenv("FUTU_HOST", "127.0.0.1")
    FUTU_PORT: int = int(os.getenv("FUTU_PORT", "11111"))

    # Trading Config
    IS_SIMULATION: bool = os.getenv("IS_SIMULATION", "true").lower() == "true"
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "8"))

    # Watchlist - Default bank stocks
    WATCHLIST: list[str] = ["BAC", "FHN", "OZK", "NBTB", "SSB"]

    # Trading Strategy Thresholds
    BUY_SCORE_THRESHOLD: int = 10  # Buy when AI Score = 10
    SELL_SCORE_THRESHOLD: int = 7  # Sell when AI Score < 7
    TAKE_PROFIT_PCT: float = 0.15  # 15% take profit
    STOP_LOSS_PCT: float = 0.08  # 8% stop loss

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "/app/data/trading.db")

    # Schedule (Hong Kong Time)
    DAILY_CHECK_TIME: str = "21:00"  # Before US market open
    PRICE_CHECK_INTERVAL_MINUTES: int = 1


config = Config()
