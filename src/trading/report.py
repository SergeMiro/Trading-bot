"""EOD Report — Generate daily trading summary."""

from datetime import date, datetime

import structlog

from src.db.models import TradeHistory
from src.db.session import SessionLocal

logger = structlog.get_logger()


def generate_daily_report() -> str:
    """Generate end-of-day report with trade statistics."""
    session = SessionLocal()
    try:
        today = date.today()
        trades = (
            session.query(TradeHistory)
            .filter(TradeHistory.exit_date >= datetime(today.year, today.month, today.day))
            .all()
        )

        if not trades:
            report = f"Daily Report - {today}\n\nNo trades executed today."
            logger.info("eod_report", trades=0)
            return report

        total_pnl_pct = sum(float(t.pnl_pct or 0) for t in trades)
        total_pnl_usd = sum(float(t.pnl_usd or 0) for t in trades)
        winners = [t for t in trades if float(t.pnl_pct or 0) > 0]
        win_rate = len(winners) / len(trades) if trades else 0

        details = []
        for t in trades:
            details.append(
                f"  {t.ticker}: {float(t.pnl_pct or 0):.2%} (${float(t.pnl_usd or 0):.2f}) - {t.reason}"
            )

        report = (
            f"Daily Report - {today}\n"
            f"\n"
            f"Trades executed: {len(trades)}\n"
            f"Total P&L: {total_pnl_pct:.2%} (${total_pnl_usd:.2f})\n"
            f"Win Rate: {win_rate:.1%}\n"
            f"\n"
            f"Details:\n" + "\n".join(details)
        )

        logger.info(
            "eod_report",
            trades=len(trades),
            pnl_pct=f"{total_pnl_pct:.2%}",
            pnl_usd=f"${total_pnl_usd:.2f}",
            win_rate=f"{win_rate:.1%}",
        )
        return report
    finally:
        session.close()
