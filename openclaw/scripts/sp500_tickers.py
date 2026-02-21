"""
S&P 500 ticker list utilities.
Fetches from Wikipedia or uses a cached fallback list.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("sp500_tickers")

# Top 100 S&P 500 by market cap (fallback if Wikipedia fetch fails)
TOP_SP500 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B",
    "LLY", "AVGO", "JPM", "TSLA", "UNH", "V", "XOM", "MA", "PG", "JNJ",
    "COST", "HD", "ABBV", "MRK", "NFLX", "CRM", "BAC", "AMD", "CVX",
    "KO", "ORCL", "WMT", "PEP", "TMO", "ACN", "LIN", "MCD", "CSCO",
    "ABT", "ADBE", "WFC", "DHR", "PM", "NOW", "GE", "IBM", "TXN",
    "QCOM", "CAT", "INTU", "AMGN", "ISRG", "VZ", "AMAT", "GS", "BKNG",
    "AXP", "DIS", "SPGI", "BLK", "T", "PFE", "MS", "NEE", "LOW",
    "MDLZ", "RTX", "HON", "LRCX", "UNP", "SYK", "DE", "TJX", "PLD",
    "COP", "ELV", "VRTX", "REGN", "BMY", "CB", "ADP", "PANW", "BSX",
    "ANET", "FI", "SBUX", "SCHW", "GILD", "KLAC", "MMC", "ADI", "TMUS",
    "CME", "MU", "INTC", "PYPL", "ICE", "CI", "MCO", "SHW", "SNPS",
    "CDNS", "EQIX", "CRWD", "ZTS", "PH", "CMG", "MSI", "APH", "ETN",
    "WELL", "MAR", "AON", "ECL", "ORLY", "EMR", "ABNB", "MRVL", "FTNT",
    "NOC", "GD", "WM", "DXCM", "ITW", "MCK", "PSA", "TT", "CTAS",
    "COF", "CEG", "FDX", "APD", "AJG", "NXPI", "SLB", "CARR", "CSX",
    "ROP", "AFL", "AIG", "TDG", "FCX", "BK", "MET", "TRV", "PCAR",
]

# Sector ETF mapping for sector strength analysis
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

# Ticker → Sector mapping (top tickers)
TICKER_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMZN": "Consumer Discretionary", "META": "Communication Services",
    "GOOGL": "Communication Services", "GOOG": "Communication Services",
    "BRK-B": "Financials", "LLY": "Healthcare", "AVGO": "Technology",
    "JPM": "Financials", "TSLA": "Consumer Discretionary", "UNH": "Healthcare",
    "V": "Financials", "XOM": "Energy", "MA": "Financials",
    "PG": "Consumer Staples", "JNJ": "Healthcare", "COST": "Consumer Staples",
    "HD": "Consumer Discretionary", "ABBV": "Healthcare", "MRK": "Healthcare",
    "NFLX": "Communication Services", "CRM": "Technology", "BAC": "Financials",
    "AMD": "Technology", "CVX": "Energy", "KO": "Consumer Staples",
    "ORCL": "Technology", "WMT": "Consumer Staples", "PEP": "Consumer Staples",
    "TMO": "Healthcare", "ACN": "Technology", "LIN": "Materials",
    "MCD": "Consumer Discretionary", "CSCO": "Technology", "ABT": "Healthcare",
    "ADBE": "Technology", "WFC": "Financials", "DHR": "Healthcare",
    "PM": "Consumer Staples", "NOW": "Technology", "GE": "Industrials",
    "IBM": "Technology", "TXN": "Technology", "QCOM": "Technology",
    "CAT": "Industrials", "INTU": "Technology", "AMGN": "Healthcare",
    "ISRG": "Healthcare", "VZ": "Communication Services", "AMAT": "Technology",
    "GS": "Financials", "BKNG": "Consumer Discretionary", "AXP": "Financials",
    "DIS": "Communication Services", "SPGI": "Financials", "BLK": "Financials",
    "T": "Communication Services", "PFE": "Healthcare", "MS": "Financials",
    "NEE": "Utilities", "LOW": "Consumer Discretionary",
}


def get_sp500_tickers(limit: int = 100) -> list[str]:
    """Return top S&P 500 tickers by market cap."""
    return TOP_SP500[:limit]


def get_sector(ticker: str) -> str:
    """Get sector for a given ticker. Returns 'Unknown' if not mapped."""
    return TICKER_SECTORS.get(ticker, "Unknown")


def get_sector_etf(sector: str) -> str:
    """Get ETF ticker for a sector. Returns 'SPY' if sector not mapped."""
    return SECTOR_ETFS.get(sector, "SPY")


def save_sp500_cache(path: Path = None):
    """Save the S&P 500 list to a JSON file for reference."""
    if path is None:
        from config import DATA_DIR
        path = DATA_DIR / "sp500_top.json"
    data = {
        "tickers": TOP_SP500,
        "count": len(TOP_SP500),
        "sector_etfs": SECTOR_ETFS,
        "ticker_sectors": TICKER_SECTORS,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


if __name__ == "__main__":
    p = save_sp500_cache()
    print(f"Saved {len(TOP_SP500)} tickers to {p}")
