"""Agent-2: Event Detector — Analyzes SEC filings for each company."""

import json
from datetime import date

import structlog

from src.agents.base import BaseAgent
from src.db.models import SecEvent
from src.db.session import SessionLocal
from src.services import sec_client

logger = structlog.get_logger()

# CIK mapping for common tickers (in production, use a full mapping or SEC's company tickers file)
TICKER_TO_CIK = {
    "AAPL": "320193",
    "MSFT": "789019",
    "GOOGL": "1652044",
    "AMZN": "1018724",
    "NVDA": "1045810",
    "META": "1326801",
    "TSLA": "1318605",
    "AMD": "2488",
    "NFLX": "1065280",
    "JPM": "19617",
}


class EventDetectorAgent(BaseAgent):
    name = "event_detector_agent"

    def execute(self, input_data: dict) -> dict:
        companies = input_data.get("companies", [])
        results = []

        for company in companies:
            ticker = company["ticker"]
            company_result = self._analyze_company(ticker)
            results.append(company_result)

        # Save to DB
        self._save_to_db(results)

        return {
            "analysis": f"Analyzed {len(results)} companies for SEC events",
            "result": {"companies": results},
        }

    def _analyze_company(self, ticker: str) -> dict:
        """Analyze SEC filings for a single company."""
        events = []
        total_score = 0
        red_flag = False

        cik = TICKER_TO_CIK.get(ticker)
        if not cik:
            # Try to get CIK from SEC
            cik = self._lookup_cik(ticker)

        if not cik:
            logger.warning("event_detector_no_cik", ticker=ticker)
            return {
                "ticker": ticker,
                "events": [],
                "total_score": 0,
                "red_flag": False,
            }

        try:
            filings = sec_client.get_recent_filings(cik, days=14)
        except Exception as e:
            logger.warning("event_detector_sec_error", ticker=ticker, error=str(e))
            return {
                "ticker": ticker,
                "events": [],
                "total_score": 0,
                "red_flag": False,
            }

        for filing in filings:
            form_type = filing["form_type"]

            if form_type in ("4", "4/A"):
                # Insider transaction — use LLM to determine buy/sell
                event = self._analyze_form4(ticker, filing)
                if event:
                    events.append(event)
                    total_score += event["weight"]

            elif form_type in ("8-K", "8-K/A"):
                # Material event — use LLM for sentiment
                event = self._analyze_8k(ticker, filing)
                if event:
                    events.append(event)
                    total_score += event["weight"]

            elif form_type in ("S-3", "S-3/A"):
                # RED FLAG: secondary offering
                events.append({
                    "type": "S-3",
                    "description": f"Secondary offering filing detected",
                    "weight": -100,
                })
                total_score = -100
                red_flag = True
                break

        return {
            "ticker": ticker,
            "events": events,
            "total_score": total_score,
            "red_flag": red_flag,
        }

    def _analyze_form4(self, ticker: str, filing: dict) -> dict | None:
        """Analyze Form 4 (insider transaction) using LLM."""
        system_prompt = (
            "You are analyzing a SEC Form 4 insider transaction filing. "
            "Determine if this is a BUY or SELL transaction. "
            "Return JSON: {\"transaction_type\": \"BUY\" or \"SELL\", "
            "\"insider_name\": \"...\", \"amount\": \"...\", \"description\": \"...\"}"
        )
        user_prompt = f"Ticker: {ticker}\nFiling: {json.dumps(filing)}"

        try:
            result = self.call_llm_json(system_prompt, user_prompt)
            tx_type = result.get("transaction_type", "UNKNOWN")

            if tx_type == "BUY":
                return {
                    "type": "Form 4",
                    "description": f"Insider {result.get('insider_name', 'unknown')} bought {result.get('amount', 'N/A')}",
                    "weight": 15,
                }
            elif tx_type == "SELL":
                return {
                    "type": "Form 4",
                    "description": f"Insider {result.get('insider_name', 'unknown')} sold {result.get('amount', 'N/A')}",
                    "weight": -10,
                }
        except Exception as e:
            logger.warning("form4_analysis_error", ticker=ticker, error=str(e))
        return None

    def _analyze_8k(self, ticker: str, filing: dict) -> dict | None:
        """Analyze 8-K filing using LLM for sentiment."""
        system_prompt = (
            "You are analyzing a SEC 8-K filing (material event). "
            "Determine if the event is POSITIVE or NEGATIVE for the stock price. "
            "Return JSON: {\"sentiment\": \"positive\" or \"negative\", \"summary\": \"...\"}"
        )
        user_prompt = f"Ticker: {ticker}\nFiling: {json.dumps(filing)}"

        try:
            result = self.call_llm_json(system_prompt, user_prompt)
            sentiment = result.get("sentiment", "neutral")

            if sentiment == "positive":
                return {
                    "type": "8-K",
                    "description": result.get("summary", "Positive event"),
                    "weight": 10,
                }
            else:
                return {
                    "type": "8-K",
                    "description": result.get("summary", "Negative event"),
                    "weight": -15,
                }
        except Exception as e:
            logger.warning("8k_analysis_error", ticker=ticker, error=str(e))
        return None

    def _lookup_cik(self, ticker: str) -> str | None:
        """Look up CIK from SEC's company tickers file."""
        try:
            import httpx
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {"User-Agent": "TradingBot bot@example.com"}
            with httpx.Client(timeout=10) as client:
                response = client.get(url, headers=headers)
                data = response.json()

            for entry in data.values():
                if entry.get("ticker") == ticker:
                    return str(entry["cik_str"])
        except Exception as e:
            logger.debug("cik_lookup_error", ticker=ticker, error=str(e))
        return None

    def _save_to_db(self, results: list[dict]):
        """Save SEC events to database."""
        session = SessionLocal()
        try:
            for company in results:
                for event in company.get("events", []):
                    sec_event = SecEvent(
                        ticker=company["ticker"],
                        form_type=event["type"],
                        event_description=event.get("description", ""),
                        weight=event.get("weight", 0),
                        red_flag=company.get("red_flag", False),
                        run_date=date.today(),
                    )
                    session.add(sec_event)
            session.commit()
            logger.info("sec_events_saved", count=sum(len(c.get("events", [])) for c in results))
        except Exception as e:
            session.rollback()
            logger.error("sec_events_save_error", error=str(e))
        finally:
            session.close()
