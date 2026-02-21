"""
Database utilities — connection, schema init, logging helpers.
Uses PostgreSQL via psycopg2 + SQLAlchemy.
"""

import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, JSON, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import QueuePool

from config import DATABASE_URL, LOG_LEVEL

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("db_utils")

Base = declarative_base()
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)
SessionFactory = sessionmaker(bind=engine)


@contextmanager
def get_session() -> Session:
    """Context manager for DB sessions with auto-commit/rollback."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── ORM Models ───────────────────────────────────────────────

class EarningsCalendar(Base):
    __tablename__ = "earnings_calendar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    earnings_date = Column(String(20), nullable=False)
    is_confirmed = Column(Boolean, default=False)
    source = Column(String(50))
    market_cap = Column(Float, nullable=True)
    sector = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scan_date = Column(String(20), nullable=False)

    __table_args__ = (
        Index("ix_earnings_ticker_date", "ticker", "earnings_date"),
    )


class SecEvent(Base):
    __tablename__ = "sec_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    weight = Column(Integer, default=0)
    red_flag = Column(Boolean, default=False)
    filing_date = Column(String(20), nullable=True)
    total_score = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scan_date = Column(String(20), nullable=False)


class MonitoringList(Base):
    __tablename__ = "monitoring_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    sec_score = Column(Integer, default=0)
    source = Column(String(50))  # "earnings" or "sp500_filler"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scan_date = Column(String(20), nullable=False)


class PremarketData(Base):
    __tablename__ = "premarket_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    premarket_price = Column(Float, nullable=True)
    premarket_volume = Column(Float, nullable=True)
    avg_volume_14d = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    atr_5d = Column(Float, nullable=True)
    sector = Column(String(100), nullable=True)
    sector_etf_change = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scan_date = Column(String(20), nullable=False)


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    final_score = Column(Integer, nullable=False)
    recommendation = Column(String(10), nullable=False)  # BUY / HOLD / SKIP
    breakdown = Column(JSON, nullable=True)
    entry_price = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scan_date = Column(String(20), nullable=False)


class OpenPosition(Base):
    __tablename__ = "open_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    target_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    max_hold_until = Column(DateTime, nullable=False)
    scoring_id = Column(Integer, ForeignKey("scoring_results.id"), nullable=True)
    status = Column(String(20), default="open")  # open, closed, force_closed
    predicted_gain_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=False)
    pnl_amount = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False)
    exit_reason = Column(String(50))  # target_hit, stop_hit, max_hold, manual
    scoring_id = Column(Integer, ForeignKey("scoring_results.id"), nullable=True)
    predicted_gain_pct = Column(Float, nullable=True)
    actual_gain_pct = Column(Float, nullable=True)
    prediction_accuracy = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # started, success, error, warning
    message = Column(Text, nullable=True)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SelfLearningLog(Base):
    __tablename__ = "self_learning_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trade_history.id"), nullable=False)
    ticker = Column(String(10), nullable=False)
    predicted_gain_pct = Column(Float, nullable=True)
    actual_gain_pct = Column(Float, nullable=True)
    prediction_error = Column(Float, nullable=True)
    chain_analysis = Column(JSON, nullable=True)  # Full agent chain snapshot
    improvement_suggestions = Column(JSON, nullable=True)
    suggested_skill_code = Column(Text, nullable=True)
    user_approved = Column(Boolean, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ─── Schema Init ──────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    logger.info("Database schema initialized successfully")


def log_agent(agent_name: str, status: str, message: str = "",
              input_data: dict = None, output_data: dict = None,
              execution_time_ms: int = None):
    """Log an agent execution step."""
    with get_session() as session:
        entry = AgentLog(
            agent_name=agent_name,
            status=status,
            message=message,
            input_data=input_data,
            output_data=output_data,
            execution_time_ms=execution_time_ms,
        )
        session.add(entry)
    logger.info(f"[{agent_name}] {status}: {message}")


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
