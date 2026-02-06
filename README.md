# Trading Bot

Multi-agent earnings trading bot. Analyzes SEC filings, pre-market data, and executes trades via IBKR.

## Pipeline

```
05:00 AM  Agent-1 (Calendar) → Agent-2 (SEC Events) → Agent-3 (IBKR Setup)
07:30 AM  Agent-4 (Pre-Market Data)
10:00 AM  Agent-5 (Scoring) → Agent-6 (Validation) → BUY / HOLD / SKIP
10:15 AM  Monitor positions (stop-loss, take-profit, max hold)
04:00 PM  EOD report + cleanup
```

## Setup

```bash
# 1. Install dependencies
pip install -e .

# 2. Configure
cp .env.example .env
# Edit .env with your Supabase URL, LLM key, IBKR settings

# 3. Initialize database
python -m src.main
```

## Run

```bash
python -m src.main
```

## Docker

```bash
docker-compose up -d
```

## Stack

- Python 3.12 + SQLAlchemy + Alembic
- Supabase (PostgreSQL)
- MiniMax M2.1 via Chutes.ai (OpenAI-compatible)
- IBKR via ib_insync
- SEC EDGAR + Yahoo Finance (fallback)
- APScheduler for cron jobs
