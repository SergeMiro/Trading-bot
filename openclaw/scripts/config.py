"""
Centralized configuration for all trading bot scripts.
Loads from environment variables with sensible defaults.
"""

import os
from pathlib import Path

# === Paths ===
BASE_DIR = Path(os.environ.get("TRADING_BOT_DIR", Path(__file__).resolve().parent.parent))
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = BASE_DIR / "scripts"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# === Database ===
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://trading_bot:trading_bot_pass@localhost:5432/trading_bot"
)

# === SEC EDGAR ===
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "trading-bot contact@youremail.com")
SEC_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_FULL_TEXT_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_FILINGS_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_RSS_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type={form_type}&dateb=&owner=include&count=40&search_text=&action=getcompany"

# === IBKR ===
IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_PORT", "7497"))  # 7497=paper, 7496=live
IBKR_CLIENT_ID_SETUP = int(os.environ.get("IBKR_CLIENT_ID_SETUP", "1"))
IBKR_CLIENT_ID_PREMARKET = int(os.environ.get("IBKR_CLIENT_ID_PREMARKET", "2"))
IBKR_CLIENT_ID_TRADE = int(os.environ.get("IBKR_CLIENT_ID_TRADE", "3"))
IBKR_CLIENT_ID_MONITOR = int(os.environ.get("IBKR_CLIENT_ID_MONITOR", "4"))

# === Trading Parameters ===
TARGET_GAIN = float(os.environ.get("TARGET_GAIN", "0.09"))        # +9%
STOP_LOSS = float(os.environ.get("STOP_LOSS", "0.05"))            # -5%
MAX_HOLD_DAYS = int(os.environ.get("MAX_HOLD_DAYS", "7"))
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE", "0.02"))  # 2% of portfolio
MAX_CONCURRENT_POSITIONS = int(os.environ.get("MAX_CONCURRENT_POSITIONS", "3"))
MAX_MONITORING_LINES = int(os.environ.get("MAX_MONITORING_LINES", "100"))

# === Scoring Thresholds ===
SCORE_BUY = int(os.environ.get("SCORE_BUY", "70"))
SCORE_HOLD = int(os.environ.get("SCORE_HOLD", "50"))

# === LLM (Anthropic Claude) ===
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# === Telegram ===
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID", "")

# === Logging ===
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
