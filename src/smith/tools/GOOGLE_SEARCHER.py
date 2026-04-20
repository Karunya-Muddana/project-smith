"""
WEB SEARCH v2 — DuckDuckGo + SearXNG Fallback + NVIDIA Query Optimizer
=======================================================================
Pipeline:
    RAW QUERY
        │
        ▼
    [QueryOptimizer]  ← NVIDIA Inference API
                         Endpoint: https://integrate.api.nvidia.com/v1/chat/completions
                         Model default: meta/llama-4-maverick-17b-128e-instruct
                         Requires NVIDIA_LLM_API_KEY
        │  Rewrites raw/vague query into precise search keywords
        ▼
    [DuckDuckGo]      ← via duckduckgo-search (pip, no API key)
        │  Primary search engine — reliable, fast, zero config
        │  Falls back to SearXNG if SEARXNG_URL set in .env
        ▼
    STRUCTURED RESULTS

Note: Search backends require no API key, but the NVIDIA optimizer path does.
"""

import os
import re
import logging
import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

NVIDIA_LLM_API_KEY = os.getenv("NVIDIA_LLM_API_KEY", "")
NVIDIA_INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OPTIMIZER_MODEL  = os.getenv(
    "SMITH_LLM_MODEL",
    "meta/llama-4-maverick-17b-128e-instruct",
)
CURRENT_YEAR = datetime.date.today().year

MAX_RESPONSE_CHARS = 24_000
PER_RESULT_CONTENT_CHARS = 6_000

# Optional: self-hosted SearXNG instance for JSON API (set in .env)
SEARXNG_URL      = os.getenv("SEARXNG_URL", "")


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — QUERY OPTIMIZER (LLM sub-model)
# ─────────────────────────────────────────────────────────────────────────────

OPTIMIZER_SYSTEM_PROMPT = f"""You are a Search Query Specialist. Your ONLY job is to
rewrite a user's raw search request into a single, highly optimised search string.

Rules:
- Output ONLY the final search string. No JSON, no prose, no explanations, no quotes.
- Make it specific: include proper nouns, dates, event names, acronyms where relevant.
- Keep it as a clean keyword string — no site: filters or special operators.
- Include the current year ({CURRENT_YEAR}) only if the topic is time-sensitive.
- Max 15 words total in the output string.
- Do NOT include words like "fetch", "find me", "get", "search for", "I need" — output keywords only.

Examples:
Input:  "fetch me news about russia ukraine war nato"
Output: Russia Ukraine war NATO ceasefire {CURRENT_YEAR}

Input:  "what is the stock price of apple"
Output: Apple AAPL stock price today {CURRENT_YEAR}

Input:  "latest news on india elections"
Output: India general elections {CURRENT_YEAR} results

Input:  "how to setup a business in dubai from india"
Output: Dubai business setup guide Indian entrepreneurs legal requirements
"""


def optimize_query(raw_query: str) -> str:
    """
    Rewrite the raw query into a precise search string using a fast LLM.
    Returns the original query as fallback on any failure.
    """
    if not NVIDIA_LLM_API_KEY:
        logger.debug("[QueryOptimizer] No NVIDIA_LLM_API_KEY — using raw query.")
        return raw_query

    if not raw_query or not raw_query.strip():
        return raw_query

    try:
        import requests as _req
        resp = _req.post(
            NVIDIA_INVOKE_URL,
            headers={
                "Authorization": f"Bearer {NVIDIA_LLM_API_KEY}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "model": OPTIMIZER_MODEL,
                "messages": [
                    {"role": "system", "content": OPTIMIZER_SYSTEM_PROMPT},
                    {"role": "user",   "content": f"Rewrite this as a search query:\n{raw_query}"}
                ],
                "temperature": 0.2,
                "max_tokens": 80,
                "top_p": 0.9,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "stream": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        optimized = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        optimized = re.sub(r'^["\'\`]|["\'\`]$', "", optimized).strip()

        if not optimized or len(optimized) > 300:
            raise ValueError(f"Unexpected optimizer output: '{optimized[:100]}'")

        logger.info(f"[QueryOptimizer] '{raw_query}' → '{optimized}'")
        return optimized

    except Exception as e:
        logger.warning(f"[QueryOptimizer] Failed ({type(e).__name__}: {e}) — using raw query.")
        return raw_query


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2A — DUCKDUCKGO SEARCH (primary)
# ─────────────────────────────────────────────────────────────────────────────

def _search_duckduckgo(query: str, num_results: int) -> list[dict] | None:
    """Search via DuckDuckGo. No API key needed."""
    try:
        from ddgs import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.text(query, max_results=num_results))

        if not raw_results:
            return None

        results = []
        for item in raw_results:
            results.append({
                "title":   item.get("title", ""),
                "link":    item.get("href", ""),
                "content": item.get("body", ""),
                "source":  "",
                "date":    "",
            })

        logger.info(f"[DuckDuckGo] {len(results)} results for: '{query[:60]}'")
        return results

    except Exception as e:
        logger.warning(f"[DuckDuckGo] Failed: {type(e).__name__}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2B — SEARXNG SEARCH (fallback, if self-hosted instance configured)
# ─────────────────────────────────────────────────────────────────────────────

def _search_searxng(query: str, num_results: int) -> list[dict] | None:
    """Search via self-hosted SearXNG instance. Only used if SEARXNG_URL is set."""
    if not SEARXNG_URL:
        return None

    try:
        import requests

        resp = requests.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={
                "q":          query,
                "format":     "json",
                "categories": "general",
                "language":   "en",
                "pageno":     1,
            },
            headers={"User-Agent": "Smith/3.0", "Accept": "application/json"},
            timeout=10,
        )

        if resp.status_code != 200:
            logger.debug(f"[SearXNG] HTTP {resp.status_code}")
            return None

        data = resp.json()
        raw_results = data.get("results", [])
        if not raw_results:
            return None

        results = []
        for item in raw_results[:num_results]:
            results.append({
                "title":   item.get("title", ""),
                "link":    item.get("url", ""),
                "content": item.get("content", ""),
                "source":  item.get("engine", ""),
                "date":    item.get("publishedDate", ""),
            })

        logger.info(f"[SearXNG] {len(results)} results from {SEARXNG_URL}")
        return results

    except Exception as e:
        logger.warning(f"[SearXNG] Failed: {type(e).__name__}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def perform_search(query: str, num_results: int = 10, fetch_webpages: bool = True) -> dict:
    """
    Search the web. Tries DuckDuckGo first, then SearXNG if configured.
    Optionally fetches the full webpage content for top results.
    """
    if not query:
        return {"status": "error", "error": "Query is required"}

    num_results = max(1, min(int(num_results), 20))

    # Try DuckDuckGo first (always available, no config needed)
    results = _search_duckduckgo(query, num_results)
    engine = "duckduckgo"

    # Fallback to SearXNG if configured and DuckDuckGo failed
    if not results:
        results = _search_searxng(query, num_results)
        engine = "searxng"

    if not results:
        return {
            "status": "error",
            "error":  "All search backends failed. Try again in a few seconds.",
        }

    # Fetch full webpage content if requested
    if fetch_webpages:
        try:
            from smith.tools.URL_READER import run_url_reader
            
            # Fetch up to top 3 results
            fetch_count = min(3, len(results))
            logger.info(f"[{engine.upper()}] Fetching full webpages for top {fetch_count} results...")
            
            for i in range(fetch_count):
                url = results[i].get("link")
                if not url:
                    continue
                    
                # Get the full page text, capped to roughly 1500 words
                page_data = run_url_reader(url, max_length=15000)
                
                if page_data.get("status") == "success" and page_data.get("content"):
                    # Replace the short snippet with the full extracted text
                    results[i]["content"] = page_data["content"]
                    logger.debug(f"[{engine.upper()}] Fetched {page_data.get('content_length')} chars from [{i+1}] {url}")
        except ImportError:
            logger.warning("URL_READER not found, skipping full webpage fetch.")
        except Exception as e:
            logger.warning(f"Error fetching full webpages: {e}")

    response_chunks = []
    truncated = False
    for r in results:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not (title or content):
            continue

        if len(content) > PER_RESULT_CONTENT_CHARS:
            content = content[:PER_RESULT_CONTENT_CHARS].rstrip() + "..."
            truncated = True

        response_chunks.append(f"{title}\n{content}" if title else content)

    response_text = "\n\n".join(response_chunks)
    if len(response_text) > MAX_RESPONSE_CHARS:
        response_text = response_text[:MAX_RESPONSE_CHARS].rstrip() + "..."
        truncated = True

    return {
        "status":     "success",
        "response":   response_text,
        "query_used": query,
        "engine":     engine,
        "truncated": truncated,
        "max_response_chars": MAX_RESPONSE_CHARS,
        "per_result_content_chars": PER_RESULT_CONTENT_CHARS,
    }


def run_google_search(query: str, num_results: int = 10, fetch_webpages: bool = True) -> dict:
    """
    Full search pipeline: optimize query → search → return results.

    Note: Function name kept as run_google_search for backward compatibility
    with the planner and orchestrator.
    """
    optimized_query = optimize_query(query)
    return perform_search(optimized_query, num_results, fetch_webpages)


# ─────────────────────────────────────────────────────────────────────────────
# ALIASES — backward compatibility for planner
# ─────────────────────────────────────────────────────────────────────────────

google_search = run_google_search
search        = run_google_search
query_fn      = run_google_search


# ─────────────────────────────────────────────────────────────────────────────
# SMITH AGENT METADATA
# ─────────────────────────────────────────────────────────────────────────────

METADATA = {
    "name":        "google_search",
    "description": (
        "Search the web for real-time information, news, or facts. "
        "Uses DuckDuckGo as primary search engine — no API key needed. "
        "Optionally falls back to a self-hosted SearXNG instance if "
        "SEARXNG_URL is set in .env. "
        "Includes an internal LLM query optimizer via NVIDIA Inference that "
        "automatically rewrites vague or natural-language queries into precise "
        "search strings. Pass raw user intent directly. "
        "Automatically fetches and extracts the full page text of the top 3 results "
        "by default, providing deep research context instead of just short snippets."
    ),
    "function":    "run_google_search",
    "dangerous":   False,
    "domain":      "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type":        "string",
                "description": (
                    "The search query. Can be raw natural language — the internal "
                    "optimizer will convert it into a precise search string."
                )
            },
            "num_results": {
                "type":        "integer",
                "description": "Number of search results to retrieve (1–20, default 10).",
                "default":     10,
                "minimum":     1,
                "maximum":     20,
            },
            "fetch_webpages": {
                "type":        "boolean",
                "description": "If True, auto-fetches the full page text for the top 3 results for deeper context. Default True.",
                "default":     True
            },
        },
        "required": ["query"],
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

    test_queries = [
        "how to setup a business in dubai from india",
        "latest AI regulation news 2025",
    ]

    for raw in test_queries:
        print(f"\n{'─'*60}")
        print(f"RAW:  {raw}")
        result = run_google_search(raw, num_results=3)
        print(f"USED: {result.get('query_used')}")
        print(f"ENGINE: {result.get('engine', 'N/A')}")
        print(f"STATUS: {result['status']}")
        if result.get("error"):
            print(f"ERROR: {result['error']}")
        for i, r in enumerate(result.get("response", "").split("\n\n"), 1):
            print(f"  [{i}] {r}")