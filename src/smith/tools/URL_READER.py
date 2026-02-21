"""
URL READER v1 — Deep Page Content Extractor
=============================================
Pipeline:
    URL
        │
        ▼
    [requests + BeautifulSoup]
        │  Smart extraction: <article> → <main> → <p> fallback
        │  Removes nav, footer, scripts, ads
        │  Returns structured sections with headings
        ▼
    STRUCTURED RESULT (title, sections, full text)

Difference from web_scraper:
- Extracts structured sections (headings + text) not just flat text
- Better content detection with article/main/role selectors
- Higher default max_length (10k vs 5k)
- Blocked domain awareness for paywalled sites

No API key needed.
"""

import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

MAX_LENGTH_DEFAULT = 10_000
FETCH_TIMEOUT      = 10

BLOCKED_DOMAINS = {
    "wsj.com", "ft.com", "bloomberg.com", "nytimes.com",
    "washingtonpost.com", "telegraph.co.uk", "theathletic.com",
    "seekingalpha.com", "barrons.com",
}


# ─────────────────────────────────────────────────────────────────────────────
# CORE
# ─────────────────────────────────────────────────────────────────────────────

def _is_blocked(url: str) -> bool:
    for domain in BLOCKED_DOMAINS:
        if domain in url:
            return True
    return False


def _extract_sections(soup) -> list[dict]:
    """Extract content organized by headings."""
    sections = []
    current_heading = "Introduction"
    current_text = []

    content_root = (
        soup.find("article") or
        soup.find("main") or
        soup.select_one("[role='main']") or
        soup.find("body")
    )

    if not content_root:
        return []

    for element in content_root.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        tag = element.name

        if tag in ("h1", "h2", "h3", "h4"):
            # Save previous section
            if current_text:
                text = "\n\n".join(current_text)
                if len(text) > 40:
                    sections.append({"heading": current_heading, "text": text})
            current_heading = element.get_text(strip=True) or "Section"
            current_text = []
        elif tag in ("p", "li"):
            text = element.get_text(strip=True)
            if len(text) > 20:
                current_text.append(text)

    # Save last section
    if current_text:
        text = "\n\n".join(current_text)
        if len(text) > 40:
            sections.append({"heading": current_heading, "text": text})

    return sections


def run_url_reader(url: str, max_length: int = MAX_LENGTH_DEFAULT) -> dict:
    """
    Fetch and extract structured content from any URL.

    Returns title, organized sections (heading + text), and full text.
    Smart content detection with fallback strategies.
    """
    if not url or not url.strip():
        return {"status": "error", "error": "URL is required."}

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if _is_blocked(url):
        return {
            "status": "error",
            "error":  f"Domain is paywalled/blocked. Cannot extract content from: {url}",
            "url":    url,
        }

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return {
                "status": "error",
                "error":  f"Not an HTML page (Content-Type: {content_type})",
                "url":    url,
            }

        soup = BeautifulSoup(resp.text, "html.parser")

        # Clean non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        # Title
        title = soup.title.string.strip() if soup.title and soup.title.string else "No title"

        # Structured sections
        sections = _extract_sections(soup)

        # Full text (flat) as fallback
        full_text = ""
        if sections:
            full_text = "\n\n".join(
                f"## {s['heading']}\n{s['text']}" for s in sections
            )
        else:
            # Fallback: get all <p> text
            paragraphs = soup.find_all("p")
            full_text = "\n\n".join(
                p.get_text(strip=True)
                for p in paragraphs
                if len(p.get_text(strip=True)) > 30
            )

        # Truncate
        max_length = max(1000, min(int(max_length), 50_000))
        if len(full_text) > max_length:
            full_text = full_text[:max_length] + "\n\n... [TRUNCATED]"

        if not full_text or len(full_text) < 50:
            return {
                "status": "error",
                "error":  "Page loaded but no readable content could be extracted.",
                "url":    url,
                "title":  title,
            }

        result = {
            "status":        "success",
            "url":           url,
            "title":         title,
            "content":       full_text,
            "content_length": len(full_text),
            "sections":      len(sections),
        }

        logger.info(f"[URLReader] '{title[:50]}' — {len(full_text):,} chars, "
                     f"{len(sections)} sections")
        return result

    except requests.exceptions.Timeout:
        return {"status": "error", "error": f"Timeout fetching: {url}", "url": url}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": f"Request failed: {str(e)}", "url": url}
    except Exception as e:
        logger.warning(f"[URLReader] Failed: {type(e).__name__}: {e}")
        return {"status": "error", "error": f"Failed: {str(e)}", "url": url}


# ─────────────────────────────────────────────────────────────────────────────
# ALIASES
# ─────────────────────────────────────────────────────────────────────────────

url_reader  = run_url_reader
read_url    = run_url_reader
fetch_url   = run_url_reader


# ─────────────────────────────────────────────────────────────────────────────
# SMITH AGENT METADATA
# ─────────────────────────────────────────────────────────────────────────────

METADATA = {
    "name":        "url_reader",
    "description": (
        "Fetch and extract structured text from any web page URL. "
        "Returns the page title, content organized by headings (sections), "
        "and full text. Use after google_search to deep-read a specific result. "
        "Handles article extraction with smart fallbacks. "
        "Skips paywalled sites automatically. No API key needed."
    ),
    "function":    "run_url_reader",
    "dangerous":   False,
    "domain":      "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type":        "string",
                "description": "The URL to read. Must be a valid HTTP/HTTPS URL.",
            },
            "max_length": {
                "type":        "integer",
                "description": "Max content length in chars (default 10000, max 50000).",
                "default":     10000,
            },
        },
        "required": ["url"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# QUICK LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    result = run_url_reader("https://en.wikipedia.org/wiki/Jebel_Ali_Free_Zone")
    print(f"\n{'═'*60}")
    print(f"  Title:    {result.get('title', 'N/A')}")
    print(f"  Length:   {result.get('content_length', 0):,} chars")
    print(f"  Sections: {result.get('sections', 0)}")
    print(f"{'═'*60}")
    print(f"\n{result.get('content', '')[:500]}...")
