"""
GOOGLE SEARCHER — Official API
------------------------------
Uses the Google Custom Search JSON API.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

# ------------------------------
# Core Logic (Renamed to prevent recursion)
# ------------------------------

def perform_google_search(query: str, num_results: int = 3):
    """
    Actual implementation of the search logic.
    """
    if not query:
        return {"status": "error", "error": "Query is required"}
    
    if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
        return {"status": "error", "error": "Missing GOOGLE_API_KEY or SEARCH_ENGINE_ID in .env"}

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "num": int(num_results)  # Safety Cast
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        if "items" in data:
            for item in data["items"]:
                results.append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "content": item.get("snippet", "")
                })
        
        if not results:
            return {"status": "success", "result": [], "message": "No results found."}

        return {"status": "success", "result": results}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE (Wrapper)
# ===========================================================================

def run_google_search(query: str, num_results: int = 3):
    """
    Dispatcher function.
    """
    return perform_google_search(query, int(num_results))

# --- SAFE ALIASES (The Anti-Hallucination Guard) ---
google_search = run_google_search
search = run_google_search
query = run_google_search  # <--- CRITICAL FIX: The Planner often calls this!
# ---------------------------------------------------

# ===========================================================================
# METADATA (SMS v1.0)
# ===========================================================================

METADATA = {
    "name": "google_search",
    "description": "Search Google for real-time information, news, or facts.",
    "function": "run_google_search",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search keywords."
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 3).",
                "default": 3
            }
        },
        "required": ["query"]
    }
}