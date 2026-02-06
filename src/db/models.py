from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EarningsCalendar(Base):
    __tablename__ = "earnings_calendar"
    __table_args__ = (UniqueConstraint("ticker", "earnings_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    market_cap: Mapped[int | None] = mapped_column(BigInteger)
    sector: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="SEC_EDGAR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SecEvent(Base):
    __tablename__ = "sec_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)
    event_description: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=0)
    red_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonitoringList(Base):
    __tablename__ = "monitoring_list"
    __table_args__ = (UniqueConstraint("ticker", "run_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(20))
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PremarketData(Base):
    __tablename__ = "premarket_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    premarket_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    premarket_volume: Mapped[int | None] = mapped_column(BigInteger)
    avg_volume_14d: Mapped[int | None] = mapped_column(BigInteger)
    volume_ratio: Mapped[float | None] = mapped_column(Numeric(8, 4))
    atr_5d: Mapped[float | None] = mapped_column(Numeric(12, 4))
    sector: Mapped[str | None] = mapped_column(String(100))
    sector_change: Mapped[float | None] = mapped_column(Numeric(8, 6))
    market_sentiment: Mapped[str | None] = mapped_column(String(20))
    sp500_change: Mapped[float | None] = mapped_column(Numeric(8, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    final_score: Mapped[int | None] = mapped_column(Integer)
    recommendation: Mapped[str | None] = mapped_column(String(10))
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    volume_score: Mapped[int | None] = mapped_column(Integer)
    volatility_score: Mapped[int | None] = mapped_column(Integer)
    market_score: Mapped[int | None] = mapped_column(Integer)
    sector_score: Mapped[int | None] = mapped_column(Integer)
    sec_score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OpenPosition(Base):
    __tablename__ = "open_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    position_size: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_loss_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    target_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TradeHistory(Base):
    __tablename__ = "trade_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    exit_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    position_size: Mapped[int | None] = mapped_column(Integer)
    pnl_pct: Mapped[float | None] = mapped_column(Numeric(8, 6))
    pnl_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    reason: Mapped[str | None] = mapped_column(String(50))
    entry_date: Mapped[datetime | None] = mapped_column(DateTime)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_data: Mapped[dict | None] = mapped_column(JSONB)
    output_data: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
