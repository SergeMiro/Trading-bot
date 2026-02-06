import time
from datetime import datetime, timedelta

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings

logger = structlog.get_logger()

SEC_BASE_URL = "https://data.sec.gov"
SEC_SUBMISSIONS_URL = f"{SEC_BASE_URL}/submissions"
SEC_EFTS_URL = "https://efts.sec.gov/LATEST/search-index?q="


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def get_company_filings(cik: str) -> dict:
    """Fetch company filings from SEC EDGAR by CIK."""
    cik_padded = cik.zfill(10)
    url = f"{SEC_SUBMISSIONS_URL}/CIK{cik_padded}.json"
    headers = {"User-Agent": settings.sec_user_agent}

    with httpx.Client(timeout=15) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        time.sleep(0.11)  # SEC rate limit: 10 req/sec
        return response.json()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def search_filings(query: str, date_from: str | None = None, forms: str | None = None) -> dict:
    """Full-text search SEC EDGAR filings."""
    params = {"q": query, "dateRange": "custom"}
    if date_from:
        params["startdt"] = date_from
        params["enddt"] = datetime.now().strftime("%Y-%m-%d")
    if forms:
        params["forms"] = forms

    url = "https://efts.sec.gov/LATEST/search-index"
    headers = {"User-Agent": settings.sec_user_agent}

    with httpx.Client(timeout=15) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        time.sleep(0.11)
        return response.json()


def get_recent_filings(cik: str, days: int = 14) -> list[dict]:
    """Get recent filings for a company within the last N days."""
    data = get_company_filings(cik)
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    cutoff = datetime.now() - timedelta(days=days)
    results = []

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocDescription", [])
    accessions = recent.get("accessionNumber", [])

    for i in range(len(forms)):
        filing_date = datetime.strptime(dates[i], "%Y-%m-%d")
        if filing_date >= cutoff:
            results.append({
                "form_type": forms[i],
                "filing_date": dates[i],
                "description": descriptions[i] if i < len(descriptions) else "",
                "accession_number": accessions[i] if i < len(accessions) else "",
            })

    logger.info("sec_recent_filings", cik=cik, count=len(results), days=days)
    return results


def get_filing_document(accession_number: str, cik: str) -> str:
    """Fetch the full text of a filing document."""
    cik_padded = cik.zfill(10)
    accession_clean = accession_number.replace("-", "")
    url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik_padded}/{accession_clean}/{accession_number}.txt"
    headers = {"User-Agent": settings.sec_user_agent}

    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        time.sleep(0.11)
        return response.text[:10000]  # First 10K chars for LLM analysis
