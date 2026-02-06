"""Agent-4: Pre-Market Data — Collect pre-market prices, volumes, ATR, sentiment at 7:30 AM."""

from datetime import date

import structlog

from src.agents.base import BaseAgent
from src.db.models import PremarketData
from src.db.session import SessionLocal
from src.services import ibkr_client, yahoo_client

logger = structlog.get_logger()


class PremarketAgent(BaseAgent):
    name = "premarket_agent"

    def execute(self, input_data: dict) -> dict:
        tickers = input_data.get("tickers", [])

        # Step 1: Get market sentiment (S&P500 overnight change)
        sp500_change = yahoo_client.get_index_change("SPY")
        if sp500_change > 0.002:
            market_sentiment = "bullish"
        elif sp500_change < -0.002:
            market_sentiment = "bearish"
        else:
            market_sentiment = "neutral"

        # Step 2: Get pre-market data for each ticker
        stocks_data = []
        for ticker in tickers:
            stock_data = self._get_premarket_data(ticker, sp500_change, market_sentiment)
            if stock_data:
                stocks_data.append(stock_data)

        # Step 3: Save to DB
        self._save_to_db(stocks_data)

        return {
            "result": {
                "market_sentiment": market_sentiment,
                "sp500_change": sp500_change,
                "stocks": stocks_data,
            },
        }

    def _get_premarket_data(self, ticker: str, sp500_change: float, market_sentiment: str) -> dict | None:
        """Gather pre-market data for a single ticker."""
        try:
            # Get snapshot from IBKR
            snapshot = ibkr_client.get_snapshot(ticker)
            premarket_price = snapshot["last"] if snapshot else None
            premarket_volume = snapshot.get("volume", 0) if snapshot else 0

            # Get historical bars for ATR and average volume calculation
            bars = ibkr_client.get_historical_bars(ticker, duration="14 D", bar_size="1 day")

            avg_volume_14d = 0
            atr_5d = 0.0

            if bars:
                # Average volume over 14 days
                volumes = [b.volume for b in bars if b.volume > 0]
                avg_volume_14d = int(sum(volumes) / len(volumes)) if volumes else 0

                # ATR over last 5 days
                recent_bars = bars[-5:] if len(bars) >= 5 else bars
                true_ranges = [b.high - b.low for b in recent_bars]
                atr_5d = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

            volume_ratio = premarket_volume / avg_volume_14d if avg_volume_14d > 0 else 0.0

            # Sector data
            info = yahoo_client.get_stock_info(ticker)
            sector = info.get("sector", "")
            sector_change = yahoo_client.get_sector_etf_change(sector) if sector else 0.0

            return {
                "ticker": ticker,
                "premarket_price": premarket_price,
                "premarket_volume": premarket_volume,
                "avg_volume_14d": avg_volume_14d,
                "volume_ratio": round(volume_ratio, 4),
                "atr_5d": round(atr_5d, 4),
                "sector": sector,
                "sector_change": round(sector_change, 6),
                "market_sentiment": market_sentiment,
                "sp500_change": round(sp500_change, 6),
            }
        except Exception as e:
            logger.warning("premarket_data_error", ticker=ticker, error=str(e))
            return None

    def _save_to_db(self, stocks: list[dict]):
        """Save pre-market data to database."""
        session = SessionLocal()
        try:
            for s in stocks:
                entry = PremarketData(
                    ticker=s["ticker"],
                    run_date=date.today(),
                    premarket_price=s.get("premarket_price"),
                    premarket_volume=s.get("premarket_volume"),
                    avg_volume_14d=s.get("avg_volume_14d"),
                    volume_ratio=s.get("volume_ratio"),
                    atr_5d=s.get("atr_5d"),
                    sector=s.get("sector"),
                    sector_change=s.get("sector_change"),
                    market_sentiment=s.get("market_sentiment"),
                    sp500_change=s.get("sp500_change"),
                )
                session.add(entry)
            session.commit()
            logger.info("premarket_data_saved", count=len(stocks))
        except Exception as e:
            session.rollback()
            logger.error("premarket_save_error", error=str(e))
        finally:
            session.close()
