"""Position monitor — continuously checks exit conditions for open positions."""

import time
from datetime import datetime

import pytz
import structlog

from src.config import settings
from src.db.models import OpenPosition, TradeHistory
from src.db.session import SessionLocal
from src.services import ibkr_client
from src.trading.risk import calculate_pnl

logger = structlog.get_logger()
NY_TZ = pytz.timezone("America/New_York")


def run_monitor_loop():
    """Main monitoring loop — runs until 4:00 PM NY or no open positions remain."""
    logger.info("monitor_loop_start")

    while True:
        now_ny = datetime.now(NY_TZ)

        # Stop at 4:00 PM NY (market close)
        if now_ny.hour >= 16:
            logger.info("monitor_loop_eod_stop")
            _force_close_all("EOD forced exit")
            break

        # Check all open positions
        positions = _get_open_positions()
        if not positions:
            logger.info("monitor_no_positions")
            time.sleep(60)
            continue

        for position in positions:
            _check_exit_conditions(position)

        time.sleep(60)  # Check every minute


def _get_open_positions() -> list[OpenPosition]:
    """Get all open positions from DB."""
    session = SessionLocal()
    try:
        positions = session.query(OpenPosition).filter(OpenPosition.status == "OPEN").all()
        # Detach from session so we can use them after close
        result = []
        for p in positions:
            session.expunge(p)
            result.append(p)
        return result
    finally:
        session.close()


def _check_exit_conditions(position: OpenPosition):
    """Check if any exit condition is met for a position."""
    ticker = position.ticker
    entry_price = float(position.entry_price)
    entry_date = position.entry_date
    days_held = (datetime.now() - entry_date).days

    # Get current price
    snapshot = ibkr_client.get_snapshot(ticker)
    if not snapshot or not snapshot.get("last"):
        logger.warning("monitor_no_price", ticker=ticker)
        return

    current_price = snapshot["last"]
    pnl_pct = calculate_pnl(entry_price, current_price)

    # Condition 1: Target reached (+8%)
    if pnl_pct >= settings.target_gain:
        _exit_position(position, current_price, pnl_pct, "Target reached")
        return

    # Condition 2: Stop-loss hit (-5%)
    if pnl_pct <= -settings.stop_loss:
        _exit_position(position, current_price, pnl_pct, "Stop-loss hit")
        return

    # Condition 3: Max hold period (7 days)
    if days_held >= settings.max_hold_days:
        _exit_position(position, current_price, pnl_pct, "Max hold period")
        return

    logger.debug(
        "monitor_position",
        ticker=ticker,
        pnl_pct=f"{pnl_pct:.2%}",
        days_held=days_held,
    )


def _exit_position(position: OpenPosition, exit_price: float, pnl_pct: float, reason: str):
    """Close a position and record in trade history."""
    ticker = position.ticker
    logger.info(
        "exit_position",
        ticker=ticker,
        exit_price=exit_price,
        pnl_pct=f"{pnl_pct:.2%}",
        reason=reason,
    )

    # Sell via IBKR
    try:
        ibkr_client.place_market_order(ticker, "SELL", position.position_size)
    except Exception as e:
        logger.error("exit_sell_error", ticker=ticker, error=str(e))

    # Update DB
    session = SessionLocal()
    try:
        # Mark position as closed
        db_position = session.query(OpenPosition).filter(OpenPosition.id == position.id).first()
        if db_position:
            db_position.status = "CLOSED"

        # Add to trade history
        pnl_usd = (exit_price - float(position.entry_price)) * position.position_size
        trade = TradeHistory(
            ticker=ticker,
            entry_price=float(position.entry_price),
            exit_price=exit_price,
            position_size=position.position_size,
            pnl_pct=pnl_pct,
            pnl_usd=pnl_usd,
            reason=reason,
            entry_date=position.entry_date,
            exit_date=datetime.now(),
        )
        session.add(trade)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("exit_db_error", ticker=ticker, error=str(e))
    finally:
        session.close()


def _force_close_all(reason: str):
    """Force close all open positions (EOD)."""
    positions = _get_open_positions()
    for position in positions:
        snapshot = ibkr_client.get_snapshot(position.ticker)
        exit_price = snapshot["last"] if snapshot and snapshot.get("last") else float(position.entry_price)
        pnl_pct = calculate_pnl(float(position.entry_price), exit_price)
        _exit_position(position, exit_price, pnl_pct, reason)
