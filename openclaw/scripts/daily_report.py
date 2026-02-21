#!/usr/bin/env python3
"""
Daily & Weekly Report Generator.
Produces performance summaries for Telegram notifications.

Modes:
  --mode daily   → End-of-day report
  --mode weekly  → Weekly performance summary
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import DATA_DIR, LOG_LEVEL
from db_utils import (
    get_session, TradeHistory, OpenPosition, AgentLog,
    ScoringResult, log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("daily_report")


def generate_daily_report(output_path: str):
    """Generate end-of-day performance report."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_session() as session:
        # Today's closed trades
        trades = session.query(TradeHistory).filter(
            TradeHistory.exit_time >= datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0
            )
        ).all()

        # Open positions
        open_pos = session.query(OpenPosition).filter(
            OpenPosition.status == "open"
        ).all()

        # Today's scoring results
        scores = session.query(ScoringResult).filter(
            ScoringResult.scan_date == today
        ).all()

    # Calculate stats
    total_trades = len(trades)
    wins = [t for t in trades if t.pnl_percent > 0]
    losses = [t for t in trades if t.pnl_percent <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

    total_pnl = sum(t.pnl_amount for t in trades)
    avg_pnl_pct = (sum(t.pnl_percent for t in trades) / total_trades
                   if total_trades else 0)

    # Prediction accuracy
    predictions_with_data = [t for t in trades
                             if t.predicted_gain_pct is not None
                             and t.actual_gain_pct is not None]
    avg_prediction_accuracy = 0
    if predictions_with_data:
        avg_prediction_accuracy = sum(
            t.prediction_accuracy for t in predictions_with_data
            if t.prediction_accuracy is not None
        ) / len(predictions_with_data)

    # Build trade details
    trade_details = []
    for t in trades:
        trade_details.append({
            "ticker": t.ticker,
            "pnl_percent": t.pnl_percent,
            "pnl_amount": t.pnl_amount,
            "exit_reason": t.exit_reason,
            "predicted_gain_pct": t.predicted_gain_pct,
            "actual_gain_pct": t.actual_gain_pct,
        })

    # Build Telegram message
    telegram_msg = f"""📊 DAILY REPORT — {today}
━━━━━━━━━━━━━━━━━
Trades: {total_trades} | Win: {win_count} | Loss: {loss_count}
Win Rate: {win_rate:.0f}%
Total P&L: ${total_pnl:+.2f}
Avg P&L: {avg_pnl_pct:+.1f}%
━━━━━━━━━━━━━━━━━"""

    if trade_details:
        telegram_msg += "\nTrade Details:"
        for td in trade_details:
            emoji = "✅" if td["pnl_percent"] > 0 else "❌"
            telegram_msg += (f"\n {emoji} {td['ticker']}: "
                             f"{td['pnl_percent']:+.1f}% "
                             f"(${td['pnl_amount']:+.2f}) "
                             f"[{td['exit_reason']}]")

    if open_pos:
        telegram_msg += f"\n━━━━━━━━━━━━━━━━━\nOpen Positions: {len(open_pos)}"
        for p in open_pos:
            telegram_msg += f"\n • {p.ticker} @ ${p.entry_price:.2f}"

    if avg_prediction_accuracy:
        telegram_msg += (f"\n━━━━━━━━━━━━━━━━━\n"
                         f"Prediction Accuracy: {avg_prediction_accuracy*100:.1f}%")

    telegram_msg += "\n━━━━━━━━━━━━━━━━━\nNext earnings scan: Tomorrow 05:00 AM (NY)"

    report = {
        "date": today,
        "type": "daily",
        "stats": {
            "total_trades": total_trades,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_pct": round(avg_pnl_pct, 2),
            "avg_prediction_accuracy": round(avg_prediction_accuracy, 4),
        },
        "trades": trade_details,
        "open_positions": len(open_pos),
        "scores_generated": len(scores),
        "telegram_message": telegram_msg,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log_agent("daily_report", "success",
              f"Daily report: {total_trades} trades, {win_rate:.0f}% win rate, "
              f"P&L=${total_pnl:+.2f}")

    print(json.dumps({
        "status": "ok",
        "telegram_message": telegram_msg,
        "stats": report["stats"],
    }))


def generate_weekly_report(output_path: str):
    """Generate weekly performance summary."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    with get_session() as session:
        trades = session.query(TradeHistory).filter(
            TradeHistory.exit_time >= week_start
        ).all()

    total_trades = len(trades)
    wins = [t for t in trades if t.pnl_percent > 0]
    losses = [t for t in trades if t.pnl_percent <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0
    total_pnl = sum(t.pnl_amount for t in trades)
    avg_pnl = (sum(t.pnl_percent for t in trades) / total_trades
               if total_trades else 0)

    best_trade = max(trades, key=lambda t: t.pnl_percent) if trades else None
    worst_trade = min(trades, key=lambda t: t.pnl_percent) if trades else None

    # Prediction analysis
    predictions = [t for t in trades if t.prediction_accuracy is not None]
    avg_accuracy = (sum(t.prediction_accuracy for t in predictions) / len(predictions)
                    if predictions else 0)

    telegram_msg = f"""📊 WEEKLY REPORT — {week_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}
━━━━━━━━━━━━━━━━━━━━━━━
Total Trades: {total_trades}
Win Rate: {win_rate:.0f}% ({len(wins)}/{total_trades})
Total P&L: ${total_pnl:+.2f}
Avg P&L per trade: {avg_pnl:+.1f}%
━━━━━━━━━━━━━━━━━━━━━━━"""

    if best_trade:
        telegram_msg += (f"\nBest: {best_trade.ticker} "
                         f"{best_trade.pnl_percent:+.1f}%")
    if worst_trade:
        telegram_msg += (f"\nWorst: {worst_trade.ticker} "
                         f"{worst_trade.pnl_percent:+.1f}%")

    if avg_accuracy:
        telegram_msg += (f"\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                         f"Prediction Accuracy: {avg_accuracy*100:.1f}%")

    telegram_msg += "\n━━━━━━━━━━━━━━━━━━━━━━━"

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        r = t.exit_reason or "unknown"
        reasons[r] = reasons.get(r, 0) + 1
    if reasons:
        telegram_msg += "\nExit Reasons:"
        for r, count in sorted(reasons.items(), key=lambda x: -x[1]):
            telegram_msg += f"\n • {r}: {count}"

    report = {
        "date_range": {
            "start": week_start.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        },
        "type": "weekly",
        "stats": {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_prediction_accuracy": round(avg_accuracy, 4),
            "exit_reasons": reasons,
        },
        "best_trade": {
            "ticker": best_trade.ticker,
            "pnl_percent": best_trade.pnl_percent,
        } if best_trade else None,
        "worst_trade": {
            "ticker": worst_trade.ticker,
            "pnl_percent": worst_trade.pnl_percent,
        } if worst_trade else None,
        "telegram_message": telegram_msg,
        "generated_at": now.isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log_agent("weekly_report", "success",
              f"Weekly: {total_trades} trades, {win_rate:.0f}% WR, ${total_pnl:+.2f}")

    print(json.dumps({
        "status": "ok",
        "telegram_message": telegram_msg,
        "stats": report["stats"],
    }))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Report generator")
    parser.add_argument("--mode", required=True, choices=["daily", "weekly"])
    parser.add_argument("--output", default=str(DATA_DIR / "report.json"))
    args = parser.parse_args()

    if args.mode == "daily":
        generate_daily_report(args.output)
    elif args.mode == "weekly":
        generate_weekly_report(args.output)
