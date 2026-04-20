"""
NEWS FETCHER v5 — DuckDuckGo News + Body Fetcher
==================================================
Pipeline:
    RAW QUERY
        │
        ▼
    [KeywordOptimizer]  ← nvidia/nemotron-3-nano-30b-a3b (OpenRouter, free)
        │  Converts natural language → precise news search keywords
        ▼
    [DuckDuckGo News]   ← ddgs pip (free, no API key, no quota)
        │  Primary news source — returns title, snippet, url, date, source
        │  Falls back to upstream google_search results if DDG fails
        ▼
    [SimpleBodyFetcher] ← requests + BeautifulSoup
        │  Extracts full article text from <article>, <p> tags
        │  Skips blocked/paywalled domains
        │  Empty body? → uses DDG snippet (never errors)
        ▼
    STRUCTURED OUTPUT (always success if any articles found)

No API key needed. No quotas. Completely free.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Any, Union

import requests as http_requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "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",
)
KEYWORD_MODEL     = "nvidia/nemotron-3-nano-30b-a3b:free"

TOP_N_DEFAULT     = 5
BODY_MAX_CHARS    = 10_000     # hard-truncate anything longer
FETCH_TIMEOUT     = 8          # seconds per body fetch

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Domains that block scrapers or are paywalled — skip body fetch
BLOCKED_DOMAINS = {
    "livemint.com", "economictimes.indiatimes.com", "timesofindia.indiatimes.com",
    "wsj.com", "ft.com", "bloomberg.com", "nytimes.com", "washingtonpost.com",
    "telegraph.co.uk", "thetimes.co.uk", "seekingalpha.com",
    "barrons.com", "theathletic.com", "businessinsider.com",
}


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — KEYWORD OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

KEYWORD_SYSTEM_PROMPT = """You are a News Search Query Engineer. Your ONLY job is to convert a
user's natural-language request into 1 precise news search keyword string.

Rules:
- Output ONLY a single clean keyword string. No JSON, no prose, no quotes, no markdown.
- Use journalistic terminology: proper nouns, event names, acronyms.
- Prefer specific over generic ("Russia Ukraine ceasefire 2025" > "Russia Ukraine news").
- Max 8 words.
- Do NOT include site filters, outlet names, or URLs.
- Do NOT include words like "fetch", "find", "get", "search", "I need".
- Include the current year if the topic is time-sensitive.

Examples:
Input:  "fetch me news about russia ukraine war nato"
Output: Russia Ukraine war NATO ceasefire 2025

Input:  "what is happening with india elections"
Output: India elections 2025 results

Input:  "tell me about apple stock"
Output: Apple AAPL earnings stock market
"""


def optimize_keywords(raw_query: str) -> str:
    """
    Rewrite raw user query into a clean news search keyword string.
    Returns raw query as fallback on any failure.
    """
    if not OPENROUTER_API_KEY or not raw_query.strip():
        return raw_query

    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        response = client.chat.completions.create(
            model=KEYWORD_MODEL,
            messages=[
                {"role": "system", "content": KEYWORD_SYSTEM_PROMPT},
                {"role": "user",   "content": f"Convert to news search keywords:\n{raw_query}"}
            ],
            temperature=0.2,
            max_tokens=60,
            top_p=0.9,
        )
        optimized = response.choices[0].message.content.strip()
        optimized = re.sub(r'^["\'\`]|["\'\`]$', "", optimized).strip()

        if not optimized or len(optimized) > 200:
            raise ValueError("Bad optimizer output")

        logger.info(f"[KeywordOptimizer] '{raw_query[:60]}' → '{optimized}'")
        return optimized

    except Exception as e:
        logger.warning(f"[KeywordOptimizer] Failed: {e} — using raw query.")
        return raw_query


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2A — DUCKDUCKGO NEWS (primary)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ddg_news(query: str, count: int) -> list[dict]:
    """Fetch news articles via DuckDuckGo. No API key needed."""
    try:
        from ddgs import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.news(query, max_results=count * 3))

        if not raw_results:
            return []

        articles = []
        for item in raw_results:
            url = item.get("url", "")
            if not url:
                continue
            articles.append({
                "title":     item.get("title", ""),
                "snippet":   item.get("body", ""),
                "url":       url,
                "published": item.get("date", ""),
                "source":    item.get("source", ""),
                "body":      "",
            })

        logger.info(f"[DDG News] Got {len(articles)} articles for: '{query[:60]}'")
        return articles

    except Exception as e:
        logger.warning(f"[DDG News] Failed: {type(e).__name__}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2B — FALLBACK: unwrap upstream google_search results
# ─────────────────────────────────────────────────────────────────────────────

def unwrap_search_result(raw: Any) -> list:
    """Unwrap {{STEPS.N}} google_search output into a flat list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("results", "articles", "items", "data", "result"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
        if any(k in raw for k in ("title", "url", "link")):
            return [raw]
    return []


def normalize_google_article(article: Union[dict, str]) -> dict | None:
    """Normalize a google_search result dict into standard article format."""
    if isinstance(article, str):
        if article.startswith("http"):
            return {"title": "", "snippet": "", "url": article,
                    "published": "", "source": "", "body": ""}
        return None
    if not isinstance(article, dict):
        return None

    title   = article.get("title") or article.get("name") or ""
    snippet = (article.get("snippet") or article.get("description") or
               article.get("content") or "")
    url     = article.get("url") or article.get("link") or ""
    published = article.get("published") or article.get("date") or ""
    source  = article.get("source_name") or article.get("source") or ""

    if not (title or snippet or url):
        return None

    return {
        "title":     str(title).strip(),
        "snippet":   str(snippet).strip(),
        "url":       str(url).strip(),
        "published": str(published).strip(),
        "source":    str(source).strip(),
        "body":      "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — SIMPLE BODY FETCHER (requests + BeautifulSoup)
# ─────────────────────────────────────────────────────────────────────────────

def _is_blocked(url: str) -> bool:
    """Check if URL belongs to a known paywalled/blocked domain."""
    for domain in BLOCKED_DOMAINS:
        if domain in url:
            return True
    return False


def fetch_body_simple(url: str) -> str:
    """
    Fetch article body using requests + BeautifulSoup.
    Extracts text from <article>, then falls back to <p> tags.
    Returns empty string on any failure — never raises.
    """
    if not url or not url.startswith("http"):
        return ""

    if _is_blocked(url):
        logger.debug(f"[BodyFetch] Blocked domain — skipping: {url}")
        return ""

    try:
        resp = http_requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove non-content tags
        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "form", "iframe", "noscript"]):
            tag.decompose()

        # Strategy 1: <article> tag
        article_tag = soup.find("article")
        if article_tag:
            paragraphs = article_tag.find_all("p")
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if len(text) > 200:
                logger.info(f"[BodyFetch] <article> → {len(text):,} chars: {url[:80]}")
                return text[:BODY_MAX_CHARS]

        # Strategy 2: semantic containers
        for selector in ["main", "[role='main']", ".article-body", ".story-body",
                         ".post-content", ".entry-content", "#article-body"]:
            container = soup.select_one(selector)
            if container:
                paragraphs = container.find_all("p")
                text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
                if len(text) > 200:
                    logger.info(f"[BodyFetch] {selector} → {len(text):,} chars: {url[:80]}")
                    return text[:BODY_MAX_CHARS]

        # Strategy 3: all <p> tags (last resort)
        paragraphs = soup.find_all("p")
        text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40)
        if len(text) > 200:
            logger.info(f"[BodyFetch] <p> fallback → {len(text):,} chars: {url[:80]}")
            return text[:BODY_MAX_CHARS]

        return ""

    except Exception as e:
        logger.debug(f"[BodyFetch] Failed: {url}: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_news_fetcher(
    articles:   Any   = None,
    raw_query:  str   = "",
    top_n:      int   = TOP_N_DEFAULT,
    fetch_body: bool  = True,
) -> dict:
    """
    News pipeline: keyword optimization → DDG news → body fetch → output.

    NEVER returns "error" if any articles are found — uses snippets as fallback.
    """

    # ── Stage 1: Keyword Optimization ────────────────────────────────────────
    optimized_query = optimize_keywords(raw_query) if raw_query.strip() else raw_query
    logger.info(f"[Pipeline] Query: '{raw_query[:80]}' → '{optimized_query}'")

    # ── Stage 2: Get candidate articles ──────────────────────────────────────
    data_source = "duckduckgo"
    candidates  = _fetch_ddg_news(optimized_query, top_n)

    if not candidates:
        logger.info("[Pipeline] Falling back to upstream google_search results.")
        data_source = "google_search_fallback"
        raw_list    = unwrap_search_result(articles) if articles else []
        candidates  = [n for item in raw_list if (n := normalize_google_article(item))]

    if not candidates:
        return {
            "status":           "error",
            "error":            (
                "No articles found via DuckDuckGo News. "
                "Ensure google_search ran and passed output via {{STEPS.N}} as fallback."
            ),
            "optimized_query":  optimized_query,
            "count":            0,
            "total_available":  0,
            "articles":         [],
        }

    # Deduplicate by URL
    seen, deduped = set(), []
    for art in candidates:
        key = art["url"] or art["title"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(art)

    total_available = len(deduped)
    pool = deduped[:top_n * 3]

    # ── Stage 3: Body Fetch with graceful degradation ────────────────────────
    results = []

    if fetch_body:
        logger.info(f"[Pipeline] Fetching bodies — need {top_n}, pool {len(pool)}")

        for i, article in enumerate(pool):
            if len(results) >= top_n:
                break

            url = article.get("url", "")
            body = fetch_body_simple(url) if url else ""

            if body:
                article["body"]        = body
                article["body_status"] = "full" if len(body) < BODY_MAX_CHARS else "truncated"
            elif article.get("snippet"):
                article["body"]        = article["snippet"]
                article["body_status"] = "snippet_only"
            else:
                article["body"]        = article.get("title", "")
                article["body_status"] = "title_only"

            results.append(article)
    else:
        for art in pool[:top_n]:
            art["body"]        = art.get("snippet", "")
            art["body_status"] = "snippet_only"
        results = pool[:top_n]

    # NEVER error if we have articles
    return {
        "status":           "success",
        "source":           data_source,
        "optimized_query":  optimized_query,
        "count":            len(results),
        "total_available":  total_available,
        "articles":         results,
    }


# Alias for Smith agent runtime
news_fetcher = run_news_fetcher


# ─────────────────────────────────────────────────────────────────────────────
# SMITH AGENT METADATA
# ─────────────────────────────────────────────────────────────────────────────

METADATA = {
    "name":        "news_fetcher",
    "description": (
        "Fetches top N news articles with body text. "
        "Uses DuckDuckGo News as the primary source — no API key needed. "
        "Falls back to upstream google_search results if DDG fails. "
        "Bodies are fetched via requests + BeautifulSoup (no external APIs). "
        "If body fetch fails, articles are returned with snippet text instead "
        "(never errors if articles exist). "
        "Pass the original user request as raw_query for keyword optimization."
    ),
    "function":    "run_news_fetcher",
    "dangerous":   False,
    "domain":      "data_retrieval",
    "output_type": "structured",
    "parameters": {
        "type": "object",
        "properties": {
            "articles": {
                "type":        "array",
                "description": (
                    "Upstream google_search output ({{STEPS.N}}). "
                    "Only used as fallback if DuckDuckGo News returns no results."
                ),
                "items": {"type": "object"}
            },
            "raw_query": {
                "type":        "string",
                "default":     "",
                "description": "Original user query. Fed into keyword optimizer sub-model."
            },
            "top_n": {
                "type":        "integer",
                "default":     5,
                "minimum":     1,
                "maximum":     20,
                "description": "Number of articles to return."
            },
            "fetch_body": {
                "type":        "boolean",
                "default":     True,
                "description": "Fetch full body text. Set False for snippet-only mode."
            }
        },
        "required": []
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# QUICK LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    result = run_news_fetcher(
        raw_query  = "setting up a business in Dubai from India",
        top_n      = 3,
        fetch_body = True,
    )

    print(f"\n{'═'*65}")
    print(f"  Status:          {result['status']}")
    print(f"  Source:          {result.get('source')}")
    print(f"  Query used:      {result.get('optimized_query')}")
    print(f"  Articles:        {result['count']} / {result['total_available']} available")
    print(f"{'═'*65}\n")

    for i, art in enumerate(result.get("articles", []), 1):
        print(f"[{i}] {art['title'] or '(no title)'}")
        print(f"     Source:      {art['source'] or 'unknown'}")
        print(f"     Published:   {art['published'] or 'unknown'}")
        print(f"     URL:         {art['url']}")
        print(f"     Body status: {art.get('body_status', 'unknown')}")
        body_preview = art['body'][:300] if art['body'] else None
        print(f"     Body:        {body_preview}..." if body_preview else "     Body:        [empty]")
        print()