"""
WEB SCRAPER — Simple URL Content Fetcher
-----------------------------------------
Fetches and extracts text content from web pages.
Uses requests and BeautifulSoup for parsing.
"""

import requests
from bs4 import BeautifulSoup


def scrape_webpage(url: str, max_length: int = 5000):
    """
    Fetch and extract text content from a web page.

    Args:
        url: The URL to scrape
        max_length: Maximum length of text to return (default 5000 chars)

    Returns:
        dict: {status, title, content, url} or {status, error}
    """
    if not url:
        return {"status": "error", "error": "URL is required"}

    # Add protocol if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        # Fetch the page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.content, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Get title
        title = soup.title.string if soup.title else "No title"

        # Get text content
        text = soup.get_text(separator=" ", strip=True)

        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = " ".join(chunk for chunk in chunks if chunk)

        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "... [TRUNCATED]"

        return {
            "status": "success",
            "url": url,
            "title": title,
            "content": text,
            "length": len(text),
        }

    except requests.exceptions.Timeout:
        return {"status": "error", "error": "Request timed out"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"status": "error", "error": f"Scraping failed: {str(e)}"}


# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================


def run_web_scraper(url: str, max_length: int = 5000):
    """
    Smith tool interface for web scraping.
    """
    return scrape_webpage(url, int(max_length))


# --- ALIASES (Anti-Hallucination Guard) ---
web_scraper = run_web_scraper
scrape = run_web_scraper
fetch_page = run_web_scraper
# ------------------------------------------


METADATA = {
    "name": "web_scraper",
    "description": "Fetch and extract text content from any web page URL. Returns the page title and main text content.",
    "function": "run_web_scraper",
    "dangerous": False,
    "domain": "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to scrape",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum length of text to return (default 5000)",
                "default": 5000,
            },
        },
        "required": ["url"],
    },
}
