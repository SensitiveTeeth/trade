"""Danelfin API client."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

import requests

from config import config

logger = logging.getLogger(__name__)

# Maximum days to look back for available data
MAX_LOOKBACK_DAYS = 5


@dataclass
class DanelfinScore:
    """Danelfin AI score data."""

    ticker: str
    ai_score: int
    fundamental_score: int
    technical_score: int
    sentiment_score: int
    target_price: Optional[float]
    date: str


class DanelfinClient:
    """Client for Danelfin API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.DANELFIN_API_KEY
        self.base_url = config.DANELFIN_API_URL
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": self.api_key})

    def _fetch_score_for_date(self, ticker: str, date: str) -> Optional[DanelfinScore]:
        """Fetch score for a specific date. Returns None if not found."""
        params = {"ticker": ticker, "date": date}

        try:
            response = self.session.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            return DanelfinScore(
                ticker=ticker,
                ai_score=data.get("aiscore", 0),
                fundamental_score=data.get("fundamental", 0),
                technical_score=data.get("technical", 0),
                sentiment_score=data.get("sentiment", 0),
                target_price=data.get("target_price"),
                date=date,
            )

        except requests.exceptions.Timeout:
            logger.error(f"Danelfin API timeout for {ticker}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Data not available for this date, not an error
                return None
            logger.error(f"Danelfin API HTTP error for {ticker}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Danelfin API request error for {ticker}: {e}")
        except (KeyError, ValueError) as e:
            logger.error(f"Danelfin API parse error for {ticker}: {e}")

        return None

    def get_score(self, ticker: str, date: Optional[str] = None) -> Optional[DanelfinScore]:
        """
        Get AI score for a ticker.

        If data for the requested date is not available, automatically tries
        previous days up to MAX_LOOKBACK_DAYS to find the most recent data.

        Args:
            ticker: Stock ticker symbol (e.g., "BAC")
            date: Date in YYYY-MM-DD format. Defaults to today.

        Returns:
            DanelfinScore object or None if failed.
        """
        start_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()

        for days_back in range(MAX_LOOKBACK_DAYS + 1):
            check_date = start_date - timedelta(days=days_back)
            date_str = check_date.strftime("%Y-%m-%d")

            score = self._fetch_score_for_date(ticker, date_str)
            if score:
                if days_back > 0:
                    logger.info(f"Using {ticker} data from {date_str} (latest available)")
                return score

        logger.warning(f"No Danelfin data found for {ticker} in the last {MAX_LOOKBACK_DAYS} days")
        return None

    def get_scores_batch(self, tickers: list[str], date: Optional[str] = None) -> dict[str, DanelfinScore]:
        """
        Get AI scores for multiple tickers.

        Args:
            tickers: List of stock ticker symbols
            date: Date in YYYY-MM-DD format. Defaults to today.

        Returns:
            Dictionary mapping ticker to DanelfinScore.
        """
        results = {}
        for ticker in tickers:
            score = self.get_score(ticker, date)
            if score:
                results[ticker] = score
        return results


# Singleton instance
danelfin_client = DanelfinClient()
