"""Agent-6: Validation Agent — Cross-validate all agent outputs before trading."""

import structlog

from src.agents.base import BaseAgent

logger = structlog.get_logger()


class ValidationAgent(BaseAgent):
    name = "validation_agent"

    def execute(self, input_data: dict) -> dict:
        agent1_tickers = set(input_data.get("agent1_tickers", []))
        agent2_companies = input_data.get("agent2_companies", [])
        recommendations = input_data.get("recommendations", [])

        agent2_tickers = {c["ticker"] for c in agent2_companies}
        agent2_map = {c["ticker"]: c for c in agent2_companies}

        issues = []

        # Check 1: All Agent-1 tickers passed through Agent-2
        missing = agent1_tickers - agent2_tickers
        if missing:
            issues.append(f"Missing tickers in Agent-2: {missing}")

        # Check 2: No contradictions (red_flag=True but recommendation=BUY)
        for rec in recommendations:
            ticker = rec["ticker"]
            company = agent2_map.get(ticker, {})
            if company.get("red_flag") and rec.get("recommendation") == "BUY":
                issues.append(f"{ticker}: red_flag=true but recommendation=BUY")

        # Check 3: Data completeness
        for rec in recommendations:
            if rec.get("final_score") is None or rec.get("confidence") is None:
                issues.append(f"{rec['ticker']}: incomplete scoring data")

        # Calculate average confidence
        confidences = [r["confidence"] for r in recommendations if r.get("confidence") is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Final verdict
        if len(issues) == 0 and avg_confidence > 0.7:
            status = "APPROVED"
        elif len(issues) > 0:
            status = "REJECTED"
        else:
            status = "NEEDS_REVIEW"

        # Build final recommendations (only for APPROVED/NEEDS_REVIEW)
        final_recs = []
        if status != "REJECTED":
            for rec in recommendations:
                ticker = rec["ticker"]
                company = agent2_map.get(ticker, {})
                # Skip red-flagged companies
                if company.get("red_flag"):
                    continue
                final_recs.append({
                    "ticker": ticker,
                    "action": rec["recommendation"],
                    "score": rec["final_score"],
                    "confidence": rec["confidence"],
                })

        return {
            "result": {
                "status": status,
                "issues": issues,
                "confidence": round(avg_confidence, 4),
                "final_recommendations": final_recs,
            },
        }
