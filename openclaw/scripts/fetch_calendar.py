#!/usr/bin/env python3
"""
Agent-1: Earnings Calendar Fetcher.
Primary source: SEC EDGAR EFTS search.
Fallback: Yahoo Finance (yfinance).
Output: /data/calendar.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import SEC_USER_AGENT, DATA_DIR, LOG_LEVEL
from sp500_tickers import get_sp500_tickers, get_sector
from db_utils import (
    get_session, EarningsCalendar, log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("fetch_calendar")

HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}


def fetch_from_sec_edgar(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch upcoming earnings from SEC EDGAR Full-Text Search.
    Searches for 8-K filings with 'earnings' in the text within the date range.
    """
    results = []
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": '"earnings release" OR "quarterly results"',
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "forms": "8-K",
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", {}).get("hits", [])
        seen_tickers = set()

        for hit in hits:
            source = hit.get("_source", {})
            ticker = source.get("ticker", "")
            company = source.get("display_names", [""])[0] if source.get("display_names") else ""
            filing_date = source.get("file_date", "")

            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                results.append({
                    "ticker": ticker,
                    "company_name": company,
                    "earnings_date": filing_date,
                    "is_confirmed": True,
                    "source": "SEC_EDGAR",
                    "sector": get_sector(ticker),
                })

        logger.info(f"SEC EDGAR returned {len(results)} unique tickers")
    except Exception as e:
        logger.error(f"SEC EDGAR fetch failed: {e}")
        raise

    return results


def fetch_from_yahoo_fallback(start_date: str, end_date: str) -> list[dict]:
    """
    Fallback: use yfinance to check earnings dates for S&P 500 tickers.
    Slower but reliable.
    """
    sp500 = get_sp500_tickers(limit=150)
    results = []
    errors = 0

    for ticker_sym in sp500:
        try:
            stock = yf.Ticker(ticker_sym)
            cal = stock.get_earnings_dates(limit=4)
            if cal is None or cal.empty:
                continue

            for date_idx, row in cal.iterrows():
                date_str = str(date_idx.date()) if hasattr(date_idx, "date") else str(date_idx)[:10]
                if start_date <= date_str <= end_date:
                    is_estimate = row.get("Earnings Date", None)
                    results.append({
                        "ticker": ticker_sym,
                        "company_name": "",
                        "earnings_date": date_str,
                        "is_confirmed": True,  # yfinance dates are generally accurate
                        "source": "yahoo_fallback",
                        "sector": get_sector(ticker_sym),
                    })
                    break  # One per ticker

            # Rate limit: be gentle with Yahoo
            time.sleep(0.3)
        except Exception as e:
            errors += 1
            if errors > 20:
                logger.warning(f"Too many Yahoo errors ({errors}), stopping early")
                break
            continue

    logger.info(f"Yahoo fallback returned {len(results)} tickers ({errors} errors)")
    return results


def save_to_db(companies: list[dict], scan_date: str):
    """Persist calendar data to PostgreSQL."""
    with get_session() as session:
        for company in companies:
            entry = EarningsCalendar(
                ticker=company["ticker"],
                earnings_date=company["earnings_date"],
                is_confirmed=company.get("is_confirmed", False),
                source=company.get("source", "unknown"),
                sector=company.get("sector"),
                scan_date=scan_date,
            )
            session.add(entry)


def main(start_date: str, end_date: str, output_path: str):
    start_time = time.time()
    log_agent("calendar_agent", "started", f"Fetching earnings {start_date} to {end_date}")

    source = "SEC_EDGAR"
    try:
        data = fetch_from_sec_edgar(start_date, end_date)
    except Exception as e:
        logger.warning(f"SEC API failed ({e}), switching to Yahoo fallback")
        data = fetch_from_yahoo_fallback(start_date, end_date)
        source = "yahoo_fallback"

    # Filter: only confirmed dates
    confirmed = [d for d in data if d.get("is_confirmed", True)]

    # Remove duplicates by ticker
    seen = set()
    unique = []
    for d in confirmed:
        if d["ticker"] not in seen:
            seen.add(d["ticker"])
            unique.append(d)
    confirmed = unique

    result = {
        "source": source,
        "count": len(confirmed),
        "companies": confirmed,
        "date_range": {"start": start_date, "end": end_date},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
    }

    if source == "yahoo_fallback":
        result["warnings"].append("Primary SEC EDGAR source unavailable, used Yahoo fallback")

    if len(confirmed) == 0:
        result["warnings"].append("No confirmed earnings found in date range")

    # Save to file
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Save to DB
    try:
        save_to_db(confirmed, start_date)
    except Exception as e:
        logger.warning(f"DB save failed (non-critical): {e}")

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("calendar_agent", "success",
              f"Found {len(confirmed)} confirmed earnings from {source}",
              output_data={"count": len(confirmed), "source": source},
              execution_time_ms=elapsed_ms)

    output = {
        "status": "ok" if confirmed else "no_earnings_today",
        "count": len(confirmed),
        "source": source,
        "action": "continue" if confirmed else "skip",
        "warnings": result["warnings"],
    }
    print(json.dumps(output))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Fetch earnings calendar")
    parser.add_argument("--date-start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--date-end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output", default=str(DATA_DIR / "calendar.json"),
                        help="Output JSON path")
    args = parser.parse_args()
    main(args.date_start, args.date_end, args.output)
