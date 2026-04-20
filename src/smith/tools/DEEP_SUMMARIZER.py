import json
import logging
from typing import Dict, Any, Union

from smith.tools.LLM_CALLER import call_llm

logger = logging.getLogger("smith.deep_summarizer")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

MAX_INPUT_CHARS = 100_000
MIN_INPUT_CHARS = 50          # Lowered: upstream tools may return short but valid summaries
DEEP_MODEL = "mistralai/devstral-2-123b-instruct-2512"


# ─────────────────────────────────────────────────────────────
# INPUT EXTRACTION HELPER
# ─────────────────────────────────────────────────────────────

def _extract_text(raw: Any) -> str:
    """
    Robustly extract usable text from whatever the template engine
    resolves {{STEPS.N}} to.

    The planner may pass:
      - A plain string  (ideal — from {{STEPS.N.response}})
      - A dict          (from {{STEPS.N}} bare ref — extract known text fields)
      - A list of dicts (from google_search / news_fetcher results)
      - None / empty

    Returns a clean UTF-8 string, or "" if nothing usable is found.
    """
    if raw is None:
        return ""

    # ── Already a string ─────────────────────────────────────
    if isinstance(raw, str):
        stripped = raw.strip()
        # Guard: stringified dict/list that resolved incorrectly
        if stripped in ("{}", "[]", "None", "null", ""):
            return ""
        return stripped

    # ── Dict — try common text fields in priority order ──────
    if isinstance(raw, dict):
        for field in ("response", "summary", "text", "content", "body", "answer"):
            val = raw.get(field)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

        # Try results sub-key (google_search shape)
        results = raw.get("results", [])
        if isinstance(results, list) and results:
            return _extract_text(results)

        # Last resort: serialize the whole dict (loses nothing, may be noisy)
        try:
            serialized = json.dumps(raw, ensure_ascii=False, indent=2)
            return serialized if len(serialized) > 10 else ""
        except Exception:
            return str(raw)

    # ── List — join all extractable text from each item ──────
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict):
                for field in ("snippet", "body", "text", "content", "response", "title"):
                    val = item.get(field)
                    if val and isinstance(val, str) and val.strip():
                        parts.append(val.strip())
                        break
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return "\n\n".join(parts)

    # ── Fallback ──────────────────────────────────────────────
    return str(raw).strip()


# ─────────────────────────────────────────────────────────────
# CORE TOOL
# ─────────────────────────────────────────────────────────────

def run_deep_summarizer(text: Any, query: str) -> Dict[str, Any]:
    """
    Deep reasoning summarizer.

    Args:
        text:  The input data to reason over. Accepts str, dict, or list —
               handles all shapes that upstream tool nodes may produce.
        query: The user's original question or analysis goal.

    Returns:
        {"status": "success", "response": <str>, "meta": {...}}
        {"status": "error",   "error":    <str>}
    """
    logger.debug("DeepSummarizer called | query=%r | input_type=%s", query, type(text).__name__)

    try:
        # ── Step 1: Extract usable text from whatever we received ──
        text_str = _extract_text(text)

        logger.debug("Extracted text length: %d chars", len(text_str))

        if not text_str:
            logger.error(
                "DeepSummarizer received empty input after extraction. "
                "Planner likely used bare {{STEPS.N}} ref instead of {{STEPS.N.response}}. "
                "raw input type=%s, repr=%r",
                type(text).__name__,
                str(text)[:200],
            )
            return {
                "status": "error",
                "error": (
                    "DeepSummarizer received empty text. "
                    "Upstream node may have failed or returned no content."
                ),
            }

        if len(text_str) < MIN_INPUT_CHARS:
            logger.warning(
                "DeepSummarizer input is very short (%d chars) — proceeding anyway.",
                len(text_str),
            )
            # Don't hard-fail on short input — let the model try.
            # Short upstream summaries can still produce useful analysis.

        # ── Step 2: Truncate to model context budget ──────────────
        truncated = False
        if len(text_str) > MAX_INPUT_CHARS:
            logger.warning("Truncating input from %d to %d chars", len(text_str), MAX_INPUT_CHARS)
            text_str = text_str[:MAX_INPUT_CHARS]
            truncated = True

        # ── Step 3: Build prompt ───────────────────────────────────
        prompt = f"""\
You are a high-level reasoning engine inside an autonomous AI system.
Your job is to deeply analyze the provided data and answer the user's query
with precise, structured reasoning.

USER QUERY:
{query}

INPUT DATA:
{text_str}

INSTRUCTIONS:
- Extract the most important facts directly relevant to the query.
- Explain cause → effect chains explicitly (X causes Y because Z).
- Identify non-obvious patterns and relationships.
- State concrete implications for the near and medium term.
- Be direct. No filler, no repetition, no generic statements.

RESPOND IN THIS STRUCTURE:

## Core Insights
<3–5 bullet points of the most critical findings>

## Cause → Effect Relationships
<explicit chain reasoning, e.g. "Rising oil prices → higher energy costs for data centers → compressed margins for GPU-intensive companies like Nvidia">

## Key Patterns
<patterns in the data that are not obvious>

## Implications
<what this means going forward — for investors, for the industry, for the user's specific question>
"""

        logger.debug("Prompt length: %d chars", len(prompt))

        # ── Step 4: Call model ─────────────────────────────────────
        response = call_llm(prompt, model=DEEP_MODEL)

        if not isinstance(response, dict):
            logger.error("Unexpected response type from call_llm: %s", type(response))
            return {"status": "error", "error": "Invalid response format from LLM"}

        if response.get("status") != "success":
            err = response.get("error", "LLM call failed")
            logger.error("DeepSummarizer LLM call failed: %s", err)
            return {"status": "error", "error": err}

        output_text = response.get("response", "").strip()

        if not output_text:
            logger.error("Model returned empty output")
            return {"status": "error", "error": "Model returned empty output"}

        logger.debug("DeepSummarizer success | output length: %d chars", len(output_text))

        return {
            "status": "success",
            "response": output_text,
            "meta": {
                "model": DEEP_MODEL,
                "input_chars": len(text_str),
                "truncated": truncated,
            },
        }

    except Exception as e:
        logger.exception("DeepSummarizer crashed with unhandled exception")
        return {"status": "error", "error": str(e)}