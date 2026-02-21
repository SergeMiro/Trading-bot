#!/usr/bin/env python3
"""
Position Monitor: Checks exit conditions for all open positions.
Runs every 5 minutes during market hours (9:30 AM — 4:00 PM NY).

Exit conditions:
1. Target hit (+9%)
2. Stop loss hit (-5%)
3. Max hold period exceeded (7 days)
4. EOD forced close (4:00 PM)
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID_MONITOR,
    TARGET_GAIN, STOP_LOSS, DATA_DIR, LOG_LEVEL
)
from db_utils import (
    get_session, OpenPosition, TradeHistory,
    log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("position_monitor")


def check_positions():
    """Check all open positions for exit conditions."""
    from ib_insync import IB, Stock

    start_time = time.time()
    log_agent("position_monitor", "started", "Checking open positions")

    with get_session() as session:
        positions = session.query(OpenPosition).filter(
            OpenPosition.status == "open"
        ).all()

        if not positions:
            logger.info("No open positions to monitor")
            print(json.dumps({"status": "ok", "open_positions": 0, "actions": []}))
            return

        logger.info(f"Monitoring {len(positions)} open positions")

    actions = []
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_MONITOR)

        with get_session() as session:
            positions = session.query(OpenPosition).filter(
                OpenPosition.status == "open"
            ).all()

            for position in positions:
                try:
                    contract = Stock(position.ticker, "SMART", "USD")
                    ib.qualifyContracts(contract)

                    md = ib.reqMktData(contract, "", False, False)
                    ib.sleep(2)

                    current_price = md.last or md.close
                    if not current_price or current_price <= 0:
                        logger.warning(f"No price data for {position.ticker}")
                        continue

                    pnl_pct = ((current_price - position.entry_price) /
                               position.entry_price)
                    now = datetime.now(timezone.utc)

                    action = None
                    reason = None

                    # Check exit conditions
                    if pnl_pct >= TARGET_GAIN:
                        action = "SELL"
                        reason = "target_hit"
                    elif pnl_pct <= -STOP_LOSS:
                        action = "SELL"
                        reason = "stop_hit"
                    elif position.max_hold_until and now >= position.max_hold_until:
                        action = "SELL"
                        reason = "max_hold"

                    if action:
                        # Execute sell
                        from ib_insync import MarketOrder
                        order = MarketOrder("SELL", position.quantity)
                        trade = ib.placeOrder(contract, order)
                        ib.sleep(3)

                        fill_price = (trade.orderStatus.avgFillPrice
                                      if trade.orderStatus else current_price)
                        if fill_price == 0:
                            fill_price = current_price

                        pnl_amount = ((fill_price - position.entry_price) *
                                      position.quantity)
                        pnl_percent = ((fill_price - position.entry_price) /
                                       position.entry_price) * 100

                        # Prediction accuracy
                        predicted = position.predicted_gain_pct
                        actual = pnl_percent
                        prediction_accuracy = None
                        if predicted and predicted != 0:
                            prediction_accuracy = round(
                                1 - abs(actual - predicted) / abs(predicted), 4
                            )

                        # Save to trade history
                        history = TradeHistory(
                            ticker=position.ticker,
                            entry_price=position.entry_price,
                            exit_price=fill_price,
                            quantity=position.quantity,
                            entry_time=position.entry_time,
                            exit_time=now,
                            pnl_amount=round(pnl_amount, 2),
                            pnl_percent=round(pnl_percent, 2),
                            exit_reason=reason,
                            scoring_id=position.scoring_id,
                            predicted_gain_pct=predicted,
                            actual_gain_pct=round(actual, 2),
                            prediction_accuracy=prediction_accuracy,
                        )
                        session.add(history)
                        position.status = "closed"

                        actions.append({
                            "ticker": position.ticker,
                            "action": "SELL",
                            "reason": reason,
                            "exit_price": round(fill_price, 2),
                            "pnl_percent": round(pnl_percent, 2),
                            "pnl_amount": round(pnl_amount, 2),
                        })

                        logger.info(f"CLOSED {position.ticker}: {reason} "
                                    f"@ ${fill_price:.2f} ({pnl_percent:+.1f}%)")
                    else:
                        logger.info(f"{position.ticker}: ${current_price:.2f} "
                                    f"({pnl_pct*100:+.1f}%) — holding")

                    ib.cancelMktData(contract)
                    ib.sleep(0.3)

                except Exception as e:
                    logger.error(f"Error monitoring {position.ticker}: {e}")

    except Exception as e:
        logger.error(f"IBKR connection failed: {e}")
        log_agent("position_monitor", "error", f"IBKR connection failed: {e}")
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("position_monitor", "success",
              f"Checked positions, {len(actions)} actions taken",
              output_data={"actions": actions},
              execution_time_ms=elapsed_ms)

    print(json.dumps({
        "status": "ok",
        "actions_taken": len(actions),
        "actions": actions,
    }))


def force_close_all(reason: str = "eod_close"):
    """Force close all open positions (EOD)."""
    from ib_insync import IB, Stock, MarketOrder

    log_agent("position_monitor", "started", f"Force closing all positions: {reason}")

    with get_session() as session:
        positions = session.query(OpenPosition).filter(
            OpenPosition.status == "open"
        ).all()

        if not positions:
            print(json.dumps({"status": "ok", "closed": 0}))
            return

    ib = IB()
    closed = []
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_MONITOR)

        with get_session() as session:
            positions = session.query(OpenPosition).filter(
                OpenPosition.status == "open"
            ).all()

            for position in positions:
                try:
                    contract = Stock(position.ticker, "SMART", "USD")
                    ib.qualifyContracts(contract)

                    order = MarketOrder("SELL", position.quantity)
                    trade = ib.placeOrder(contract, order)
                    ib.sleep(3)

                    fill_price = (trade.orderStatus.avgFillPrice
                                  if trade.orderStatus else 0)

                    md = ib.reqMktData(contract, "", False, False)
                    ib.sleep(1)
                    if fill_price == 0:
                        fill_price = md.last or md.close or position.entry_price

                    pnl_amount = ((fill_price - position.entry_price) *
                                  position.quantity)
                    pnl_percent = ((fill_price - position.entry_price) /
                                   position.entry_price) * 100

                    predicted = position.predicted_gain_pct
                    actual = pnl_percent
                    prediction_accuracy = None
                    if predicted and predicted != 0:
                        prediction_accuracy = round(
                            1 - abs(actual - predicted) / abs(predicted), 4
                        )

                    history = TradeHistory(
                        ticker=position.ticker,
                        entry_price=position.entry_price,
                        exit_price=fill_price,
                        quantity=position.quantity,
                        entry_time=position.entry_time,
                        exit_time=datetime.now(timezone.utc),
                        pnl_amount=round(pnl_amount, 2),
                        pnl_percent=round(pnl_percent, 2),
                        exit_reason=reason,
                        scoring_id=position.scoring_id,
                        predicted_gain_pct=predicted,
                        actual_gain_pct=round(actual, 2),
                        prediction_accuracy=prediction_accuracy,
                    )
                    session.add(history)
                    position.status = "force_closed"

                    closed.append({
                        "ticker": position.ticker,
                        "pnl_percent": round(pnl_percent, 2),
                    })

                except Exception as e:
                    logger.error(f"Failed to close {position.ticker}: {e}")

    except Exception as e:
        logger.error(f"IBKR connection failed: {e}")
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    log_agent("position_monitor", "success",
              f"Force closed {len(closed)} positions ({reason})")

    print(json.dumps({
        "status": "ok",
        "closed": len(closed),
        "details": closed,
    }))


if __name__ == "__main__":
    init_db()

    import argparse
    parser = argparse.ArgumentParser(description="Position monitor")
    parser.add_argument("--mode", default="check",
                        choices=["check", "force_close"],
                        help="Monitor mode")
    parser.add_argument("--reason", default="eod_close",
                        help="Reason for force close")
    args = parser.parse_args()

    if args.mode == "check":
        check_positions()
    elif args.mode == "force_close":
        force_close_all(args.reason)
