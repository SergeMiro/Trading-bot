"""Trade executor — places BUY/SELL orders via IBKR."""

from datetime import datetime

import structlog

from src.db.models import OpenPosition
from src.db.session import SessionLocal
from src.services import ibkr_client
from src.trading.risk import calculate_position_size, calculate_stop_loss_price, calculate_target_price

logger = structlog.get_logger()


def execute_buy(ticker: str, score: int, confidence: float) -> dict | None:
    """Execute a BUY order for a ticker with full risk management."""
    logger.info("execute_buy_start", ticker=ticker, score=score)

    # Step 1: Get account balance
    account_balance = ibkr_client.get_account_balance()
    if account_balance <= 0:
        logger.error("no_account_balance")
        return None

    # Step 2: Get current price
    snapshot = ibkr_client.get_snapshot(ticker)
    if not snapshot or not snapshot.get("last"):
        logger.error("no_price_data", ticker=ticker)
        return None

    entry_price = snapshot["last"]

    # Step 3: Calculate position size
    position_size = calculate_position_size(account_balance, entry_price)
    if position_size <= 0:
        logger.warning("zero_position_size", ticker=ticker)
        return None

    # Step 4: Place market buy order
    order_result = ibkr_client.place_market_order(ticker, "BUY", position_size)
    avg_fill_price = order_result.get("avg_fill_price", entry_price)

    # Step 5: Calculate SL/TP
    stop_price = calculate_stop_loss_price(avg_fill_price)
    target_price = calculate_target_price(avg_fill_price)

    # Step 6: Place stop-loss and take-profit orders
    ibkr_client.place_stop_order(ticker, position_size, stop_price)
    ibkr_client.place_limit_order(ticker, position_size, target_price)

    # Step 7: Save position to DB
    _save_position(ticker, avg_fill_price, position_size, stop_price, target_price)

    logger.info(
        "buy_executed",
        ticker=ticker,
        price=avg_fill_price,
        size=position_size,
        stop=stop_price,
        target=target_price,
    )

    return {
        "ticker": ticker,
        "entry_price": avg_fill_price,
        "position_size": position_size,
        "stop_loss": stop_price,
        "target": target_price,
    }


def execute_sell(ticker: str, position_size: int, reason: str) -> dict | None:
    """Execute a SELL order to close a position."""
    logger.info("execute_sell_start", ticker=ticker, reason=reason)

    order_result = ibkr_client.place_market_order(ticker, "SELL", position_size)

    logger.info(
        "sell_executed",
        ticker=ticker,
        size=position_size,
        price=order_result.get("avg_fill_price"),
        reason=reason,
    )

    return {
        "ticker": ticker,
        "exit_price": order_result.get("avg_fill_price"),
        "reason": reason,
    }


def _save_position(
    ticker: str,
    entry_price: float,
    position_size: int,
    stop_loss_price: float,
    target_price: float,
):
    """Save open position to database."""
    session = SessionLocal()
    try:
        position = OpenPosition(
            ticker=ticker,
            entry_price=entry_price,
            position_size=position_size,
            stop_loss_price=stop_loss_price,
            target_price=target_price,
            entry_date=datetime.now(),
            status="OPEN",
        )
        session.add(position)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("save_position_error", ticker=ticker, error=str(e))
    finally:
        session.close()
