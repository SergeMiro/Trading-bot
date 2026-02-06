"""Risk management — position sizing, stop-loss, take-profit calculations."""

import structlog

from src.config import settings

logger = structlog.get_logger()


def calculate_position_size(account_balance: float, entry_price: float) -> int:
    """Calculate position size based on risk-per-trade and stop-loss.

    Formula:
        risk_amount = account_balance * risk_per_trade  (e.g. 2%)
        risk_per_share = entry_price * stop_loss         (e.g. 5%)
        shares = risk_amount / risk_per_share
    """
    risk_amount = account_balance * settings.risk_per_trade
    risk_per_share = entry_price * settings.stop_loss

    if risk_per_share <= 0:
        logger.warning("risk_per_share_zero", entry_price=entry_price)
        return 0

    shares = int(risk_amount / risk_per_share)
    logger.info(
        "position_size_calculated",
        balance=account_balance,
        entry_price=entry_price,
        shares=shares,
        risk_amount=risk_amount,
    )
    return max(shares, 1)


def calculate_stop_loss_price(entry_price: float) -> float:
    """Calculate stop-loss price (-5% from entry)."""
    return round(entry_price * (1 - settings.stop_loss), 4)


def calculate_target_price(entry_price: float) -> float:
    """Calculate take-profit price (+8% from entry)."""
    return round(entry_price * (1 + settings.target_gain), 4)


def calculate_pnl(entry_price: float, current_price: float) -> float:
    """Calculate P&L percentage."""
    if entry_price <= 0:
        return 0.0
    return (current_price - entry_price) / entry_price
