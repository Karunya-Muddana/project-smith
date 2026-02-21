"""
WIKIPEDIA LOOKUP v1 — Structured Wikipedia Summaries
=====================================================
Pipeline:
    RAW QUERY
        │
        ▼
    [Wikipedia API]  ← wikipedia-api pip (free, no API key)
        │  Searches for matching page
        │  Returns summary, sections, categories, links
        ▼
    STRUCTURED RESULT

No API key needed. No quotas. Completely free.
"""

import logging
import wikipediaapi

logger = logging.getLogger(__name__)

USER_AGENT = "SmithAgent/3.0 (research bot; contact@example.com)"

SUMMARY_MAX_CHARS  = 3000      # summary limit
SECTION_MAX_CHARS  = 2000      # per-section text limit
MAX_SECTIONS       = 10        # max sections to return


# ─────────────────────────────────────────────────────────────────────────────
# CORE
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sections(page, max_sections: int = MAX_SECTIONS) -> list[dict]:
    """Extract top-level sections with their text."""
    sections = []
    for section in page.sections:
        if len(sections) >= max_sections:
            break
        text = section.text.strip()
        if not text or len(text) < 20:
            continue

        if len(text) > SECTION_MAX_CHARS:
            text = text[:SECTION_MAX_CHARS] + "... [truncated]"

        sections.append({
            "heading": section.title,
            "text":    text,
        })
    return sections


def run_wikipedia_lookup(query: str, language: str = "en") -> dict:
    """
    Look up a topic on Wikipedia.

    Returns structured data: summary, sections, categories, and URL.
    If the exact page isn't found, searches for the closest match.
    """
    if not query or not query.strip():
        return {"status": "error", "error": "Query is required."}

    query = query.strip()

    try:
        wiki = wikipediaapi.Wikipedia(
            user_agent=USER_AGENT,
            language=language,
        )

        # Try exact page first
        page = wiki.page(query)

        if not page.exists():
            # Try title-case and common variations
            variations = [
                query.title(),
                query.replace(" ", "_"),
                query.upper(),
            ]
            for v in variations:
                page = wiki.page(v)
                if page.exists():
                    break

        if not page.exists():
            return {
                "status": "error",
                "error":  f"No Wikipedia page found for '{query}'. Try a more specific term.",
                "query":  query,
            }

        # Build result
        summary = page.summary
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = summary[:SUMMARY_MAX_CHARS] + "... [truncated]"

        sections   = _extract_sections(page)
        categories = [c.replace("Category:", "") for c in list(page.categories.keys())[:10]]

        result = {
            "status":     "success",
            "title":      page.title,
            "url":        page.fullurl,
            "summary":    summary,
            "sections":   sections,
            "categories": categories,
            "language":   language,
        }

        logger.info(f"[Wikipedia] Found: '{page.title}' ({len(summary)} chars, "
                     f"{len(sections)} sections)")
        return result

    except Exception as e:
        logger.warning(f"[Wikipedia] Failed: {type(e).__name__}: {e}")
        return {
            "status": "error",
            "error":  f"Wikipedia lookup failed: {str(e)}",
            "query":  query,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ALIASES
# ─────────────────────────────────────────────────────────────────────────────

wikipedia_lookup = run_wikipedia_lookup
wiki             = run_wikipedia_lookup


# ─────────────────────────────────────────────────────────────────────────────
# SMITH AGENT METADATA
# ─────────────────────────────────────────────────────────────────────────────

METADATA = {
    "name":        "wikipedia_lookup",
    "description": (
        "Look up a topic on Wikipedia. Returns a structured summary, "
        "top-level sections with text, categories, and page URL. "
        "Useful for background context, definitions, or factual overviews "
        "to complement search/news results. No API key needed."
    ),
    "function":    "run_wikipedia_lookup",
    "dangerous":   False,
    "domain":      "data",
    "output_type": "factual",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type":        "string",
                "description": (
                    "The topic to look up. Use proper nouns and specific terms "
                    "for best results (e.g. 'Dubai', 'Free trade zone', "
                    "'Companies Act India')."
                ),
            },
            "language": {
                "type":        "string",
                "description": "Wikipedia language code (default 'en').",
                "default":     "en",
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

    result = run_wikipedia_lookup("Jebel Ali Free Zone")

    print(f"\n{'═'*60}")
    print(f"  Title:      {result.get('title')}")
    print(f"  URL:        {result.get('url')}")
    print(f"  Categories: {', '.join(result.get('categories', [])[:5])}")
    print(f"  Sections:   {len(result.get('sections', []))}")
    print(f"{'═'*60}")
    print(f"\nSummary:\n{result.get('summary', '')[:500]}...")
    for s in result.get("sections", [])[:3]:
        print(f"\n## {s['heading']}")
        print(f"   {s['text'][:200]}...")
