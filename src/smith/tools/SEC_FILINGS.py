"""
SEC Filings Fetcher Tool
Queries SEC EDGAR for the latest 10-K and 10-Q filings for a ticker.
Requires no API key, completely free. Uses standard REST interface.
"""

import json
import urllib.request
import urllib.parse
from typing import Dict, Any

# SEC requires a user-agent declaring who we are
USER_AGENT = "SmithAgent (research@smithagent.local)"

def get_cik_for_ticker(ticker: str) -> str:
    """Converts a ticker symbol to a SEC CIK number."""
    # SEC provides a mappings file mapping tickers to CIKs
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        ticker_upper = ticker.upper()
        
        # Format is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        for _, company in data.items():
            if company.get("ticker") == ticker_upper:
                # SEC CIKs are 10 digits padded with zeros
                return str(company.get("cik_str")).zfill(10)
    except Exception:
        pass
        
    return None

def fetch_recent_filings(cik: str, form_type: str = "10-K", limit: int = 3) -> Dict[str, Any]:
    """Fetches submission history for a CIK."""
    # submissions API provides recent filings
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        company_name = data.get("name")
        recent_filings = data.get("filings", {}).get("recent", {})
        
        if not recent_filings:
            return {"status": "error", "error": "No recent filings found for CIK"}
            
        results = []
        forms = recent_filings.get("form", [])
        accessions = recent_filings.get("accessionNumber", [])
        dates = recent_filings.get("filingDate", [])
        primary_docs = recent_filings.get("primaryDocument", [])
        
        for i, form in enumerate(forms):
            if limit > 0 and len(results) >= limit:
                break
                
            if form == form_type:
                accession = accessions[i]
                accession_no_dashes = accession.replace("-", "")
                primary_doc = primary_docs[i]
                
                # Construct URL to the actual document
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_no_dashes}/{primary_doc}"
                
                results.append({
                    "form_type": form,
                    "filing_date": dates[i],
                    "accession_number": accession,
                    "document_url": doc_url
                })
                
        return {
            "status": "success",
            "company_name": company_name,
            "cik": cik,
            "filings": results
        }
        
    except Exception as e:
        return {"status": "error", "error": f"SEC API Error: {str(e)}"}

def run_sec_filings_fetcher(ticker: str, form_type: str = "10-K", limit: int = 3) -> Dict[str, Any]:
    """Main router for SEC filings fetcher."""
    if not ticker:
        return {"status": "error", "error": "Ticker symbol is required."}
        
    form_type = form_type.upper()
    if form_type not in ["10-K", "10-Q", "8-K"]:
        form_type = "10-K" # default
        
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"status": "error", "error": f"Could not find SEC CIK for ticker {ticker}"}
            
        return fetch_recent_filings(cik, form_type, limit)
    except Exception as e:
        return {"status": "error", "error": str(e)}

METADATA = {
    "name": "sec_filings",
    "description": "Fetch the latest SEC EDGAR filings (10-K, 10-Q, 8-K) and their URLs for a given stock ticker. Completely free.",
    "function": "run_sec_filings_fetcher",
    "dangerous": False,
    "domain": "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Stock ticker symbol (e.g. AAPL, MSFT)"
            },
            "form_type": {
                "type": "string",
                "enum": ["10-K", "10-Q", "8-K"],
                "description": "Type of filing to retrieve",
                "default": "10-K"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of filings to return",
                "default": 3
            }
        },
        "required": ["ticker"]
    }
}
