"""Agent-3: IBKR Setup — Sort by score, take top 100, configure IBKR monitoring."""

from datetime import date

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.agents.base import BaseAgent
from src.config import settings
from src.db.models import MonitoringList
from src.db.session import SessionLocal
from src.services import ibkr_client, yahoo_client

logger = structlog.get_logger()


class IBKRSetupAgent(BaseAgent):
    name = "ibkr_setup_agent"

    def execute(self, input_data: dict) -> dict:
        companies = input_data.get("companies", [])

        # Step 1: Filter out red flags
        filtered = [c for c in companies if not c.get("red_flag", False)]

        # Step 2: Sort by total_score descending
        sorted_companies = sorted(filtered, key=lambda x: x.get("total_score", 0), reverse=True)

        # Step 3: Take top N
        max_lines = settings.max_monitoring_lines
        top = sorted_companies[:max_lines]

        # Step 4: Fill remaining slots with S&P500 tickers
        if len(top) < max_lines:
            existing_tickers = {c["ticker"] for c in top}
            try:
                sp500 = yahoo_client.get_sp500_tickers()
                for ticker in sp500:
                    if len(top) >= max_lines:
                        break
                    if ticker not in existing_tickers:
                        top.append({
                            "ticker": ticker,
                            "total_score": 0,
                            "source": "SP500_FILLER",
                        })
                        existing_tickers.add(ticker)
            except Exception as e:
                logger.warning("sp500_filler_error", error=str(e))

        tickers = [c["ticker"] for c in top]
        earnings_count = len([c for c in top if c.get("total_score", 0) > 0])

        # Step 5: Request historical data from IBKR
        historical_status = self._setup_ibkr_monitoring(tickers)

        # Step 6: Save monitoring list to DB
        self._save_to_db(top)

        return {
            "result": {
                "tickers": tickers,
                "ibkr_config": {
                    "contract_type": "STK",
                    "exchange": "SMART",
                    "currency": "USD",
                    "historical_period": "30 D",
                    "bar_size": "1 hour",
                },
            },
            "metadata": {
                "total_lines": len(tickers),
                "earnings_candidates": earnings_count,
                "sp500_filler": len(tickers) - earnings_count,
                "ibkr_status": historical_status,
            },
        }

    def _setup_ibkr_monitoring(self, tickers: list[str]) -> str:
        """Request historical data from IBKR for each ticker."""
        success = 0
        errors = 0

        for ticker in tickers:
            try:
                ibkr_client.get_historical_bars(ticker, duration="30 D", bar_size="1 hour")
                success += 1
            except Exception as e:
                logger.debug("ibkr_historical_error", ticker=ticker, error=str(e))
                errors += 1

        logger.info("ibkr_setup_complete", success=success, errors=errors)
        return f"OK ({success}/{len(tickers)} loaded)"

    def _save_to_db(self, companies: list[dict]):
        """Save monitoring list to database."""
        session = SessionLocal()
        try:
            for c in companies:
                stmt = pg_insert(MonitoringList).values(
                    ticker=c["ticker"],
                    total_score=c.get("total_score", 0),
                    source=c.get("source", "EARNINGS"),
                    run_date=date.today(),
                ).on_conflict_do_update(
                    index_elements=["ticker", "run_date"],
                    set_={"total_score": c.get("total_score", 0)},
                )
                session.execute(stmt)
            session.commit()
            logger.info("monitoring_list_saved", count=len(companies))
        except Exception as e:
            session.rollback()
            logger.error("monitoring_list_save_error", error=str(e))
        finally:
            session.close()
