#!/usr/bin/env python3
"""
SEC RSS Monitor: Polls SEC EDGAR RSS feed for real-time 8-K and S-3 filings.
When a relevant filing is detected for monitored tickers,
sends a webhook to OpenClaw Gateway for immediate processing.

Designed to run as a long-lived process (systemd service).
"""

import json
import logging
import os
import sys
import time
import hashlib
from datetime import datetime, timezone

import requests
import xml.etree.ElementTree as ET

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from config import SEC_USER_AGENT, DATA_DIR, LOG_LEVEL

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("sec_rss_monitor")

HEADERS = {"User-Agent": SEC_USER_AGENT}

# OpenClaw webhook endpoint
OPENCLAW_WEBHOOK_URL = os.environ.get(
    "OPENCLAW_WEBHOOK_URL",
    "http://localhost:3000/webhook/sec-events"
)
OPENCLAW_WEBHOOK_SECRET = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "")

# Monitored form types
MONITORED_FORMS = ["8-K", "S-3", "4"]

# Polling interval in seconds (SEC asks for >= 10 seconds between requests)
POLL_INTERVAL = int(os.environ.get("SEC_POLL_INTERVAL", "900"))  # 15 min default

# File to track seen filing IDs
SEEN_FILE = DATA_DIR / "sec_rss_seen.json"


def load_monitored_tickers() -> set:
    """Load tickers from the current IBKR monitoring config."""
    config_path = DATA_DIR / "ibkr_config.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
        return set(config.get("tickers", []))
    except FileNotFoundError:
        logger.warning("No ibkr_config.json found, monitoring all tickers")
        return set()


def load_seen_ids() -> set:
    """Load previously seen filing IDs."""
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        return set(data.get("seen_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen_ids(seen: set):
    """Save seen filing IDs (keep last 5000 to prevent unbounded growth)."""
    recent = sorted(seen)[-5000:]
    with open(SEEN_FILE, "w") as f:
        json.dump({"seen_ids": recent, "updated_at": datetime.now(timezone.utc).isoformat()}, f)


def fetch_sec_rss(form_type: str) -> list[dict]:
    """Fetch SEC EDGAR RSS feed for a specific form type."""
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar"
           f"?action=getcompany&type={form_type}&dateb=&owner=include"
           f"&count=40&search_text=&action=getcompany&output=atom")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        entries = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            link = entry.find("atom:link", ns)
            summary = entry.find("atom:summary", ns)
            updated = entry.find("atom:updated", ns)

            filing_id = hashlib.md5(
                (title.text if title is not None else "").encode()
            ).hexdigest()

            entries.append({
                "id": filing_id,
                "title": title.text if title is not None else "",
                "link": link.get("href", "") if link is not None else "",
                "summary": summary.text if summary is not None else "",
                "updated": updated.text if updated is not None else "",
                "form_type": form_type,
            })

        return entries
    except Exception as e:
        logger.error(f"Failed to fetch SEC RSS for {form_type}: {e}")
        return []


def extract_ticker_from_title(title: str) -> str:
    """Try to extract ticker symbol from SEC filing title."""
    # SEC titles often contain CIK and company name, not tickers directly.
    # This is a simplified extraction — in production, map CIK → ticker.
    parts = title.split(" - ")
    if len(parts) >= 2:
        company = parts[0].strip()
        return company[:10]  # Rough approximation
    return ""


def send_webhook(filing: dict, ticker: str):
    """Send filing alert to OpenClaw Gateway webhook."""
    payload = {
        "ticker": ticker,
        "form_type": filing["form_type"],
        "title": filing["title"],
        "link": filing["link"],
        "summary": filing["summary"][:500],
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    headers = {
        "Content-Type": "application/json",
    }
    if OPENCLAW_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = OPENCLAW_WEBHOOK_SECRET

    try:
        resp = requests.post(OPENCLAW_WEBHOOK_URL, json=payload,
                             headers=headers, timeout=10)
        if resp.ok:
            logger.info(f"Webhook sent for {ticker} ({filing['form_type']})")
        else:
            logger.warning(f"Webhook failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Webhook send failed: {e}")


def poll_once():
    """Single poll iteration: fetch RSS, check for new filings, send webhooks."""
    monitored = load_monitored_tickers()
    seen = load_seen_ids()
    new_count = 0

    for form_type in MONITORED_FORMS:
        entries = fetch_sec_rss(form_type)
        logger.debug(f"Fetched {len(entries)} {form_type} entries")

        for entry in entries:
            if entry["id"] in seen:
                continue

            seen.add(entry["id"])
            new_count += 1

            # Check if any monitored ticker is mentioned
            title_upper = entry["title"].upper()
            summary_upper = entry.get("summary", "").upper()

            matched_ticker = None
            for ticker in monitored:
                if ticker in title_upper or ticker in summary_upper:
                    matched_ticker = ticker
                    break

            if matched_ticker:
                logger.info(f"NEW FILING: {form_type} for {matched_ticker} — "
                            f"{entry['title'][:100]}")
                send_webhook(entry, matched_ticker)
            else:
                logger.debug(f"New {form_type} filing (no monitored ticker match): "
                             f"{entry['title'][:80]}")

        # Be polite to SEC servers
        time.sleep(2)

    save_seen_ids(seen)
    return new_count


def run_continuous():
    """Run continuous polling loop."""
    logger.info(f"SEC RSS Monitor started. Poll interval: {POLL_INTERVAL}s")
    logger.info(f"Webhook endpoint: {OPENCLAW_WEBHOOK_URL}")

    while True:
        try:
            new = poll_once()
            if new > 0:
                logger.info(f"Processed {new} new filings")
        except Exception as e:
            logger.error(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEC RSS real-time monitor")
    parser.add_argument("--once", action="store_true",
                        help="Run single poll and exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL,
                        help="Poll interval in seconds")
    args = parser.parse_args()

    POLL_INTERVAL = args.interval

    if args.once:
        count = poll_once()
        print(json.dumps({"status": "ok", "new_filings": count}))
    else:
        run_continuous()
