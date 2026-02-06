"""Agent-1: Calendar Agent — Collects earnings calendar for next 30 days."""

import json
from datetime import date, datetime, timedelta

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.agents.base import BaseAgent
from src.config import settings
from src.db.models import EarningsCalendar
from src.db.session import SessionLocal
from src.services import sec_client, yahoo_client

logger = structlog.get_logger()


class CalendarAgent(BaseAgent):
    name = "calendar_agent"

    def execute(self, input_data: dict) -> dict:
        date_start = datetime.now()
        date_end = date_start + timedelta(days=30)

        # Step 1: Get earnings from SEC or Yahoo fallback
        companies = self._fetch_earnings(date_start, date_end)

        # Step 2: Filter through LLM
        if companies:
            companies = self._filter_with_llm(companies)

        # Step 3: Save to DB
        self._save_to_db(companies)

        return {
            "analysis": f"Found {len(companies)} companies with earnings in next 30 days",
            "result": {
                "source": companies[0]["source"] if companies else "NONE",
                "count": len(companies),
                "companies": companies,
            },
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "date_range": f"{date_start.date()} to {date_end.date()}",
            },
        }

    def _fetch_earnings(self, date_start: datetime, date_end: datetime) -> list[dict]:
        """Fetch earnings calendar — SEC primary, Yahoo fallback."""
        companies = []

        # Try getting a broad list of companies with upcoming earnings via Yahoo
        # (SEC doesn't have a centralized earnings calendar endpoint)
        try:
            companies = self._fetch_from_yahoo_bulk(date_start, date_end)
            logger.info("calendar_yahoo_bulk", count=len(companies))
        except Exception as e:
            logger.warning("calendar_yahoo_bulk_error", error=str(e))

        return companies

    def _fetch_from_yahoo_bulk(self, date_start: datetime, date_end: datetime) -> list[dict]:
        """Fetch earnings from Yahoo Finance for known tickers."""
        # Get S&P500 list as base universe
        try:
            sp500 = yahoo_client.get_sp500_tickers()
        except Exception:
            sp500 = []
            logger.warning("sp500_list_fetch_failed")

        companies = []
        for ticker in sp500:
            try:
                info = yahoo_client.get_stock_info(ticker)
                market_cap = info.get("market_cap", 0)
                if market_cap < settings.min_market_cap:
                    continue

                earnings = yahoo_client.get_earnings_calendar(ticker)
                for e in earnings:
                    earnings_date = datetime.strptime(e["earnings_date"], "%Y-%m-%d").date()
                    if date_start.date() <= earnings_date <= date_end.date():
                        companies.append({
                            "ticker": ticker,
                            "company_name": info.get("company_name", ""),
                            "earnings_date": str(earnings_date),
                            "is_confirmed": True,
                            "market_cap": market_cap,
                            "sector": info.get("sector", ""),
                            "source": "YAHOO_FALLBACK",
                        })
                        break  # One entry per ticker
            except Exception as e:
                logger.debug("calendar_ticker_error", ticker=ticker, error=str(e))
                continue

        return companies

    def _filter_with_llm(self, companies: list[dict]) -> list[dict]:
        """Use LLM to validate and filter earnings list."""
        system_prompt = (
            "You are an earnings calendar agent. "
            "Your task: validate the list of companies with upcoming earnings. "
            "Keep only companies with confirmed dates and market cap > $500M. "
            "Return a JSON array of valid companies with the same fields."
        )
        user_prompt = (
            f"Here are {len(companies)} companies with upcoming earnings:\n"
            f"{json.dumps(companies[:50], indent=2)}\n\n"  # Limit to 50 for token budget
            "Filter and return valid companies as a JSON array."
        )

        try:
            result = self.call_llm_json(system_prompt, user_prompt)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "companies" in result:
                return result["companies"]
            return companies
        except Exception as e:
            logger.warning("calendar_llm_filter_error", error=str(e))
            return companies

    def _save_to_db(self, companies: list[dict]):
        """Save earnings calendar to database."""
        session = SessionLocal()
        try:
            for c in companies:
                stmt = pg_insert(EarningsCalendar).values(
                    ticker=c["ticker"],
                    company_name=c.get("company_name", ""),
                    earnings_date=c["earnings_date"],
                    is_confirmed=c.get("is_confirmed", False),
                    market_cap=c.get("market_cap"),
                    sector=c.get("sector", ""),
                    source=c.get("source", "SEC_EDGAR"),
                ).on_conflict_do_update(
                    index_elements=["ticker", "earnings_date"],
                    set_={"market_cap": c.get("market_cap"), "source": c.get("source")},
                )
                session.execute(stmt)
            session.commit()
            logger.info("calendar_saved", count=len(companies))
        except Exception as e:
            session.rollback()
            logger.error("calendar_save_error", error=str(e))
            raise
        finally:
            session.close()
