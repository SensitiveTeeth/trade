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

    def _fetch_ticker_history(self, ticker: str) -> Optional[dict]:
        """
        Fetch historical scores for a ticker (without date param).

        Returns dict with dates as keys, e.g.:
        {"2026-01-14": {"aiscore": 10, "technical": 10, ...}, ...}
        """
        params = {"ticker": ticker}

        try:
            response = self.session.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and data:
                return data
            return None

        except requests.exceptions.Timeout:
            logger.error(f"Danelfin API timeout for {ticker}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Danelfin API HTTP error for {ticker}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Danelfin API request error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"Danelfin API parse error for {ticker}: {e}")

        return None

    def get_score(self, ticker: str, date: Optional[str] = None) -> Optional[DanelfinScore]:
        """
        Get AI score for a ticker.

        Fetches historical data and returns the most recent score (or score for specific date).

        Args:
            ticker: Stock ticker symbol (e.g., "BAC")
            date: Date in YYYY-MM-DD format. If None, returns the most recent available.

        Returns:
            DanelfinScore object or None if failed.
        """
        history = self._fetch_ticker_history(ticker)
        if not history:
            logger.warning(f"No Danelfin data found for {ticker}")
            return None

        # If specific date requested, try to find it
        if date and date in history:
            scores = history[date]
            return DanelfinScore(
                ticker=ticker,
                ai_score=scores.get("aiscore", 0),
                fundamental_score=scores.get("fundamental", 0),
                technical_score=scores.get("technical", 0),
                sentiment_score=scores.get("sentiment", 0),
                target_price=scores.get("target_price"),
                date=date,
            )

        # Otherwise, get the most recent date (dates are sorted desc in response)
        # Sort dates to ensure we get the latest
        sorted_dates = sorted(history.keys(), reverse=True)

        for check_date in sorted_dates[:MAX_LOOKBACK_DAYS + 1]:
            scores = history[check_date]
            if date and check_date != date:
                logger.info(f"Using {ticker} data from {check_date} (latest available)")
            return DanelfinScore(
                ticker=ticker,
                ai_score=scores.get("aiscore", 0),
                fundamental_score=scores.get("fundamental", 0),
                technical_score=scores.get("technical", 0),
                sentiment_score=scores.get("sentiment", 0),
                target_price=scores.get("target_price"),
                date=check_date,
            )

        logger.warning(f"No recent Danelfin data found for {ticker}")
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

    def get_top_stocks(self, ai_score: int = 10, date: Optional[str] = None) -> list[DanelfinScore]:
        """
        Get all stocks with specified AI Score using bulk query.

        Args:
            ai_score: Filter by AI Score (default 10 for highest)
            date: Date in YYYY-MM-DD format. If None, tries recent dates.

        Returns:
            List of DanelfinScore objects for stocks matching the AI score.
        """
        start_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()

        for days_back in range(MAX_LOOKBACK_DAYS + 1):
            check_date = start_date - timedelta(days=days_back)
            date_str = check_date.strftime("%Y-%m-%d")

            results = self._fetch_top_stocks_by_score(date_str, ai_score)
            if results:
                if days_back > 0:
                    logger.info(f"Using top stocks data from {date_str} (latest available)")
                return results

        logger.warning(f"No AI Score {ai_score} stocks found in the last {MAX_LOOKBACK_DAYS} days")
        return []

    def _fetch_top_stocks_by_score(self, date: str, ai_score: int) -> list[DanelfinScore]:
        """
        Fetch all stocks with specified AI Score for a date.

        Response format: {"2026-01-14": {"AGI": {...}, "BAC": {...}, ...}}
        """
        params = {"date": date, "aiscore": ai_score}

        try:
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Response format: {date: {ticker: {scores}, ...}}
            if isinstance(data, dict) and date in data:
                date_data = data[date]
                results = []
                for ticker, scores in date_data.items():
                    results.append(DanelfinScore(
                        ticker=ticker,
                        ai_score=scores.get("aiscore", 0),
                        fundamental_score=scores.get("fundamental", 0),
                        technical_score=scores.get("technical", 0),
                        sentiment_score=scores.get("sentiment", 0),
                        target_price=scores.get("target_price"),
                        date=date,
                    ))
                logger.info(f"Found {len(results)} stocks with AI Score {ai_score} on {date}")
                return results
            return []

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return []
            logger.error(f"Danelfin API HTTP error for top stocks: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Danelfin API request error for top stocks: {e}")
        except Exception as e:
            logger.error(f"Danelfin API parse error for top stocks: {e}")

        return []


# Singleton instance
danelfin_client = DanelfinClient()
