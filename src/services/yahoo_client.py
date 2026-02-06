from datetime import datetime, timedelta

import structlog
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def get_earnings_calendar(ticker: str) -> list[dict]:
    """Fetch upcoming earnings dates from Yahoo Finance (fallback)."""
    stock = yf.Ticker(ticker)
    try:
        dates = stock.earnings_dates
        if dates is None or dates.empty:
            return []

        results = []
        for idx, row in dates.iterrows():
            earnings_date = idx.to_pydatetime().date()
            results.append({
                "ticker": ticker,
                "earnings_date": str(earnings_date),
                "source": "YAHOO_FALLBACK",
            })
        logger.info("yahoo_earnings", ticker=ticker, count=len(results))
        return results
    except Exception as e:
        logger.warning("yahoo_earnings_error", ticker=ticker, error=str(e))
        return []


def get_stock_info(ticker: str) -> dict:
    """Get basic stock info (market cap, sector, etc.)."""
    stock = yf.Ticker(ticker)
    info = stock.info or {}
    return {
        "ticker": ticker,
        "company_name": info.get("longName", ""),
        "market_cap": info.get("marketCap", 0),
        "sector": info.get("sector", ""),
    }


def get_historical_data(ticker: str, period: str = "30d", interval: str = "1h") -> list[dict]:
    """Get historical price data."""
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, interval=interval)
    if hist.empty:
        return []

    return [
        {
            "date": str(idx),
            "open": row["Open"],
            "high": row["High"],
            "low": row["Low"],
            "close": row["Close"],
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]


def get_sp500_tickers() -> list[str]:
    """Get list of S&P 500 tickers from Wikipedia via yfinance/pandas."""
    import pandas as pd

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df = tables[0]
    return df["Symbol"].tolist()


def get_index_change(symbol: str = "SPY") -> float:
    """Get overnight change for an index ETF."""
    stock = yf.Ticker(symbol)
    hist = stock.history(period="2d")
    if len(hist) < 2:
        return 0.0
    prev_close = hist["Close"].iloc[-2]
    current = hist["Close"].iloc[-1]
    return (current - prev_close) / prev_close


def get_sector_etf_change(sector: str) -> float:
    """Get overnight change for a sector ETF."""
    sector_etfs = {
        "Technology": "XLK",
        "Healthcare": "XLV",
        "Financial Services": "XLF",
        "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP",
        "Energy": "XLE",
        "Industrials": "XLI",
        "Basic Materials": "XLB",
        "Utilities": "XLU",
        "Real Estate": "XLRE",
        "Communication Services": "XLC",
    }
    etf = sector_etfs.get(sector, "SPY")
    return get_index_change(etf)
