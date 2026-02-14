"""
ARXIV FETCHER — Official arXiv API
----------------------------------
Fetches academic papers from arXiv using keyword search.
"""

import requests

# ------------------------------
# Core Logic
# ------------------------------


def perform_arxiv_search(query: str, max_results: int = 5):
    """
    Fetch academic papers from arXiv based on a search query.
    Returns title, authors, summary, and URL.
    """
    if not query:
        return {"status": "error", "error": "Query is required"}

    try:
        url = "https://export.arxiv.org/api/query"
        params = {"search_query": query, "start": 0, "max_results": int(max_results)}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        xml_text = response.text

        # manual parsing (lightweight) — avoids XML libraries to keep the tool portable
        items = xml_text.split("<entry>")
        results = []

        for item in items[1:]:
            title = item.split("<title>")[1].split("</title>")[0].strip()
            summary = item.split("<summary>")[1].split("</summary>")[0].strip()
            link = item.split("<id>")[1].split("</id>")[0].strip()
            authors = [a.split("</name>")[0].strip() for a in item.split("<name>")[1:]]

            results.append(
                {"title": title, "authors": authors, "summary": summary, "link": link}
            )

        return {"status": "success", "result": results}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# =====================================================================
# SMITH AGENT INTERFACE (Wrapper)
# =====================================================================


def run_arxiv_search(query: str, max_results: int = 5):
    return perform_arxiv_search(query, int(max_results))


# --- SAFE ALIASES (Anti-Hallucination Guard)
arxiv_search = run_arxiv_search
search = run_arxiv_search
query = run_arxiv_search
# ---------------------------------------------------

# =====================================================================
# METADATA — identical structure to Google Search
# =====================================================================

METADATA = {
    "name": "arxiv_search",
    "description": "Fetch academic papers from arXiv by keyword search.",
    "function": "run_arxiv_search",
    "dangerous": False,
    "domain": "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Keyword(s) for paper search, e.g. 'transformers', 'reinforcement learning', etc."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Number of papers to return",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}
