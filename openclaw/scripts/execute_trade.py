#!/usr/bin/env python3
"""
Trade Executor: Places BUY/SELL orders via IBKR API.
Called by Master Orchestrator after Agent-6 validation.

Modes:
  --mode buy     → Open new position (limit order)
  --mode sell    → Close position (market order)
  --mode status  → Report open positions
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID_TRADE,
    RISK_PER_TRADE, MAX_CONCURRENT_POSITIONS, TARGET_GAIN, STOP_LOSS,
    MAX_HOLD_DAYS, DATA_DIR, LOG_LEVEL
)
from db_utils import (
    get_session, OpenPosition, TradeHistory, ScoringResult,
    log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("execute_trade")


def get_portfolio_value(ib) -> float:
    """Get total portfolio value from IBKR."""
    account_values = ib.accountSummary()
    for av in account_values:
        if av.tag == "NetLiquidation" and av.currency == "USD":
            return float(av.value)
    return 100000.0  # Default for paper trading


def calculate_position_size(portfolio_value: float, entry_price: float,
                            stop_price: float) -> int:
    """
    Calculate position size based on risk-per-trade rule.
    Risk = RISK_PER_TRADE * portfolio_value
    Size = Risk / (entry_price - stop_price)
    """
    risk_amount = portfolio_value * RISK_PER_TRADE
    risk_per_share = abs(entry_price - stop_price)

    if risk_per_share <= 0:
        risk_per_share = entry_price * STOP_LOSS

    quantity = int(risk_amount / risk_per_share)
    return max(1, quantity)


def count_open_positions() -> int:
    """Count currently open positions in DB."""
    with get_session() as session:
        return session.query(OpenPosition).filter(
            OpenPosition.status == "open"
        ).count()


def execute_buy(ticker: str, entry_price: float, target_price: float,
                stop_price: float, scoring_id: int = None,
                predicted_gain_pct: float = None):
    """Execute a BUY order for a ticker."""
    from ib_insync import IB, Stock, LimitOrder, StopOrder

    start_time = time.time()

    # Check position limit
    open_count = count_open_positions()
    if open_count >= MAX_CONCURRENT_POSITIONS:
        msg = (f"Cannot open position for {ticker}: "
               f"already at max ({open_count}/{MAX_CONCURRENT_POSITIONS})")
        logger.warning(msg)
        log_agent("trade_executor", "warning", msg)
        print(json.dumps({"status": "rejected", "reason": "max_positions_reached",
                          "open_count": open_count}))
        return

    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_TRADE)
        portfolio_value = get_portfolio_value(ib)

        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)

        quantity = calculate_position_size(portfolio_value, entry_price, stop_price)

        # Place limit order at entry price
        order = LimitOrder("BUY", quantity, entry_price)
        order.tif = "DAY"  # Day order only
        trade = ib.placeOrder(contract, order)

        ib.sleep(3)  # Wait for order acknowledgment

        order_status = trade.orderStatus.status if trade.orderStatus else "Unknown"
        logger.info(f"BUY order placed: {ticker} x{quantity} @ ${entry_price} "
                     f"→ status={order_status}")

        # Place bracket orders (take profit + stop loss)
        if order_status in ("Submitted", "Filled", "PreSubmitted"):
            # Take profit
            tp_order = LimitOrder("SELL", quantity, target_price)
            tp_order.tif = "GTC"
            ib.placeOrder(contract, tp_order)

            # Stop loss
            sl_order = StopOrder("SELL", quantity, stop_price)
            sl_order.tif = "GTC"
            ib.placeOrder(contract, sl_order)

        # Save to DB
        max_hold_until = datetime.now(timezone.utc) + timedelta(days=MAX_HOLD_DAYS)
        with get_session() as session:
            position = OpenPosition(
                ticker=ticker,
                entry_price=entry_price,
                quantity=quantity,
                entry_time=datetime.now(timezone.utc),
                target_price=target_price,
                stop_price=stop_price,
                max_hold_until=max_hold_until,
                scoring_id=scoring_id,
                status="open",
                predicted_gain_pct=predicted_gain_pct,
            )
            session.add(position)

        elapsed_ms = int((time.time() - start_time) * 1000)
        log_agent("trade_executor", "success",
                  f"BUY {ticker} x{quantity} @ ${entry_price} "
                  f"(target=${target_price}, stop=${stop_price})",
                  execution_time_ms=elapsed_ms)

        print(json.dumps({
            "status": "ok",
            "action": "BUY",
            "ticker": ticker,
            "quantity": quantity,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_price": stop_price,
            "order_status": order_status,
            "portfolio_value": round(portfolio_value, 2),
            "risk_amount": round(portfolio_value * RISK_PER_TRADE, 2),
        }))

    except Exception as e:
        logger.error(f"BUY execution failed for {ticker}: {e}")
        log_agent("trade_executor", "error", f"BUY failed: {ticker} — {e}")
        print(json.dumps({"status": "error", "ticker": ticker, "error": str(e)}))
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def execute_sell(ticker: str, reason: str = "manual"):
    """Execute a SELL (close position) for a ticker."""
    from ib_insync import IB, Stock, MarketOrder

    start_time = time.time()

    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_TRADE)

        # Get open position from DB
        with get_session() as session:
            position = session.query(OpenPosition).filter(
                OpenPosition.ticker == ticker,
                OpenPosition.status == "open"
            ).first()

            if not position:
                print(json.dumps({"status": "error", "reason": "no_open_position"}))
                return

            contract = Stock(ticker, "SMART", "USD")
            ib.qualifyContracts(contract)

            # Market order to close
            order = MarketOrder("SELL", position.quantity)
            trade = ib.placeOrder(contract, order)
            ib.sleep(3)

            # Get fill price
            fill_price = trade.orderStatus.avgFillPrice if trade.orderStatus else 0
            if fill_price == 0:
                # Try to get last price
                md = ib.reqMktData(contract, "", False, False)
                ib.sleep(2)
                fill_price = md.last or md.close or position.entry_price

            # Calculate P&L
            pnl_amount = (fill_price - position.entry_price) * position.quantity
            pnl_percent = ((fill_price - position.entry_price) / position.entry_price) * 100

            # Calculate prediction accuracy
            predicted = position.predicted_gain_pct
            actual = pnl_percent
            prediction_accuracy = None
            if predicted and predicted != 0:
                prediction_accuracy = round(1 - abs(actual - predicted) / abs(predicted), 4)

            # Move to trade history
            history_entry = TradeHistory(
                ticker=ticker,
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
            session.add(history_entry)

            # Close position
            position.status = "closed"

        elapsed_ms = int((time.time() - start_time) * 1000)
        log_agent("trade_executor", "success",
                  f"SELL {ticker} @ ${fill_price:.2f} | P&L: {pnl_percent:+.2f}% "
                  f"(${pnl_amount:+.2f}) | reason={reason}",
                  execution_time_ms=elapsed_ms)

        print(json.dumps({
            "status": "ok",
            "action": "SELL",
            "ticker": ticker,
            "exit_price": round(fill_price, 2),
            "pnl_percent": round(pnl_percent, 2),
            "pnl_amount": round(pnl_amount, 2),
            "exit_reason": reason,
            "predicted_gain_pct": predicted,
            "actual_gain_pct": round(actual, 2),
        }))

    except Exception as e:
        logger.error(f"SELL execution failed for {ticker}: {e}")
        log_agent("trade_executor", "error", f"SELL failed: {ticker} — {e}")
        print(json.dumps({"status": "error", "ticker": ticker, "error": str(e)}))
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def get_positions_status():
    """Report all open positions."""
    with get_session() as session:
        positions = session.query(OpenPosition).filter(
            OpenPosition.status == "open"
        ).all()

        result = []
        for p in positions:
            result.append({
                "ticker": p.ticker,
                "entry_price": p.entry_price,
                "quantity": p.quantity,
                "target_price": p.target_price,
                "stop_price": p.stop_price,
                "entry_time": p.entry_time.isoformat() if p.entry_time else None,
                "max_hold_until": p.max_hold_until.isoformat() if p.max_hold_until else None,
                "predicted_gain_pct": p.predicted_gain_pct,
            })

    print(json.dumps({
        "status": "ok",
        "open_positions": len(result),
        "positions": result,
    }))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Execute trades via IBKR")
    parser.add_argument("--mode", required=True,
                        choices=["buy", "sell", "status"])
    parser.add_argument("--ticker", help="Ticker symbol")
    parser.add_argument("--entry-price", type=float, help="Entry price (buy)")
    parser.add_argument("--target-price", type=float, help="Target price (buy)")
    parser.add_argument("--stop-price", type=float, help="Stop price (buy)")
    parser.add_argument("--scoring-id", type=int, help="Scoring result ID")
    parser.add_argument("--predicted-gain", type=float, help="Predicted gain %")
    parser.add_argument("--reason", default="manual",
                        help="Sell reason (target_hit, stop_hit, max_hold, manual)")
    args = parser.parse_args()

    if args.mode == "buy":
        execute_buy(
            ticker=args.ticker,
            entry_price=args.entry_price,
            target_price=args.target_price,
            stop_price=args.stop_price,
            scoring_id=args.scoring_id,
            predicted_gain_pct=args.predicted_gain,
        )
    elif args.mode == "sell":
        execute_sell(ticker=args.ticker, reason=args.reason)
    elif args.mode == "status":
        get_positions_status()
