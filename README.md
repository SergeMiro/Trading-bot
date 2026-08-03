# Trading Bot

**A multi-agent earnings trading bot.** It reads the earnings calendar and SEC filings,
scores the candidates before the open, lets a separate agent veto the decision, and only
then places an order through Interactive Brokers — then manages the exit automatically.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-migrations-6BA81E)](https://alembic.sqlalchemy.org/)
[![Postgres](https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?logo=postgresql&logoColor=white)](https://supabase.com/)
[![IBKR](https://img.shields.io/badge/IBKR-ib__insync-D81222)](https://interactivebrokers.github.io/)
[![APScheduler](https://img.shields.io/badge/APScheduler-NY_trading_clock-4B8BBE)](https://apscheduler.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

> ⚠️ **Personal research lab — explicitly not financial advice.** This code places real
> orders through a real brokerage account. Run it against IBKR paper trading first, and
> understand every risk parameter before pointing it at live capital. No warranty of any
> kind.

---

## Table of contents

- [How it works](#how-it-works)
- [The agents](#the-agents)
- [Data sources](#data-sources)
- [Scoring and risk](#scoring-and-risk)
- [Complete tech stack](#complete-tech-stack)
- [Data model](#data-model)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Two deployment shapes](#two-deployment-shapes)
- [Project structure](#project-structure)
- [Disclaimer](#disclaimer)

## How it works

Six agents on a clock, rather than one loop that does everything. The trading day is a
schedule, not a code path — every step is a separate agent with one job and one output, and
every decision is written to the database before the next step reads it.

```
America/New_York, Monday–Friday

05:00  morning pipeline    Agent-1 Calendar → Agent-2 SEC Events → Agent-3 IBKR Setup
07:30  premarket pipeline  Agent-4 Pre-Market Data
10:00  trading pipeline    Agent-5 Scoring → Agent-6 Validation → BUY / HOLD / SKIP
10:15  monitor loop        stop-loss · take-profit · max-hold enforcement
16:00  end of day          report + cleanup
```

The order matters: nothing is bought before a *second, independent* agent has had the
chance to reject it, and no position is left to a discretionary exit decision.

## The agents

| # | Agent | Module | Job |
| --- | --- | --- | --- |
| 1 | Calendar | `agents/calendar_agent.py` | Which companies report, and when |
| 2 | SEC events | `agents/event_detector.py` | Read the filings themselves for material events |
| 3 | IBKR setup | `agents/ibkr_setup.py` | Configure broker-side monitoring for the shortlist |
| 4 | Pre-market | `agents/premarket_agent.py` | Volume, ATR, sentiment, sector strength |
| 5 | Scoring | `agents/scoring_agent.py` | One comparable number per candidate |
| 6 | Validation | `agents/validation_agent.py` | An independent veto before any order is placed |

All six inherit from `BaseAgent` (`agents/base.py`), which times each run, catches failures
and writes an `agent_logs` row — so a bad week can be read back rather than guessed at.
`pipeline/orchestrator.py` sequences them; `scheduler/jobs.py` puts them on the clock.

## Data sources

Three independent feeds, so a single bad source cannot drive a trade:

- **SEC EDGAR** (`services/sec_client.py`) — the filing is read at the source, with a
  declared `SEC_USER_AGENT` as EDGAR requires
- **Yahoo Finance** (`services/yahoo_client.py`, via `yfinance`) — prices and pre-market
  movement
- **Interactive Brokers** (`services/ibkr_client.py`, via `ib_insync`) — orders, positions
  and the account's own view of its state

## Scoring and risk

The scoring engine ranks candidates; the risk rules are deliberately separate from it
(`trading/risk.py`), so changing how a candidate is judged never silently changes how much
is put at stake.

Position size is derived from risk-per-trade and the stop distance, not from a fixed lot:

```
risk_amount    = account_balance × RISK_PER_TRADE   (default 2 %)
risk_per_share = entry_price     × STOP_LOSS        (default 5 %)
shares         = risk_amount ÷ risk_per_share
```

After entry, `trading/monitor.py` enforces the exit — take-profit (default +8 %), stop-loss
(default −5 %) and a maximum holding period (default 7 days). `trading/executor.py` places
the orders; `trading/report.py` produces the end-of-day summary of what was done and why.

Decisions are thresholded rather than binary: score ≥ `SCORE_THRESHOLD_BUY` buys, ≥
`SCORE_THRESHOLD_HOLD` holds, anything below is skipped.

## Complete tech stack

| Area | Technologies |
| --- | --- |
| Language | Python 3.12+ |
| Persistence | [SQLAlchemy](https://www.sqlalchemy.org/) 2.0 · [Alembic](https://alembic.sqlalchemy.org/) migrations · `psycopg2-binary` |
| Database | PostgreSQL, hosted on [Supabase](https://supabase.com/) |
| Configuration | `pydantic-settings` — typed settings from the environment |
| Scheduling | [APScheduler](https://apscheduler.readthedocs.io/) with `CronTrigger`, timezone-aware (`America/New_York`), `pytz` |
| Brokerage | [Interactive Brokers](https://www.interactivebrokers.com/) via [`ib_insync`](https://ib-insync.readthedocs.io/) |
| Market data | [`yfinance`](https://github.com/ranaroussi/yfinance) (Yahoo Finance), SEC EDGAR over `httpx` |
| LLM | Any OpenAI-compatible endpoint via the `openai` SDK — default **MiniMax M2.1** through [Chutes.ai](https://chutes.ai/) |
| Resilience | [`tenacity`](https://tenacity.readthedocs.io/) retries around every external call |
| Logging | [`structlog`](https://www.structlog.org/) structured events, plus an `agent_logs` table |
| Testing | pytest · pytest-cov |
| Packaging | `pyproject.toml` (setuptools), installable with `pip install -e .` |
| Delivery | Docker · Docker Compose (`restart: unless-stopped`) |
| Alternative runtime | OpenClaw agent gateway — YAML skills, crons and webhooks (see below), with pandas/numpy for the analysis scripts and Telegram as the control channel |

**Model choice, deliberately.** The reasoning steps run on an inexpensive open model behind
an OpenAI-compatible endpoint: the loop runs every trading day, and a premium model per
decision would cost more than the edge it buys. Swapping provider is three environment
variables (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`), not a code change.

## Data model

Eight tables (`src/db/models.py`), migrated with Alembic:

| Table | Holds |
| --- | --- |
| `earnings_calendar` | Who reports, and when |
| `sec_events` | Material events extracted from filings |
| `monitoring_list` | The current shortlist, capped by `MAX_MONITORING_LINES` |
| `premarket_data` | Volume, ATR, sentiment, sector strength per candidate |
| `scoring_results` | The score behind every decision |
| `open_positions` | Live positions with their stop, target and deadline |
| `trade_history` | Every fill, closed out |
| `agent_logs` | Every agent run: input, output, duration, failure |

## Getting started

### Prerequisites

- Python 3.12+
- A PostgreSQL database (Supabase works out of the box)
- Interactive Brokers **TWS or IB Gateway** running and reachable — start with the paper
  account on port `7497`
- An API key for any OpenAI-compatible LLM endpoint
- An email address for the SEC EDGAR user agent (EDGAR requires one)

### Install

```bash
git clone https://github.com/SergeMiro/Trading-bot.git
cd Trading-bot
pip install -e .            # add [dev] for pytest
```

### Configure

```bash
cp .env.example .env
# then edit .env — see Configuration below
```

### Migrate and run

```bash
alembic upgrade head        # create the schema
python -m src.main          # start the scheduler
```

### Docker

```bash
docker-compose up -d        # logs land in ./logs
```

### Tests

```bash
pytest
```

## Configuration

Everything is environment-driven and validated by `pydantic-settings` (`src/config.py`).

**Connections**

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL / Supabase connection string |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Any OpenAI-compatible provider |
| `SEC_USER_AGENT` | `Your Name your@email.com` — required by SEC EDGAR |
| `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` | TWS / IB Gateway (`7497` paper, `7496` live) |

**Trading and risk** — these are the numbers that decide how much of the account is at risk.
Read them before the first run.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MIN_MARKET_CAP` | `500000000` | Smallest company considered (USD) |
| `MAX_MONITORING_LINES` | `100` | Ceiling on simultaneously watched tickers |
| `SCORE_THRESHOLD_BUY` | `70` | Score at or above which a buy is placed |
| `SCORE_THRESHOLD_HOLD` | `50` | Score at or above which a position is held |
| `TARGET_GAIN` | `0.08` | Take-profit, +8 % |
| `STOP_LOSS` | `0.05` | Stop-loss, −5 % |
| `MAX_HOLD_DAYS` | `7` | Forced exit after seven days |
| `RISK_PER_TRADE` | `0.02` | Fraction of the account risked per trade, 2 % |

## Two deployment shapes

The repository carries the same strategy in two runtimes:

**1. Standalone Python service — `src/`**
The package described above: six agents, an orchestrator and APScheduler, run as
`python -m src.main` or under Docker Compose. Self-contained, no external agent platform.

**2. OpenClaw agent gateway — `openclaw/`**
The same pipeline expressed as a hierarchical agent system on the
[OpenClaw](https://openclaw.ai/) gateway, driven from Telegram:

- `openclaw.json` — a `master_orchestrator` with one sub-agent per pipeline stage, each with
  its own system prompt in `agents/*.md`, a narrow tool allow-list and `temperature: 0.0`
- `crons/trading-bot-schedule.yaml` — the trading day as declarative UTC cron entries with
  per-job `enabled` flags and preconditions
- `skills/trading-skills.yaml`, `skills/ibkr-tools.yaml` — typed tool definitions
  (`fetch_earnings_calendar`, `scan_sec_events`, `calculate_scores`, `execute_buy`,
  `ibkr_account_summary`, `ibkr_cancel_all_orders`, …)
- `webhooks/sec-webhook.yaml` — push-driven SEC filing ingestion, alongside
  `scripts/sec_rss_monitor.py`
- `scripts/` — the executable side: `scoring_engine.py`, `execute_trade.py`,
  `position_monitor.py`, `daily_report.py`, `self_learning.py` (yesterday's outcomes feed
  today's weights), `healthcheck.sh`, plus pandas/numpy analysis helpers
- Deployment notes in [`openclaw/DEPLOY.md`](openclaw/DEPLOY.md), schema in
  `openclaw/db/init.sql`

## Project structure

```
src/
  main.py               entry point — migrate, wire, start the scheduler
  config.py             pydantic-settings configuration
  agents/               base + 6 pipeline agents
  pipeline/
    orchestrator.py     sequences the agents, stage by stage
  scheduler/
    jobs.py             APScheduler cron jobs on the New York clock
  services/
    sec_client.py       SEC EDGAR
    yahoo_client.py     Yahoo Finance / yfinance
    ibkr_client.py      Interactive Brokers via ib_insync
    llm_client.py       OpenAI-compatible client, text and JSON modes
  trading/
    executor.py         order placement
    monitor.py          stop-loss · take-profit · max-hold
    risk.py             position sizing
    report.py           end-of-day report
  db/
    models.py           8 SQLAlchemy models
    session.py          engine and session factory
alembic/                migration environment
openclaw/               OpenClaw gateway deployment (agents, crons, skills, webhooks, scripts)
tests/                  pytest suite
docs/                   pipeline walkthrough
Dockerfile, docker-compose.yml
```

## Disclaimer

This is a personal research project published so the engineering can be read. It is **not
investment advice, not a recommendation, and not a product.** Automated trading can lose
money quickly, including more than intended if a parameter is wrong or a data feed lies.
Use IBKR paper trading, read `trading/risk.py` and every value in
[Configuration](#configuration) before considering live capital, and accept that any
consequence of running it is yours.

---

Built by **Sergiy Mirochnyk** · [smiro.dev](https://smiro.dev)
