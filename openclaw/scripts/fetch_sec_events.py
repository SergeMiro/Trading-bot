#!/usr/bin/env python3
"""
Agent-2: SEC Events Detector.
Scans SEC EDGAR for Form 4 (insider trades), 8-K, S-3 (dilution) filings.
Assigns weights and red flags.
Output: /data/sec_events.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import SEC_USER_AGENT, DATA_DIR, LOG_LEVEL
from db_utils import get_session, SecEvent, log_agent, init_db

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("fetch_sec_events")

HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}

# Event weight configuration
EVENT_WEIGHTS = {
    "form4_buy": +15,       # Insider purchase
    "form4_sell": -10,       # Insider sale
    "8k_positive": +10,      # Positive corporate event
    "8k_negative": -20,      # Negative corporate event
    "s3_dilution": -100,     # Secondary offering → RED FLAG
    "guidance_raise": +20,   # Guidance raised
}

# Keywords for 8-K sentiment classification
POSITIVE_8K_KEYWORDS = [
    "acquisition", "merger", "contract", "partnership", "revenue increase",
    "positive", "growth", "expansion", "dividend increase", "buyback",
    "share repurchase", "strategic alliance",
]
NEGATIVE_8K_KEYWORDS = [
    "lawsuit", "litigation", "penalty", "fine", "SEC investigation",
    "restatement", "fraud", "default", "bankruptcy", "layoff",
    "restructuring charge", "write-down", "impairment",
]


def search_sec_filings(ticker: str, form_type: str, days: int = 14) -> list[dict]:
    """Search SEC EDGAR EFTS for specific form types."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": ticker,
        "forms": form_type,
        "dateRange": "custom",
        "startdt": since,
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json().get("hits", {}).get("hits", [])
    except Exception as e:
        logger.warning(f"SEC search failed for {ticker}/{form_type}: {e}")
        return []


def classify_8k_sentiment(hit: dict) -> str:
    """Classify 8-K filing as positive or negative based on text content."""
    text = json.dumps(hit.get("_source", {})).lower()

    pos_score = sum(1 for kw in POSITIVE_8K_KEYWORDS if kw in text)
    neg_score = sum(1 for kw in NEGATIVE_8K_KEYWORDS if kw in text)

    if neg_score > pos_score:
        return "negative"
    elif pos_score > neg_score:
        return "positive"
    return "neutral"


def analyze_form4(hits: list[dict]) -> list[dict]:
    """Analyze Form 4 filings for insider buy/sell patterns."""
    events = []
    for hit in hits:
        source = hit.get("_source", {})
        text = json.dumps(source).lower()
        filing_date = source.get("file_date", "")

        # Simple heuristic: check for acquisition vs disposition
        is_buy = "acquisition" in text or "purchase" in text or "a -" in text
        is_sell = "disposition" in text or "sale" in text or "d -" in text

        if is_buy:
            events.append({
                "type": "Form4_Buy",
                "weight": EVENT_WEIGHTS["form4_buy"],
                "description": f"Insider purchase detected on {filing_date}",
                "filing_date": filing_date,
            })
        elif is_sell:
            events.append({
                "type": "Form4_Sell",
                "weight": EVENT_WEIGHTS["form4_sell"],
                "description": f"Insider sale detected on {filing_date}",
                "filing_date": filing_date,
            })
    return events


def analyze_ticker(ticker: str, days: int = 14) -> dict:
    """Full analysis for a single ticker across all SEC form types."""
    result = {
        "ticker": ticker,
        "events": [],
        "total_score": 0,
        "red_flag": False,
        "analysis_period_days": days,
    }

    # 1. Check S-3 (dilution) — highest priority red flag
    s3_hits = search_sec_filings(ticker, "S-3", days)
    if s3_hits:
        result["events"].append({
            "type": "S-3_Dilution",
            "weight": EVENT_WEIGHTS["s3_dilution"],
            "description": f"Secondary offering (S-3) filed — {len(s3_hits)} filing(s)",
            "filing_date": s3_hits[0].get("_source", {}).get("file_date", ""),
        })
        result["red_flag"] = True
        result["total_score"] = EVENT_WEIGHTS["s3_dilution"]
        logger.warning(f"RED FLAG: {ticker} has S-3 filing — excluded")
        return result

    # 2. Form 4 (insider trades)
    form4_hits = search_sec_filings(ticker, "4", days)
    form4_events = analyze_form4(form4_hits[:10])  # Limit to latest 10
    for evt in form4_events:
        result["events"].append(evt)
        result["total_score"] += evt["weight"]

    # 3. 8-K (corporate events)
    k8_hits = search_sec_filings(ticker, "8-K", days)
    for hit in k8_hits[:5]:  # Latest 5
        sentiment = classify_8k_sentiment(hit)
        filing_date = hit.get("_source", {}).get("file_date", "")

        if sentiment == "positive":
            weight = EVENT_WEIGHTS["8k_positive"]
        elif sentiment == "negative":
            weight = EVENT_WEIGHTS["8k_negative"]
        else:
            weight = 0

        if weight != 0:
            result["events"].append({
                "type": f"8-K_{sentiment}",
                "weight": weight,
                "description": f"8-K ({sentiment}) filed on {filing_date}",
                "filing_date": filing_date,
            })
            result["total_score"] += weight

    # Rate limit: SEC requires polite behavior
    time.sleep(0.5)

    return result


def save_to_db(results: list[dict], scan_date: str):
    """Persist SEC events to PostgreSQL."""
    with get_session() as session:
        for company in results:
            for event in company.get("events", []):
                entry = SecEvent(
                    ticker=company["ticker"],
                    event_type=event["type"],
                    description=event.get("description", ""),
                    weight=event.get("weight", 0),
                    red_flag=company.get("red_flag", False),
                    filing_date=event.get("filing_date", ""),
                    total_score=company.get("total_score", 0),
                    scan_date=scan_date,
                )
                session.add(entry)


def main(tickers_str: str, output_path: str, days: int = 14):
    start_time = time.time()
    tickers = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    log_agent("events_agent", "started",
              f"Analyzing {len(tickers)} tickers for SEC events (last {days} days)",
              input_data={"tickers": tickers, "days": days})

    results = []
    for ticker in tickers:
        try:
            result = analyze_ticker(ticker, days)
            results.append(result)
            logger.info(f"{ticker}: score={result['total_score']}, "
                        f"red_flag={result['red_flag']}, events={len(result['events'])}")
        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "events": [],
                "total_score": 0,
                "red_flag": False,
                "error": str(e),
            })

    filtered_out = [r["ticker"] for r in results if r["red_flag"]]
    passed = [r["ticker"] for r in results if not r["red_flag"]]

    output = {
        "companies": results,
        "filtered_out": filtered_out,
        "passed": passed,
        "total_analyzed": len(results),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        save_to_db(results, scan_date)
    except Exception as e:
        logger.warning(f"DB save failed (non-critical): {e}")

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("events_agent", "success",
              f"Passed: {len(passed)}, Filtered out: {len(filtered_out)}",
              output_data={"passed": len(passed), "filtered_out": len(filtered_out)},
              execution_time_ms=elapsed_ms)

    print(json.dumps({
        "status": "ok",
        "passed": len(passed),
        "filtered_out": len(filtered_out),
        "red_flags": filtered_out,
    }))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Fetch SEC events for tickers")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--days", type=int, default=14, help="Lookback period in days")
    parser.add_argument("--output", default=str(DATA_DIR / "sec_events.json"),
                        help="Output JSON path")
    args = parser.parse_args()
    main(args.tickers, args.output, args.days)
