#!/usr/bin/env python3
"""
Agent-5: Scoring Engine.
Calculates composite score for each earnings candidate.
Combines: volume ratio, ATR, market sentiment, sector strength, SEC events.
Output: /data/scoring_result.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import (
    SCORE_BUY, SCORE_HOLD, TARGET_GAIN, STOP_LOSS, MAX_HOLD_DAYS,
    DATA_DIR, LOG_LEVEL
)
from db_utils import get_session, ScoringResult, log_agent, init_db

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("scoring_engine")


# ─── Scoring Rules ────────────────────────────────────────────

def score_volume_ratio(ratio: float) -> tuple[int, str]:
    """Score based on pre-market volume ratio vs 14-day average."""
    if ratio >= 2.0:
        return 25, f"volume_ratio={ratio:.1f}x (>=2.0 → +25)"
    elif ratio >= 1.5:
        return 20, f"volume_ratio={ratio:.1f}x (>=1.5 → +20)"
    elif ratio >= 1.2:
        return 10, f"volume_ratio={ratio:.1f}x (>=1.2 → +10)"
    else:
        return 0, f"volume_ratio={ratio:.1f}x (<1.2 → +0)"


def score_atr(atr: float) -> tuple[int, str]:
    """Score based on 5-day ATR (optimal volatility window)."""
    if 2.0 <= atr <= 5.0:
        return 10, f"ATR={atr:.1f} (2.0-5.0 optimal → +10)"
    elif 5.0 < atr <= 8.0:
        return 5, f"ATR={atr:.1f} (5.0-8.0 elevated → +5)"
    else:
        return 0, f"ATR={atr:.1f} (out of range → +0)"


def score_market_sentiment(sentiment: str) -> tuple[int, str]:
    """Score based on overall market direction."""
    scores = {
        "bullish": (15, "market=bullish → +15"),
        "neutral": (5, "market=neutral → +5"),
        "bearish": (-10, "market=bearish → -10"),
    }
    return scores.get(sentiment, (0, f"market={sentiment} → +0"))


def score_sector_movement(change: float) -> tuple[int, str]:
    """Score based on sector ETF overnight change."""
    if change > 0.005:
        return 15, f"sector={change*100:.1f}% (>0.5% → +15)"
    elif change >= 0:
        return 8, f"sector={change*100:.1f}% (0-0.5% → +8)"
    else:
        return -5, f"sector={change*100:.1f}% (<0% → -5)"


def score_sec_events(sec_score: int) -> tuple[int, str]:
    """Pass-through SEC events score from Agent-2."""
    return sec_score, f"SEC_events_score={sec_score} (direct)"


# ─── Main Scoring Logic ──────────────────────────────────────

def calculate_score(stock: dict, sec_data: dict, market_sentiment: str) -> dict:
    """Calculate final composite score for a single ticker."""
    ticker = stock["ticker"]
    breakdown = []
    total = 0

    # 1. Volume ratio
    pts, desc = score_volume_ratio(stock.get("volume_ratio", 0))
    total += pts
    breakdown.append({"factor": "volume_ratio", "points": pts, "detail": desc})

    # 2. ATR
    pts, desc = score_atr(stock.get("atr_5d", 0))
    total += pts
    breakdown.append({"factor": "atr_5d", "points": pts, "detail": desc})

    # 3. Market sentiment
    pts, desc = score_market_sentiment(market_sentiment)
    total += pts
    breakdown.append({"factor": "market_sentiment", "points": pts, "detail": desc})

    # 4. Sector movement
    pts, desc = score_sector_movement(stock.get("sector_etf_change", 0))
    total += pts
    breakdown.append({"factor": "sector_movement", "points": pts, "detail": desc})

    # 5. SEC events
    sec_score = sec_data.get("total_score", 0)
    pts, desc = score_sec_events(sec_score)
    total += pts
    breakdown.append({"factor": "sec_events", "points": pts, "detail": desc})

    # Determine recommendation
    if total >= SCORE_BUY:
        recommendation = "BUY"
    elif total >= SCORE_HOLD:
        recommendation = "HOLD"
    else:
        recommendation = "SKIP"

    # Calculate entry/target/stop prices
    price = stock.get("premarket_price")
    entry_price = price
    target_price = round(price * (1 + TARGET_GAIN), 2) if price else None
    stop_price = round(price * (1 - STOP_LOSS), 2) if price else None

    return {
        "ticker": ticker,
        "final_score": total,
        "recommendation": recommendation,
        "breakdown": breakdown,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "target_gain_pct": TARGET_GAIN * 100,
        "stop_loss_pct": STOP_LOSS * 100,
        "max_hold_days": MAX_HOLD_DAYS,
        "entry_time": "10:15 AM (NY)",
        "market_sentiment": market_sentiment,
        "sector": stock.get("sector", "Unknown"),
    }


def main(premarket_path: str, sec_events_path: str, calendar_path: str, output_path: str):
    start_time = time.time()
    log_agent("scoring_agent", "started", "Calculating final scores")

    # Load all data files
    with open(premarket_path) as f:
        premarket = json.load(f)
    with open(sec_events_path) as f:
        sec_events = json.load(f)
    with open(calendar_path) as f:
        calendar = json.load(f)

    market_sentiment = premarket.get("market_sentiment", "neutral")

    # Build SEC data lookup
    sec_lookup = {}
    for company in sec_events.get("companies", []):
        sec_lookup[company["ticker"]] = company

    # Get today's earnings tickers
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    earnings_today = set()
    for c in calendar.get("companies", []):
        if c.get("earnings_date", "")[:10] == today:
            earnings_today.add(c["ticker"])

    # Score each stock from pre-market data
    results = []
    buy_signals = []
    hold_signals = []
    skip_signals = []

    for stock in premarket.get("stocks", []):
        ticker = stock["ticker"]

        # Skip stocks not in today's earnings (unless they have high volume)
        if ticker not in earnings_today and stock.get("volume_ratio", 0) < 2.0:
            continue

        # Skip red-flagged tickers
        if ticker in sec_events.get("filtered_out", []):
            continue

        sec_data = sec_lookup.get(ticker, {"total_score": 0})

        # Skip if price data is missing
        if not stock.get("premarket_price"):
            continue

        score = calculate_score(stock, sec_data, market_sentiment)
        results.append(score)

        if score["recommendation"] == "BUY":
            buy_signals.append(score)
        elif score["recommendation"] == "HOLD":
            hold_signals.append(score)
        else:
            skip_signals.append(score)

    # Sort by score descending
    results.sort(key=lambda x: x["final_score"], reverse=True)
    buy_signals.sort(key=lambda x: x["final_score"], reverse=True)

    output = {
        "results": results,
        "summary": {
            "total_scored": len(results),
            "buy_count": len(buy_signals),
            "hold_count": len(hold_signals),
            "skip_count": len(skip_signals),
            "market_sentiment": market_sentiment,
            "sp500_change": premarket.get("sp500_overnight_change", 0),
        },
        "buy_signals": buy_signals,
        "hold_signals": hold_signals,
        "thresholds": {
            "buy_min": SCORE_BUY,
            "hold_min": SCORE_HOLD,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Save to DB
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with get_session() as session:
            for r in results:
                entry = ScoringResult(
                    ticker=r["ticker"],
                    final_score=r["final_score"],
                    recommendation=r["recommendation"],
                    breakdown=r["breakdown"],
                    entry_price=r.get("entry_price"),
                    target_price=r.get("target_price"),
                    stop_price=r.get("stop_price"),
                    scan_date=scan_date,
                )
                session.add(entry)
    except Exception as e:
        logger.warning(f"DB save failed (non-critical): {e}")

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("scoring_agent", "success",
              f"Scored {len(results)} tickers: {len(buy_signals)} BUY, "
              f"{len(hold_signals)} HOLD, {len(skip_signals)} SKIP",
              output_data=output["summary"],
              execution_time_ms=elapsed_ms)

    print(json.dumps({
        "status": "ok",
        "total_scored": len(results),
        "buy_count": len(buy_signals),
        "hold_count": len(hold_signals),
        "skip_count": len(skip_signals),
        "top_picks": [{"ticker": s["ticker"], "score": s["final_score"]}
                      for s in buy_signals[:5]],
    }))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="Scoring engine for earnings candidates")
    parser.add_argument("--premarket", default=str(DATA_DIR / "premarket_data.json"))
    parser.add_argument("--sec-events", default=str(DATA_DIR / "sec_events.json"))
    parser.add_argument("--calendar", default=str(DATA_DIR / "calendar.json"))
    parser.add_argument("--output", default=str(DATA_DIR / "scoring_result.json"))
    args = parser.parse_args()
    main(args.premarket, args.sec_events, args.calendar, args.output)
