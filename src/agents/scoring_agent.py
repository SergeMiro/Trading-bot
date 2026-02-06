"""Agent-5: Scoring Agent — Calculate composite score and recommendation for each stock."""

from datetime import date

import structlog

from src.agents.base import BaseAgent
from src.config import settings
from src.db.models import ScoringResult
from src.db.session import SessionLocal

logger = structlog.get_logger()


class ScoringAgent(BaseAgent):
    name = "scoring_agent"

    def execute(self, input_data: dict) -> dict:
        # Combine Agent-2 (SEC events) and Agent-4 (pre-market) data
        sec_companies = {c["ticker"]: c for c in input_data.get("sec_companies", [])}
        premarket_stocks = {s["ticker"]: s for s in input_data.get("premarket_stocks", [])}

        results = []
        for ticker, premarket in premarket_stocks.items():
            sec_data = sec_companies.get(ticker, {"total_score": 0})
            score, breakdown = self._calculate_score(sec_data, premarket)
            confidence = min(score / 100, 1.0)

            if score >= settings.score_threshold_buy:
                recommendation = "BUY"
            elif score >= settings.score_threshold_hold:
                recommendation = "HOLD"
            else:
                recommendation = "SKIP"

            result = {
                "ticker": ticker,
                "final_score": score,
                "recommendation": recommendation,
                "breakdown": breakdown,
                "confidence": round(confidence, 4),
                "entry_time": "10:15 AM NY",
                "target_gain": f"{settings.target_gain:.0%}",
                "stop_loss": f"-{settings.stop_loss:.0%}",
            }
            results.append(result)

        # Save to DB
        self._save_to_db(results)

        return {
            "result": {"recommendations": results},
        }

    def _calculate_score(self, sec_data: dict, premarket: dict) -> tuple[int, dict]:
        """Calculate composite score from all data sources."""
        score = 0
        breakdown = {}

        # 1. Volume Score (max 25)
        volume_ratio = premarket.get("volume_ratio", 0)
        if volume_ratio > 2.0:
            breakdown["volume_score"] = 25
        elif volume_ratio > 1.5:
            breakdown["volume_score"] = 20
        elif volume_ratio > 1.0:
            breakdown["volume_score"] = 10
        else:
            breakdown["volume_score"] = 0
        score += breakdown["volume_score"]

        # 2. Volatility Score / ATR (max 10)
        atr = premarket.get("atr_5d", 0)
        if 2 <= atr <= 5:
            breakdown["volatility_score"] = 10
        elif 5 < atr <= 10:
            breakdown["volatility_score"] = 5
        else:
            breakdown["volatility_score"] = 0
        score += breakdown["volatility_score"]

        # 3. Market Score (max 15)
        sentiment = premarket.get("market_sentiment", "neutral")
        if sentiment == "bullish":
            breakdown["market_score"] = 15
        elif sentiment == "neutral":
            breakdown["market_score"] = 5
        else:
            breakdown["market_score"] = 0
        score += breakdown["market_score"]

        # 4. Sector Score (max 15)
        sector_change = premarket.get("sector_change", 0)
        if sector_change > 0:
            breakdown["sector_score"] = 15
        else:
            breakdown["sector_score"] = 0
        score += breakdown["sector_score"]

        # 5. SEC Events Score (from Agent-2)
        sec_score = sec_data.get("total_score", 0)
        breakdown["sec_score"] = sec_score
        score += sec_score

        return score, breakdown

    def _save_to_db(self, results: list[dict]):
        """Save scoring results to database."""
        session = SessionLocal()
        try:
            for r in results:
                entry = ScoringResult(
                    ticker=r["ticker"],
                    run_date=date.today(),
                    final_score=r["final_score"],
                    recommendation=r["recommendation"],
                    confidence=r["confidence"],
                    volume_score=r["breakdown"].get("volume_score"),
                    volatility_score=r["breakdown"].get("volatility_score"),
                    market_score=r["breakdown"].get("market_score"),
                    sector_score=r["breakdown"].get("sector_score"),
                    sec_score=r["breakdown"].get("sec_score"),
                )
                session.add(entry)
            session.commit()
            logger.info("scoring_results_saved", count=len(results))
        except Exception as e:
            session.rollback()
            logger.error("scoring_save_error", error=str(e))
        finally:
            session.close()
