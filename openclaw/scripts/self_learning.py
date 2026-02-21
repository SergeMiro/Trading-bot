#!/usr/bin/env python3
"""
Self-Learning System — Prediction Analysis & Skill Improvement Generator.

This system closes the feedback loop:
1. Compares predictions (predicted_gain_pct) with actual results (actual_gain_pct)
2. Analyzes the full agent chain for each trade to find weak links
3. Generates concrete improvement suggestions as OpenClaw skill code
4. Presents suggestions to the user for approval

Modes:
  --mode trade_analysis   → Analyze a single completed trade
  --mode weekly_analysis  → Analyze all trades from the past week
  --mode generate_skill   → Generate improved skill code for a specific issue
  --mode apply_skill      → Apply an approved skill improvement
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_DIR, LOG_LEVEL, SCORE_BUY, SCORE_HOLD, TARGET_GAIN, STOP_LOSS
from db_utils import (
    get_session, TradeHistory, ScoringResult, SecEvent,
    PremarketData, SelfLearningLog, AgentLog,
    log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("self_learning")


# ─── Analysis Constants ───────────────────────────────────────

# Prediction quality thresholds
EXCELLENT_ACCURACY = 0.8    # >= 80% of predicted gain achieved
ACCEPTABLE_ACCURACY = 0.5   # >= 50% of predicted gain achieved
POOR_ACCURACY = 0.3         # < 30% = needs investigation

# Pattern detection thresholds
MIN_TRADES_FOR_PATTERN = 3  # Need at least 3 trades to detect a pattern
SIGNIFICANT_ERROR_PCT = 5.0 # Prediction error > 5% is significant


# ─── Trade Chain Reconstruction ───────────────────────────────

def reconstruct_chain(trade: TradeHistory, session) -> dict:
    """
    Reconstruct the full agent chain for a specific trade.
    Returns all data that went into the trading decision.
    """
    chain = {
        "trade": {
            "ticker": trade.ticker,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl_percent": trade.pnl_percent,
            "exit_reason": trade.exit_reason,
            "predicted_gain_pct": trade.predicted_gain_pct,
            "actual_gain_pct": trade.actual_gain_pct,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
        },
        "scoring": None,
        "sec_events": [],
        "premarket_data": None,
        "agent_logs": [],
    }

    # Get scoring result
    if trade.scoring_id:
        scoring = session.query(ScoringResult).filter(
            ScoringResult.id == trade.scoring_id
        ).first()
        if scoring:
            chain["scoring"] = {
                "final_score": scoring.final_score,
                "recommendation": scoring.recommendation,
                "breakdown": scoring.breakdown,
                "entry_price": scoring.entry_price,
                "target_price": scoring.target_price,
                "stop_price": scoring.stop_price,
            }

    # Get SEC events for the ticker around trade date
    scan_date = trade.entry_time.strftime("%Y-%m-%d") if trade.entry_time else None
    if scan_date:
        sec_events = session.query(SecEvent).filter(
            SecEvent.ticker == trade.ticker,
            SecEvent.scan_date == scan_date,
        ).all()
        chain["sec_events"] = [
            {
                "event_type": e.event_type,
                "weight": e.weight,
                "description": e.description,
                "red_flag": e.red_flag,
            }
            for e in sec_events
        ]

        # Get premarket data
        premarket = session.query(PremarketData).filter(
            PremarketData.ticker == trade.ticker,
            PremarketData.scan_date == scan_date,
        ).first()
        if premarket:
            chain["premarket_data"] = {
                "premarket_price": premarket.premarket_price,
                "volume_ratio": premarket.volume_ratio,
                "atr_5d": premarket.atr_5d,
                "sector": premarket.sector,
                "sector_etf_change": premarket.sector_etf_change,
            }

    # Get agent logs around trade time
    if trade.entry_time:
        start = trade.entry_time - timedelta(hours=6)
        end = trade.entry_time + timedelta(hours=1)
        logs = session.query(AgentLog).filter(
            AgentLog.created_at.between(start, end)
        ).order_by(AgentLog.created_at).all()
        chain["agent_logs"] = [
            {
                "agent": log.agent_name,
                "status": log.status,
                "message": log.message,
                "time": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs[:20]  # Limit to 20 entries
        ]

    return chain


# ─── Diagnosis Engine ─────────────────────────────────────────

def diagnose_trade(chain: dict) -> dict:
    """
    Analyze a trade chain and identify what went wrong (or right).
    Returns diagnosis with specific weak points.
    """
    trade = chain["trade"]
    scoring = chain.get("scoring", {}) or {}
    premarket = chain.get("premarket_data", {}) or {}

    predicted = trade.get("predicted_gain_pct", 0) or 0
    actual = trade.get("actual_gain_pct", 0) or 0
    error = abs(predicted - actual)
    is_profitable = actual > 0
    is_prediction_accurate = error < SIGNIFICANT_ERROR_PCT

    diagnosis = {
        "ticker": trade["ticker"],
        "predicted_gain_pct": predicted,
        "actual_gain_pct": actual,
        "prediction_error_pct": round(error, 2),
        "is_profitable": is_profitable,
        "is_prediction_accurate": is_prediction_accurate,
        "exit_reason": trade.get("exit_reason"),
        "weak_points": [],
        "strong_points": [],
        "suggestions": [],
        "severity": "info",  # info, warning, critical
    }

    # ── Analyze each scoring factor ──

    breakdown = scoring.get("breakdown", []) or []

    for factor in breakdown:
        factor_name = factor.get("factor", "")
        points = factor.get("points", 0)

        # Volume ratio analysis
        if factor_name == "volume_ratio":
            vol_ratio = premarket.get("volume_ratio", 0)
            if vol_ratio >= 2.0 and not is_profitable:
                diagnosis["weak_points"].append({
                    "factor": "volume_ratio",
                    "issue": f"High volume ({vol_ratio}x) gave +{points}pts but trade lost",
                    "suggestion": "Volume alone doesn't guarantee direction. "
                                  "Consider adding price momentum confirmation.",
                    "skill_type": "scoring_adjustment",
                })
            elif vol_ratio < 1.5 and is_profitable:
                diagnosis["strong_points"].append({
                    "factor": "volume_ratio",
                    "note": "Profitable despite low volume — other factors compensated",
                })

        # ATR analysis
        if factor_name == "atr_5d":
            atr = premarket.get("atr_5d", 0)
            if atr > 6.0 and trade.get("exit_reason") == "stop_hit":
                diagnosis["weak_points"].append({
                    "factor": "atr_5d",
                    "issue": f"ATR={atr} was too high, stop-loss hit likely due to noise",
                    "suggestion": "For high-ATR stocks, widen stop-loss to 1.5x ATR "
                                  "or reduce position size.",
                    "skill_type": "risk_adjustment",
                })

        # Market sentiment
        if factor_name == "market_sentiment":
            if points < 0 and is_profitable:
                diagnosis["strong_points"].append({
                    "factor": "market_sentiment",
                    "note": "Stock outperformed despite bearish market — strong stock-specific signal",
                })
            elif points > 0 and not is_profitable:
                diagnosis["weak_points"].append({
                    "factor": "market_sentiment",
                    "issue": "Bullish market didn't help — stock-specific problem",
                    "suggestion": "Weight stock-specific factors (SEC events, volume) "
                                  "higher than market sentiment.",
                    "skill_type": "scoring_reweight",
                })

    # ── Exit reason analysis ──

    exit_reason = trade.get("exit_reason")
    if exit_reason == "stop_hit" and predicted > 0:
        diagnosis["severity"] = "warning"
        diagnosis["suggestions"].append({
            "type": "stop_loss_tuning",
            "description": (f"Stop-loss hit while predicting +{predicted}% gain. "
                            f"Consider dynamic stop-loss based on ATR."),
            "proposed_change": "Use stop_price = entry_price - (1.5 * ATR) "
                               "instead of fixed -5%",
        })

    if exit_reason == "max_hold" and actual < predicted * 0.5:
        diagnosis["severity"] = "warning"
        diagnosis["suggestions"].append({
            "type": "hold_period_tuning",
            "description": (f"Position held to max ({trade.get('exit_reason')}) "
                            f"achieving only {actual:.1f}% of {predicted:.1f}% target."),
            "proposed_change": "Consider reducing MAX_HOLD_DAYS for low-momentum "
                               "stocks or adding momentum exit criteria.",
        })

    if exit_reason == "target_hit" and is_prediction_accurate:
        diagnosis["severity"] = "info"
        diagnosis["strong_points"].append({
            "factor": "overall",
            "note": "Target hit with accurate prediction — system worked correctly",
        })

    # ── Overall severity ──
    if error > SIGNIFICANT_ERROR_PCT * 2:
        diagnosis["severity"] = "critical"
    elif not is_profitable and predicted > 5:
        diagnosis["severity"] = "critical"

    return diagnosis


# ─── Pattern Detection ────────────────────────────────────────

def detect_patterns(trades: list[TradeHistory], session) -> list[dict]:
    """
    Analyze multiple trades to find recurring patterns and systematic issues.
    """
    patterns = []

    if len(trades) < MIN_TRADES_FOR_PATTERN:
        return patterns

    # Pattern 1: Stop-loss hit rate
    stop_trades = [t for t in trades if t.exit_reason == "stop_hit"]
    stop_rate = len(stop_trades) / len(trades)
    if stop_rate > 0.4:  # > 40% trades hit stop-loss
        patterns.append({
            "pattern": "high_stop_loss_rate",
            "description": (f"{stop_rate*100:.0f}% of trades hit stop-loss. "
                            f"Stop may be too tight or entries too late."),
            "affected_trades": len(stop_trades),
            "severity": "critical",
            "suggested_fix": {
                "type": "parameter_adjustment",
                "param": "STOP_LOSS",
                "current": STOP_LOSS,
                "suggested": min(STOP_LOSS * 1.5, 0.08),
                "reason": "Widen stop-loss to accommodate normal volatility",
            },
        })

    # Pattern 2: Sector bias
    sector_results = {}
    for t in trades:
        # Get premarket data for sector info
        premarket = session.query(PremarketData).filter(
            PremarketData.ticker == t.ticker,
        ).order_by(PremarketData.created_at.desc()).first()
        sector = premarket.sector if premarket else "Unknown"

        if sector not in sector_results:
            sector_results[sector] = {"wins": 0, "losses": 0, "total_pnl": 0}
        if t.pnl_percent > 0:
            sector_results[sector]["wins"] += 1
        else:
            sector_results[sector]["losses"] += 1
        sector_results[sector]["total_pnl"] += t.pnl_percent

    for sector, stats in sector_results.items():
        total = stats["wins"] + stats["losses"]
        if total >= 3 and stats["losses"] > stats["wins"] * 2:
            patterns.append({
                "pattern": "sector_underperformance",
                "description": (f"Sector '{sector}' has {stats['wins']} wins vs "
                                f"{stats['losses']} losses (avg PnL: "
                                f"{stats['total_pnl']/total:.1f}%)"),
                "severity": "warning",
                "suggested_fix": {
                    "type": "scoring_adjustment",
                    "detail": f"Add sector penalty of -10pts for '{sector}' in scoring engine",
                },
            })

    # Pattern 3: Prediction overestimation
    predictions = [t for t in trades
                   if t.predicted_gain_pct is not None and t.actual_gain_pct is not None]
    if len(predictions) >= 3:
        avg_predicted = sum(t.predicted_gain_pct for t in predictions) / len(predictions)
        avg_actual = sum(t.actual_gain_pct for t in predictions) / len(predictions)
        overestimation = avg_predicted - avg_actual

        if overestimation > 3.0:  # Systematically overestimating by > 3%
            patterns.append({
                "pattern": "systematic_overestimation",
                "description": (f"Predictions average {avg_predicted:.1f}% but "
                                f"actual average is {avg_actual:.1f}% "
                                f"(overestimation: {overestimation:.1f}%)"),
                "severity": "critical",
                "suggested_fix": {
                    "type": "target_adjustment",
                    "param": "TARGET_GAIN",
                    "current": TARGET_GAIN,
                    "suggested": round(TARGET_GAIN * (avg_actual / avg_predicted), 3),
                    "reason": "Reduce target to match actual achievable gains",
                },
            })

    # Pattern 4: Time-of-day effect
    morning_trades = [t for t in trades
                      if t.entry_time and t.entry_time.hour < 15]  # Before 10 AM NY
    afternoon_trades = [t for t in trades
                        if t.entry_time and t.entry_time.hour >= 15]

    if len(morning_trades) >= 2 and len(afternoon_trades) >= 2:
        morning_wr = (sum(1 for t in morning_trades if t.pnl_percent > 0)
                      / len(morning_trades))
        afternoon_wr = (sum(1 for t in afternoon_trades if t.pnl_percent > 0)
                        / len(afternoon_trades))

        if afternoon_wr > morning_wr + 0.2:  # 20% better in afternoon
            patterns.append({
                "pattern": "time_of_day_effect",
                "description": (f"Afternoon entries win {afternoon_wr*100:.0f}% vs "
                                f"morning {morning_wr*100:.0f}%"),
                "severity": "info",
                "suggested_fix": {
                    "type": "timing_adjustment",
                    "detail": "Consider delaying entries to 10:30 AM (NY) instead of 10:15 AM",
                },
            })

    return patterns


# ─── Skill Code Generation ───────────────────────────────────

def generate_skill_code(diagnosis: dict, patterns: list[dict]) -> dict:
    """
    Generate concrete OpenClaw skill code to address identified issues.
    Returns the skill definition and Python code that can be applied.
    """
    skills = []

    # From individual trade diagnosis
    for weak in diagnosis.get("weak_points", []):
        skill_type = weak.get("skill_type", "")

        if skill_type == "scoring_adjustment":
            skills.append({
                "name": f"improved_scoring_{diagnosis['ticker'].lower()}",
                "description": f"Adjusted scoring based on {diagnosis['ticker']} analysis",
                "type": "scoring_modifier",
                "code": f"""
# Scoring Modifier Skill — Generated by Self-Learning System
# Issue: {weak['issue']}
# Suggestion: {weak['suggestion']}

def modified_score_volume(ratio: float, price_momentum: float = 0) -> int:
    \"\"\"Enhanced volume scoring with momentum confirmation.\"\"\"
    base_score = 0
    if ratio >= 2.0:
        base_score = 25
    elif ratio >= 1.5:
        base_score = 20
    elif ratio >= 1.2:
        base_score = 10

    # Momentum confirmation: if price is dropping despite high volume,
    # reduce the volume bonus
    if price_momentum < -0.01 and base_score > 10:
        base_score = int(base_score * 0.5)

    return base_score
""",
                "apply_to": "scoring_engine.py",
                "function": "score_volume_ratio",
            })

        elif skill_type == "risk_adjustment":
            skills.append({
                "name": "dynamic_stop_loss",
                "description": "ATR-based dynamic stop-loss calculation",
                "type": "risk_modifier",
                "code": """
# Dynamic Stop-Loss Skill — Generated by Self-Learning System
# Replaces fixed -5% stop with ATR-based calculation

def calculate_dynamic_stop(entry_price: float, atr: float,
                           multiplier: float = 1.5) -> float:
    \"\"\"Calculate stop-loss based on ATR instead of fixed percentage.\"\"\"
    atr_stop = entry_price - (atr * multiplier)
    fixed_stop = entry_price * (1 - 0.05)  # -5% floor

    # Use the wider of the two (give more room for volatile stocks)
    return min(atr_stop, fixed_stop)
""",
                "apply_to": "execute_trade.py",
                "function": "calculate_position_size",
            })

    # From patterns
    for pattern in patterns:
        fix = pattern.get("suggested_fix", {})

        if fix.get("type") == "parameter_adjustment":
            skills.append({
                "name": f"param_tune_{fix['param'].lower()}",
                "description": f"Tune {fix['param']} from {fix['current']} to {fix['suggested']}",
                "type": "config_change",
                "code": f"""
# Parameter Tuning — Generated by Self-Learning System
# Pattern: {pattern['pattern']}
# Reason: {fix.get('reason', '')}

# In .env file, change:
# {fix['param']}={fix['current']}
# To:
# {fix['param']}={fix['suggested']}

# This change will take effect after restarting the pipeline.
""",
                "apply_to": ".env",
                "param": fix["param"],
                "old_value": fix["current"],
                "new_value": fix["suggested"],
            })

        elif fix.get("type") == "scoring_adjustment" and "sector" in fix.get("detail", ""):
            skills.append({
                "name": "sector_penalty_skill",
                "description": fix.get("detail", "Sector-based scoring penalty"),
                "type": "scoring_modifier",
                "code": f"""
# Sector Penalty Skill — Generated by Self-Learning System
# Pattern: {pattern['pattern']}

SECTOR_PENALTIES = {{
    # Sectors with historically poor performance get penalized
    # Update this dict based on ongoing self-learning analysis
}}

def score_sector_history(sector: str) -> int:
    \"\"\"Apply historical sector performance penalty/bonus.\"\"\"
    return SECTOR_PENALTIES.get(sector, 0)
""",
                "apply_to": "scoring_engine.py",
                "function": "NEW: score_sector_history",
            })

    return {
        "skills_count": len(skills),
        "skills": skills,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Main Analysis Functions ─────────────────────────────────

def analyze_single_trade(trade_id: int, output_path: str):
    """Analyze a single completed trade."""
    start_time = time.time()

    with get_session() as session:
        trade = session.query(TradeHistory).filter(
            TradeHistory.id == trade_id
        ).first()

        if not trade:
            print(json.dumps({"status": "error", "reason": f"Trade {trade_id} not found"}))
            return

        chain = reconstruct_chain(trade, session)
        diagnosis = diagnose_trade(chain)
        skill_suggestions = generate_skill_code(diagnosis, [])

        # Save to self-learning log
        entry = SelfLearningLog(
            trade_id=trade_id,
            ticker=trade.ticker,
            predicted_gain_pct=trade.predicted_gain_pct,
            actual_gain_pct=trade.actual_gain_pct,
            prediction_error=abs((trade.predicted_gain_pct or 0) - (trade.actual_gain_pct or 0)),
            chain_analysis=chain,
            improvement_suggestions=skill_suggestions,
            suggested_skill_code=json.dumps(skill_suggestions.get("skills", [])),
        )
        session.add(entry)

    result = {
        "trade_id": trade_id,
        "diagnosis": diagnosis,
        "chain_snapshot": chain,
        "skill_suggestions": skill_suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("self_learning", "success",
              f"Analyzed trade {trade_id} ({trade.ticker}): "
              f"severity={diagnosis['severity']}, "
              f"{len(diagnosis['weak_points'])} weak points, "
              f"{skill_suggestions['skills_count']} skill suggestions",
              execution_time_ms=elapsed_ms)

    # Build Telegram message
    telegram_msg = build_trade_analysis_message(diagnosis, skill_suggestions)

    print(json.dumps({
        "status": "ok",
        "trade_id": trade_id,
        "severity": diagnosis["severity"],
        "weak_points": len(diagnosis["weak_points"]),
        "suggestions": skill_suggestions["skills_count"],
        "telegram_message": telegram_msg,
    }))


def analyze_weekly(output_path: str):
    """Analyze all trades from the past week."""
    start_time = time.time()

    week_start = datetime.now(timezone.utc) - timedelta(days=7)

    with get_session() as session:
        trades = session.query(TradeHistory).filter(
            TradeHistory.exit_time >= week_start
        ).all()

        if not trades:
            print(json.dumps({"status": "ok", "message": "No trades this week"}))
            return

        # Analyze each trade
        diagnoses = []
        for trade in trades:
            chain = reconstruct_chain(trade, session)
            diagnosis = diagnose_trade(chain)
            diagnoses.append(diagnosis)

        # Detect patterns across all trades
        patterns = detect_patterns(trades, session)

        # Generate improvement skills
        # Use the worst trade's diagnosis as primary input
        worst = max(diagnoses, key=lambda d: d.get("prediction_error_pct", 0))
        all_weak_points = []
        for d in diagnoses:
            all_weak_points.extend(d.get("weak_points", []))

        combined_diagnosis = {
            "ticker": "WEEKLY_ANALYSIS",
            "predicted_gain_pct": sum(d.get("predicted_gain_pct", 0) for d in diagnoses) / len(diagnoses),
            "actual_gain_pct": sum(d.get("actual_gain_pct", 0) for d in diagnoses) / len(diagnoses),
            "prediction_error_pct": sum(d.get("prediction_error_pct", 0) for d in diagnoses) / len(diagnoses),
            "weak_points": all_weak_points,
            "strong_points": [],
            "suggestions": [],
            "severity": "critical" if any(d["severity"] == "critical" for d in diagnoses) else "warning",
        }

        skill_suggestions = generate_skill_code(combined_diagnosis, patterns)

        # Save to DB
        for trade in trades:
            try:
                entry = SelfLearningLog(
                    trade_id=trade.id,
                    ticker=trade.ticker,
                    predicted_gain_pct=trade.predicted_gain_pct,
                    actual_gain_pct=trade.actual_gain_pct,
                    prediction_error=abs((trade.predicted_gain_pct or 0) -
                                         (trade.actual_gain_pct or 0)),
                    chain_analysis={"weekly_batch": True},
                    improvement_suggestions={"patterns": patterns},
                )
                session.add(entry)
            except Exception:
                continue

    result = {
        "period": {
            "start": week_start.isoformat(),
            "end": datetime.now(timezone.utc).isoformat(),
        },
        "total_trades": len(trades),
        "diagnoses": diagnoses,
        "patterns": patterns,
        "skill_suggestions": skill_suggestions,
        "summary": {
            "avg_prediction_error": combined_diagnosis["prediction_error_pct"],
            "critical_issues": sum(1 for d in diagnoses if d["severity"] == "critical"),
            "total_weak_points": len(all_weak_points),
            "total_patterns": len(patterns),
            "total_skill_suggestions": skill_suggestions["skills_count"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("self_learning", "success",
              f"Weekly analysis: {len(trades)} trades, "
              f"{len(patterns)} patterns, "
              f"{skill_suggestions['skills_count']} skill suggestions",
              execution_time_ms=elapsed_ms)

    telegram_msg = build_weekly_analysis_message(result)

    print(json.dumps({
        "status": "ok",
        "total_trades": len(trades),
        "patterns": len(patterns),
        "suggestions": skill_suggestions["skills_count"],
        "critical_issues": result["summary"]["critical_issues"],
        "telegram_message": telegram_msg,
    }))


# ─── Telegram Message Builders ────────────────────────────────

def build_trade_analysis_message(diagnosis: dict, skills: dict) -> str:
    """Build Telegram notification for a single trade analysis."""
    severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
    emoji = severity_emoji.get(diagnosis["severity"], "📊")

    msg = f"""{emoji} SELF-LEARNING: Trade Analysis
━━━━━━━━━━━━━━━━━
Ticker: {diagnosis['ticker']}
Predicted: +{diagnosis['predicted_gain_pct']:.1f}%
Actual: {diagnosis['actual_gain_pct']:+.1f}%
Error: {diagnosis['prediction_error_pct']:.1f}%
Exit: {diagnosis['exit_reason']}
━━━━━━━━━━━━━━━━━"""

    if diagnosis["weak_points"]:
        msg += "\n\nWeak Points:"
        for wp in diagnosis["weak_points"][:3]:
            msg += f"\n • [{wp['factor']}] {wp['issue'][:80]}"

    if diagnosis["strong_points"]:
        msg += "\n\nStrong Points:"
        for sp in diagnosis["strong_points"][:2]:
            msg += f"\n • [{sp['factor']}] {sp['note'][:80]}"

    if skills["skills_count"] > 0:
        msg += f"\n\n📝 {skills['skills_count']} improvement(s) suggested."
        msg += "\nReply 'show improvements' to see details."
        msg += "\nReply 'apply improvement N' to approve."

    return msg


def build_weekly_analysis_message(result: dict) -> str:
    """Build Telegram notification for weekly analysis."""
    summary = result["summary"]

    msg = f"""📊 WEEKLY SELF-LEARNING REPORT
━━━━━━━━━━━━━━━━━━━━━━━
Trades Analyzed: {result['total_trades']}
Avg Prediction Error: {summary['avg_prediction_error']:.1f}%
Critical Issues: {summary['critical_issues']}
Patterns Found: {summary['total_patterns']}
━━━━━━━━━━━━━━━━━━━━━━━"""

    if result["patterns"]:
        msg += "\n\nDetected Patterns:"
        for p in result["patterns"][:3]:
            sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(p["severity"], "")
            msg += f"\n {sev} {p['description'][:100]}"

    if summary["total_skill_suggestions"] > 0:
        msg += f"\n\n📝 {summary['total_skill_suggestions']} skill improvement(s) generated."
        msg += "\nReply 'show improvements' for details."
        msg += "\nReply 'apply all' to approve all."

    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━"
    return msg


# ─── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Self-Learning System")
    parser.add_argument("--mode", required=True,
                        choices=["trade_analysis", "weekly_analysis",
                                 "generate_skill"],
                        help="Analysis mode")
    parser.add_argument("--trade-id", type=int, help="Trade ID (for trade_analysis)")
    parser.add_argument("--output",
                        default=str(DATA_DIR / "self_learning_report.json"),
                        help="Output JSON path")
    args = parser.parse_args()

    if args.mode == "trade_analysis":
        if not args.trade_id:
            print(json.dumps({"status": "error", "reason": "trade-id required"}))
            sys.exit(1)
        analyze_single_trade(args.trade_id, args.output)
    elif args.mode == "weekly_analysis":
        analyze_weekly(args.output)
    elif args.mode == "generate_skill":
        if not args.trade_id:
            print(json.dumps({"status": "error", "reason": "trade-id required"}))
            sys.exit(1)
        # Generate skill is handled within trade_analysis
        analyze_single_trade(args.trade_id, args.output)
