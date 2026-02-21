#!/usr/bin/env python3
"""
Agent-3 & Agent-4: IBKR Monitoring Setup & Pre-Market Data Fetch.
Connects to Interactive Brokers TWS via ib_insync.

Modes:
  --mode setup     → Agent-3: configure monitoring lines
  --mode premarket → Agent-4: fetch pre-market data
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID_SETUP, IBKR_CLIENT_ID_PREMARKET,
    MAX_MONITORING_LINES, DATA_DIR, LOG_LEVEL
)
from sp500_tickers import get_sp500_tickers, get_sector, get_sector_etf, SECTOR_ETFS
from db_utils import (
    get_session, MonitoringList, PremarketData, log_agent, init_db
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("ibkr_monitor")


def calculate_atr(bars, period: int = 14) -> float:
    """Calculate Average True Range from historical bars."""
    if not bars or len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(period, len(trs))


def setup_monitoring(tickers: list[str], output_path: str):
    """
    Agent-3: Set up monitoring for up to MAX_MONITORING_LINES tickers.
    Fills remaining slots with top S&P 500 stocks.
    """
    from ib_insync import IB, Stock

    start_time = time.time()
    log_agent("ibkr_setup_agent", "started",
              f"Setting up monitoring for {len(tickers)} earnings tickers")

    # Fill to MAX_MONITORING_LINES with S&P 500
    earnings_count = len(tickers)
    if len(tickers) < MAX_MONITORING_LINES:
        sp500 = get_sp500_tickers(limit=200)
        filler = [t for t in sp500 if t not in set(tickers)]
        tickers = tickers + filler[:MAX_MONITORING_LINES - len(tickers)]
    tickers = tickers[:MAX_MONITORING_LINES]
    sp500_filler_count = len(tickers) - earnings_count

    ib = IB()
    qualified = []
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_SETUP)
        logger.info(f"Connected to IBKR at {IBKR_HOST}:{IBKR_PORT}")

        for ticker in tickers:
            try:
                contract = Stock(ticker, "SMART", "USD")
                ib.qualifyContracts(contract)
                qualified.append(ticker)
            except Exception as e:
                logger.warning(f"Could not qualify {ticker}: {e}")
                continue

        logger.info(f"Qualified {len(qualified)}/{len(tickers)} contracts")
    except Exception as e:
        logger.error(f"IBKR connection failed: {e}")
        # Fallback: assume all tickers are valid (for paper trading scenarios)
        qualified = tickers
        logger.warning("Using unqualified ticker list as fallback")
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    config = {
        "tickers": qualified,
        "total_lines": len(qualified),
        "earnings_candidates": earnings_count,
        "sp500_filler": sp500_filler_count,
        "contract_type": "STK",
        "exchange": "SMART",
        "currency": "USD",
        "setup_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)

    # Save to DB
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with get_session() as session:
            for rank, ticker in enumerate(qualified, 1):
                entry = MonitoringList(
                    ticker=ticker,
                    rank=rank,
                    sec_score=0,
                    source="earnings" if rank <= earnings_count else "sp500_filler",
                    scan_date=scan_date,
                )
                session.add(entry)
    except Exception as e:
        logger.warning(f"DB save failed (non-critical): {e}")

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("ibkr_setup_agent", "success",
              f"Monitoring set: {len(qualified)} lines ({earnings_count} earnings + {sp500_filler_count} filler)",
              execution_time_ms=elapsed_ms)

    print(json.dumps({
        "status": "ok",
        "total_lines": len(qualified),
        "earnings_candidates": earnings_count,
        "sp500_filler": sp500_filler_count,
    }))


def fetch_premarket(tickers: list[str], output_path: str):
    """
    Agent-4: Fetch pre-market data for all monitored tickers.
    Collects: price, volume, volume ratio, ATR, sector ETF movement.
    """
    from ib_insync import IB, Stock, Index

    start_time = time.time()
    log_agent("premarket_agent", "started",
              f"Fetching pre-market data for {len(tickers)} tickers")

    stocks_data = []
    market_sentiment = "neutral"
    sp500_change = 0.0

    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID_PREMARKET)
        logger.info(f"Connected to IBKR for pre-market data")

        # 1. S&P 500 overnight change for market sentiment
        try:
            spy = Stock("SPY", "SMART", "USD")
            ib.qualifyContracts(spy)
            spy_bars = ib.reqHistoricalData(
                spy, endDateTime="", durationStr="2 D",
                barSizeSetting="1 day", whatToShow="TRADES", useRTH=True
            )
            if spy_bars and len(spy_bars) >= 2:
                prev_close = spy_bars[-2].close
                curr = spy_bars[-1].close
                sp500_change = (curr - prev_close) / prev_close
                if sp500_change > 0.003:
                    market_sentiment = "bullish"
                elif sp500_change < -0.005:
                    market_sentiment = "bearish"
            logger.info(f"S&P 500 change: {sp500_change:.4f} → {market_sentiment}")
        except Exception as e:
            logger.warning(f"Failed to get S&P 500 data: {e}")

        # 2. Sector ETF changes
        sector_changes = {}
        for sector_name, etf_ticker in SECTOR_ETFS.items():
            try:
                etf = Stock(etf_ticker, "SMART", "USD")
                ib.qualifyContracts(etf)
                etf_bars = ib.reqHistoricalData(
                    etf, endDateTime="", durationStr="2 D",
                    barSizeSetting="1 day", whatToShow="TRADES", useRTH=True
                )
                if etf_bars and len(etf_bars) >= 2:
                    change = (etf_bars[-1].close - etf_bars[-2].close) / etf_bars[-2].close
                    sector_changes[sector_name] = round(change, 4)
            except Exception:
                continue
            ib.sleep(0.2)

        # 3. Per-ticker data
        for ticker in tickers:
            try:
                contract = Stock(ticker, "SMART", "USD")
                ib.qualifyContracts(contract)

                # Request market data (including pre-market)
                md = ib.reqMktData(contract, "", False, False)
                ib.sleep(2)

                # Historical data for volume average and ATR
                bars = ib.reqHistoricalData(
                    contract, endDateTime="", durationStr="14 D",
                    barSizeSetting="1 hour", whatToShow="TRADES", useRTH=False
                )

                # Calculate metrics
                avg_volume = sum(b.volume for b in bars) / len(bars) if bars else 0
                current_volume = md.volume if md.volume and md.volume > 0 else 0
                volume_ratio = round(current_volume / avg_volume, 2) if avg_volume > 0 else 0

                # ATR (5-day)
                daily_bars = ib.reqHistoricalData(
                    contract, endDateTime="", durationStr="10 D",
                    barSizeSetting="1 day", whatToShow="TRADES", useRTH=True
                )
                atr = round(calculate_atr(daily_bars, period=5), 2)

                sector = get_sector(ticker)
                sector_etf_change = sector_changes.get(sector, 0.0)

                price = md.last or md.close or (bars[-1].close if bars else 0)

                stocks_data.append({
                    "ticker": ticker,
                    "premarket_price": round(price, 2) if price else None,
                    "premarket_volume": current_volume,
                    "avg_volume_14d": round(avg_volume, 0),
                    "volume_ratio": volume_ratio,
                    "atr_5d": atr,
                    "sector": sector,
                    "sector_etf_change": sector_etf_change,
                })

                # Cancel market data subscription
                ib.cancelMktData(contract)
                ib.sleep(0.3)

            except Exception as e:
                logger.warning(f"Failed to get data for {ticker}: {e}")
                stocks_data.append({
                    "ticker": ticker,
                    "premarket_price": None,
                    "premarket_volume": 0,
                    "avg_volume_14d": 0,
                    "volume_ratio": 0,
                    "atr_5d": 0,
                    "sector": get_sector(ticker),
                    "sector_etf_change": 0,
                    "error": str(e),
                })

    except Exception as e:
        logger.error(f"IBKR connection failed: {e}")
        log_agent("premarket_agent", "error", f"IBKR connection failed: {e}")
        # Return empty data structure
        for ticker in tickers:
            stocks_data.append({
                "ticker": ticker,
                "premarket_price": None,
                "premarket_volume": 0,
                "avg_volume_14d": 0,
                "volume_ratio": 0,
                "atr_5d": 0,
                "sector": get_sector(ticker),
                "sector_etf_change": 0,
                "error": "IBKR connection failed",
            })
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    output = {
        "market_sentiment": market_sentiment,
        "sp500_overnight_change": round(sp500_change, 4),
        "sector_changes": sector_changes,
        "stocks": stocks_data,
        "count": len(stocks_data),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Save to DB
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with get_session() as session:
            for stock in stocks_data:
                entry = PremarketData(
                    ticker=stock["ticker"],
                    premarket_price=stock.get("premarket_price"),
                    premarket_volume=stock.get("premarket_volume"),
                    avg_volume_14d=stock.get("avg_volume_14d"),
                    volume_ratio=stock.get("volume_ratio"),
                    atr_5d=stock.get("atr_5d"),
                    sector=stock.get("sector"),
                    sector_etf_change=stock.get("sector_etf_change"),
                    scan_date=scan_date,
                )
                session.add(entry)
    except Exception as e:
        logger.warning(f"DB save failed (non-critical): {e}")

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_agent("premarket_agent", "success",
              f"Fetched data for {len(stocks_data)} tickers, sentiment={market_sentiment}",
              execution_time_ms=elapsed_ms)

    print(json.dumps({
        "status": "ok",
        "count": len(stocks_data),
        "market_sentiment": market_sentiment,
        "sp500_change": round(sp500_change, 4),
    }))


if __name__ == "__main__":
    init_db()

    parser = argparse.ArgumentParser(description="IBKR monitoring setup & pre-market data")
    parser.add_argument("--mode", required=True, choices=["setup", "premarket"],
                        help="Operation mode: setup or premarket")
    parser.add_argument("--tickers", help="Comma-separated tickers (for setup mode)")
    parser.add_argument("--config", default=str(DATA_DIR / "ibkr_config.json"),
                        help="IBKR config JSON (for premarket mode)")
    parser.add_argument("--output", help="Output JSON path")
    args = parser.parse_args()

    if args.mode == "setup":
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
        output = args.output or str(DATA_DIR / "ibkr_config.json")
        setup_monitoring(tickers, output)
    elif args.mode == "premarket":
        with open(args.config) as f:
            config = json.load(f)
        tickers = config.get("tickers", [])
        output = args.output or str(DATA_DIR / "premarket_data.json")
        fetch_premarket(tickers, output)
