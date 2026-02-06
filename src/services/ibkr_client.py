import structlog
from ib_insync import IB, Contract, MarketOrder, LimitOrder, StopOrder, Stock, util

from src.config import settings

logger = structlog.get_logger()

_ib: IB | None = None


def get_ib() -> IB:
    """Get or create IBKR connection."""
    global _ib
    if _ib is None or not _ib.isConnected():
        _ib = IB()
        _ib.connect(
            settings.ibkr_host,
            settings.ibkr_port,
            clientId=settings.ibkr_client_id,
        )
        logger.info("ibkr_connected", host=settings.ibkr_host, port=settings.ibkr_port)
    return _ib


def disconnect():
    """Disconnect from IBKR."""
    global _ib
    if _ib and _ib.isConnected():
        _ib.disconnect()
        logger.info("ibkr_disconnected")
    _ib = None


def make_stock_contract(ticker: str) -> Stock:
    return Stock(ticker, "SMART", "USD")


def get_historical_bars(ticker: str, duration: str = "30 D", bar_size: str = "1 hour") -> list:
    """Get historical price bars from IBKR."""
    ib = get_ib()
    contract = make_stock_contract(ticker)
    ib.qualifyContracts(contract)

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=False,
    )
    logger.info("ibkr_historical", ticker=ticker, bars=len(bars))
    return bars


def get_snapshot(ticker: str) -> dict | None:
    """Get current market snapshot for a ticker."""
    ib = get_ib()
    contract = make_stock_contract(ticker)
    ib.qualifyContracts(contract)

    ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    ticker_data = ib.ticker(contract)

    if ticker_data is None:
        return None

    return {
        "last": ticker_data.last,
        "bid": ticker_data.bid,
        "ask": ticker_data.ask,
        "volume": ticker_data.volume,
    }


def get_account_balance() -> float:
    """Get total account balance."""
    ib = get_ib()
    summary = ib.accountSummary()
    for item in summary:
        if item.tag == "NetLiquidation" and item.currency == "USD":
            return float(item.value)
    return 0.0


def place_market_order(ticker: str, action: str, quantity: int) -> dict:
    """Place a market order (BUY or SELL)."""
    ib = get_ib()
    contract = make_stock_contract(ticker)
    ib.qualifyContracts(contract)

    order = MarketOrder(action, quantity)
    trade = ib.placeOrder(contract, order)
    ib.sleep(2)

    logger.info(
        "ibkr_order",
        ticker=ticker,
        action=action,
        quantity=quantity,
        status=trade.orderStatus.status,
    )
    return {
        "ticker": ticker,
        "action": action,
        "quantity": quantity,
        "status": trade.orderStatus.status,
        "avg_fill_price": trade.orderStatus.avgFillPrice,
    }


def place_stop_order(ticker: str, quantity: int, stop_price: float) -> dict:
    """Place a stop-loss order."""
    ib = get_ib()
    contract = make_stock_contract(ticker)
    ib.qualifyContracts(contract)

    order = StopOrder("SELL", quantity, stop_price)
    trade = ib.placeOrder(contract, order)
    logger.info("ibkr_stop_order", ticker=ticker, stop_price=stop_price)
    return {"status": trade.orderStatus.status}


def place_limit_order(ticker: str, quantity: int, limit_price: float) -> dict:
    """Place a take-profit limit order."""
    ib = get_ib()
    contract = make_stock_contract(ticker)
    ib.qualifyContracts(contract)

    order = LimitOrder("SELL", quantity, limit_price)
    trade = ib.placeOrder(contract, order)
    logger.info("ibkr_limit_order", ticker=ticker, limit_price=limit_price)
    return {"status": trade.orderStatus.status}
