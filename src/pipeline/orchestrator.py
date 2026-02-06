"""Daily Pipeline Orchestrator — coordinates all agents and trading actions."""

from datetime import date, datetime

import pytz
import structlog

from src.agents.calendar_agent import CalendarAgent
from src.agents.event_detector import EventDetectorAgent
from src.agents.ibkr_setup import IBKRSetupAgent
from src.agents.premarket_agent import PremarketAgent
from src.agents.scoring_agent import ScoringAgent
from src.agents.validation_agent import ValidationAgent
from src.config import settings
from src.db.models import EarningsCalendar
from src.db.session import SessionLocal
from src.services import ibkr_client
from src.trading import executor, monitor, report

logger = structlog.get_logger()
NY_TZ = pytz.timezone("America/New_York")


class DailyPipelineOrchestrator:
    def __init__(self):
        self.calendar_agent = CalendarAgent()
        self.event_detector = EventDetectorAgent()
        self.ibkr_setup = IBKRSetupAgent()
        self.premarket_agent = PremarketAgent()
        self.scoring_agent = ScoringAgent()
        self.validation_agent = ValidationAgent()

    def is_trading_day(self) -> bool:
        """Check if today is a NYSE trading day (Mon-Fri, not holiday)."""
        now = datetime.now(NY_TZ)
        # Skip weekends
        if now.weekday() >= 5:
            return False
        # Major US holidays could be added here
        return True

    def run_morning_pipeline(self):
        """5:00 AM NY — Agent-1 → Agent-2 → Decision → Agent-3."""
        logger.info("pipeline_morning_start")

        if not self.is_trading_day():
            logger.info("pipeline_skip_non_trading_day")
            return

        # Agent-1: Calendar
        agent1_result = self.calendar_agent.run({})
        companies = agent1_result["result"]["companies"]
        logger.info("pipeline_agent1_done", companies=len(companies))

        if not companies:
            logger.info("pipeline_no_companies")
            return

        # Agent-2: Event Detector
        agent2_result = self.event_detector.run({"companies": companies})
        agent2_companies = agent2_result["result"]["companies"]
        logger.info("pipeline_agent2_done", companies=len(agent2_companies))

        # Decision Point 1: Red Flag Check
        passed = [c for c in agent2_companies if not c.get("red_flag", False)]
        skipped = [c for c in agent2_companies if c.get("red_flag", False)]
        for s in skipped:
            logger.info("pipeline_red_flag_skip", ticker=s["ticker"])

        if not passed:
            logger.info("pipeline_all_red_flagged")
            return

        # Agent-3: IBKR Setup
        agent3_result = self.ibkr_setup.run({"companies": passed})
        logger.info("pipeline_agent3_done", tickers=len(agent3_result["result"]["tickers"]))

        # Store results for later phases
        self._morning_data = {
            "agent1_tickers": [c["ticker"] for c in companies],
            "agent2_companies": agent2_companies,
            "monitoring_tickers": agent3_result["result"]["tickers"],
        }

    def run_premarket_pipeline(self):
        """7:30 AM NY — Agent-4 (only for today's earnings)."""
        logger.info("pipeline_premarket_start")

        # Get companies with earnings today
        today_tickers = self._get_earnings_today()
        if not today_tickers:
            logger.info("pipeline_no_earnings_today")
            return

        # Agent-4: Pre-Market Data
        agent4_result = self.premarket_agent.run({"tickers": today_tickers})
        self._premarket_data = agent4_result["result"]
        logger.info("pipeline_agent4_done", stocks=len(self._premarket_data.get("stocks", [])))

    def run_trading_pipeline(self):
        """10:00 AM NY — Agent-5 → Agent-6 → Execute trades."""
        logger.info("pipeline_trading_start")

        morning_data = getattr(self, "_morning_data", None)
        premarket_data = getattr(self, "_premarket_data", None)

        if not morning_data or not premarket_data:
            logger.warning("pipeline_missing_data")
            return

        # Agent-5: Scoring
        scoring_input = {
            "sec_companies": morning_data["agent2_companies"],
            "premarket_stocks": premarket_data.get("stocks", []),
        }
        agent5_result = self.scoring_agent.run(scoring_input)
        recommendations = agent5_result["result"]["recommendations"]
        logger.info("pipeline_agent5_done", recommendations=len(recommendations))

        # Agent-6: Validation
        validation_input = {
            "agent1_tickers": morning_data["agent1_tickers"],
            "agent2_companies": morning_data["agent2_companies"],
            "recommendations": recommendations,
        }
        agent6_result = self.validation_agent.run(validation_input)
        validation = agent6_result["result"]
        logger.info(
            "pipeline_agent6_done",
            status=validation["status"],
            confidence=validation["confidence"],
        )

        # Decision Point 2: Execute based on validation
        if validation["status"] == "REJECTED":
            logger.warning("pipeline_validation_rejected", issues=validation["issues"])
            return

        for rec in validation["final_recommendations"]:
            if rec["action"] == "BUY":
                executor.execute_buy(rec["ticker"], rec["score"], rec["confidence"])
                logger.info("pipeline_buy", ticker=rec["ticker"], score=rec["score"])
            elif rec["action"] == "HOLD":
                logger.info("pipeline_hold", ticker=rec["ticker"], score=rec["score"])
            else:
                logger.info("pipeline_skip", ticker=rec["ticker"], score=rec["score"])

    def run_monitor_loop(self):
        """10:15 AM–4:00 PM NY — Monitor all open positions."""
        logger.info("pipeline_monitor_start")
        monitor.run_monitor_loop()

    def run_eod(self):
        """4:00 PM NY — Generate report and clean up."""
        logger.info("pipeline_eod_start")

        # Generate daily report
        daily_report = report.generate_daily_report()
        logger.info("eod_report_generated", report=daily_report)

        # Disconnect IBKR
        try:
            ibkr_client.disconnect()
        except Exception as e:
            logger.warning("ibkr_disconnect_error", error=str(e))

        logger.info("pipeline_eod_done")

    def _get_earnings_today(self) -> list[str]:
        """Get tickers with earnings scheduled for today."""
        session = SessionLocal()
        try:
            today = date.today()
            records = (
                session.query(EarningsCalendar)
                .filter(EarningsCalendar.earnings_date == today)
                .all()
            )
            return [r.ticker for r in records]
        finally:
            session.close()
