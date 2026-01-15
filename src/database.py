"""SQLite database operations."""

import sqlite3
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from config import config


@contextmanager
def get_db_connection():
    """Get database connection context manager."""
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    """Initialize database tables."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ticker VARCHAR(10) NOT NULL,
                action VARCHAR(10) NOT NULL,
                quantity INTEGER NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                total_amount DECIMAL(12,2) NOT NULL,
                ai_score INTEGER,
                reason VARCHAR(100),
                order_id VARCHAR(50),
                status VARCHAR(20) DEFAULT 'FILLED'
            )
        """)

        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker VARCHAR(10) NOT NULL UNIQUE,
                quantity INTEGER NOT NULL,
                avg_cost DECIMAL(10,2) NOT NULL,
                entry_date DATETIME,
                entry_ai_score INTEGER,
                target_price DECIMAL(10,2),
                stop_loss DECIMAL(10,2)
            )
        """)

        # AI Score history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_score_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                ticker VARCHAR(10) NOT NULL,
                ai_score INTEGER,
                fundamental_score INTEGER,
                technical_score INTEGER,
                sentiment_score INTEGER,
                target_price DECIMAL(10,2),
                UNIQUE(date, ticker)
            )
        """)

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_score_date_ticker ON ai_score_history(date, ticker)")

        conn.commit()


def log_trade(
    ticker: str,
    action: str,
    quantity: int,
    price: float,
    ai_score: Optional[int] = None,
    reason: Optional[str] = None,
    order_id: Optional[str] = None,
) -> int:
    """Log a trade to database."""
    total_amount = quantity * price
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO trades (ticker, action, quantity, price, total_amount, ai_score, reason, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, action, quantity, price, total_amount, ai_score, reason, order_id),
        )
        conn.commit()
        return cursor.lastrowid


def add_position(
    ticker: str,
    quantity: int,
    avg_cost: float,
    ai_score: Optional[int] = None,
    target_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> None:
    """Add or update a position."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO positions (ticker, quantity, avg_cost, entry_date, entry_ai_score, target_price, stop_loss)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                avg_cost = (avg_cost * quantity + excluded.avg_cost * excluded.quantity) / (quantity + excluded.quantity)
            """,
            (ticker, quantity, avg_cost, datetime.now(), ai_score, target_price, stop_loss),
        )
        conn.commit()


def remove_position(ticker: str) -> None:
    """Remove a position."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
        conn.commit()


def update_position(ticker: str, quantity: int, avg_cost: float) -> None:
    """Update an existing position's quantity and avg_cost."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE positions SET quantity = ?, avg_cost = ? WHERE ticker = ?",
            (quantity, avg_cost, ticker),
        )
        conn.commit()


def get_position(ticker: str) -> Optional[dict]:
    """Get a single position."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_positions() -> list[dict]:
    """Get all positions."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions")
        return [dict(row) for row in cursor.fetchall()]


def get_position_count() -> int:
    """Get current position count."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM positions")
        return cursor.fetchone()[0]


def save_ai_score(
    ticker: str,
    ai_score: int,
    fundamental_score: Optional[int] = None,
    technical_score: Optional[int] = None,
    sentiment_score: Optional[int] = None,
    target_price: Optional[float] = None,
) -> None:
    """Save AI score history."""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_score_history (date, ticker, ai_score, fundamental_score, technical_score, sentiment_score, target_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, ticker) DO UPDATE SET
                ai_score = excluded.ai_score,
                fundamental_score = excluded.fundamental_score,
                technical_score = excluded.technical_score,
                sentiment_score = excluded.sentiment_score,
                target_price = excluded.target_price
            """,
            (today, ticker, ai_score, fundamental_score, technical_score, sentiment_score, target_price),
        )
        conn.commit()


def get_recent_trades(limit: int = 20) -> list[dict]:
    """Get recent trades."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
