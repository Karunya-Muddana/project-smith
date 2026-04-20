"""
Query Router
------------
Classifies an incoming query as "direct" (simple LLM call) or "planner"
(full DAG pipeline with tools).  Also provides direct-answer and speech-
conversion helpers used by the CLI and voice mode.

Classification is three-tier:
  1. Fast regex heuristic  (covers ~90 % of queries, no API call)
  2. LLM second-opinion    (only for ambiguous mid-zone queries, ~5 tokens)
  3. Default to "direct"   (fail-safe)
"""

from __future__ import annotations

import json
import os
import re
import logging
from typing import Literal, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("smith.router")

# ─────────────────────────────────────────────────────────────────────────────
# Heuristic classification
# ─────────────────────────────────────────────────────────────────────────────

_PLANNER_RE = re.compile(
    r"\b("
    r"search|look\s+up|look\s+for|find\s+me|fetch|latest|recent|current|live|real[-\s]?time|"
    r"news|today|right\s+now|as\s+of|breaking|"
    r"stock|share\s+price|price\s+of|ticker|market|nasdaq|nyse|s&p|stocks|"
    r"weather|temperature|forecast|humidity|wind|rain|"
    r"crypto|bitcoin|ethereum|btc|eth|solana|coin|"
    r"calculate|convert|compute|how\s+much\s+is|how\s+many\s+are|"
    r"compare|versus|vs\.?|"
    r"analyze|analyse|review\s+the|check\s+the|monitor|"
    r"sec\s+filing|earnings|revenue|balance\s+sheet|"
    r"send\s+email|check\s+email|gmail|my\s+calendar|schedule\s+a|"
    r"what\s+happened|what[''`]?s\s+happening|who\s+won|"
    r"rsi|macd|moving\s+average|technical\s+indicator|"
    r"wikipedia|wiki\s+article"
    r")\b",
    re.IGNORECASE,
)

_DIRECT_RE = re.compile(
    r"^("
    r"(what|who|where|when|why|how)\s+(is|are|was|were|does|do|did|can|could|should|would|will)\b|"
    r"explain\b|define\b|tell\s+me\s+(about|what|how|why)|"
    r"write\s+(a|me|an|the)|generate\b|create\b|draft\b|compose\b|"
    r"translate\b|help\s+me\s+(write|understand|create|think|build)|"
    r"what\s+does\s+.+\s+mean|give\s+me\s+an\s+example|"
    r"(can|could)\s+you\s+(help|write|explain|create|draft|show)|"
    r"summarize\s+(this|the\s+following)|rewrite\b|rephrase\b|"
    r"code\s+(a|an|the)|write\s+code|implement\b"
    r")",
    re.IGNORECASE,
)

# Queries that fall into neither bucket — LLM decides
_AMBIGUOUS_RE = re.compile(
    r"^(tell me|give me|show me|i want to know|i need|can you tell|"
    r"what do you think|your thoughts on|opinion on)",
    re.IGNORECASE,
)


def classify(query: str) -> Literal["direct", "planner"]:
    """
    Returns "direct" for simple LLM-only queries, "planner" for anything
    that needs tools, live data, or multi-step orchestration.
    """
    q = query.strip()
    words = q.split()

    # Very short conversational queries → direct
    if len(words) <= 4 and not _PLANNER_RE.search(q):
        return "direct"

    # Explicit tool / real-time signals override everything
    if _PLANNER_RE.search(q):
        return "planner"

    # Classic explanation / writing patterns
    if _DIRECT_RE.search(q):
        return "direct"

    # Two or more "and" clauses usually signal compound research
    if len(re.findall(r"\band\b", q, re.IGNORECASE)) >= 2:
        return "planner"

    # Very long queries are usually research/analysis tasks
    if len(words) > 18:
        return "planner"

    # Ambiguous middle zone → ask the LLM (fast, ~5 tokens out)
    if _AMBIGUOUS_RE.search(q) or 8 <= len(words) <= 18:
        llm_verdict = _llm_classify(q)
        if llm_verdict:
            return llm_verdict

    return "direct"


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_MODEL = os.getenv(
    "SMITH_LLM_MODEL",
    "meta/llama-4-maverick-17b-128e-instruct",
)


def _api_key() -> str:
    return os.getenv(
        "NVIDIA_LLM_API_KEY",
        "",
    )


def _call(system: str, user: str, max_tokens: int = 512) -> str:
    import requests
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("Missing NVIDIA_LLM_API_KEY")
    resp = requests.post(
        _NVIDIA_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stream": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return (content or "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# LLM classification (second-opinion, ~5 tokens)
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFY_SYS = (
    "You classify user queries. Reply with ONLY one word: direct OR planner.\n"
    "direct  = answerable from general knowledge, no real-time data or tools needed.\n"
    "planner = requires web search, live data (stocks/weather/news/crypto), "
    "calculations, or multiple tool calls."
)


def _llm_classify(query: str) -> Optional[Literal["direct", "planner"]]:
    try:
        result = _call(_CLASSIFY_SYS, query, max_tokens=5).lower()
        if "planner" in result:
            return "planner"
        if "direct" in result:
            return "direct"
    except Exception as e:
        logger.debug(f"[Router] LLM classify failed: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Direct LLM answer (no tools)
# ─────────────────────────────────────────────────────────────────────────────

_TEXT_SYS = (
    "You are Smith, a concise AI assistant. "
    "Answer clearly and directly. No filler phrases. "
    "No markdown unless the user asks. "
    "Keep answers under 4 sentences unless more detail is explicitly requested."
)


def _with_memory_context(query: str) -> str:
    """
    Best-effort memory injection for direct answers.
    Falls back to the raw query if memory is unavailable.
    """
    try:
        from smith.config import config
        if not config.memory_enabled:
            return query

        from smith.memory import get_memory_manager

        mem_ctx = get_memory_manager().read_context(
            query,
            top_k=min(max(2, config.memory_top_k), 6),
            max_chars=min(config.memory_inject_max_chars, 1000),
        )
        if not mem_ctx:
            return query

        return (
            "[Relevant context from past sessions]\n"
            f"{mem_ctx}\n"
            "[End memory context]\n\n"
            f"Current user query: {query}"
        )
    except Exception as e:
        logger.debug(f"[Router] memory injection skipped: {e}")
        return query


def _voice_sys(user_name: str = "") -> str:
    name = f" You are speaking with {user_name}." if user_name else ""
    return (
        f"You are Smith, an AI assistant.{name} "
        "Answer in natural spoken English — no bullet points, no markdown, "
        "no numbered lists, no special characters, no JSON. "
        "2 to 4 sentences maximum. Sound like a knowledgeable friend talking directly."
    )


def direct_answer(query: str, voice_mode: bool = False, user_name: str = "") -> str:
    """
    Call the LLM directly (no tools).  Returns the response string.
    Uses a conversational system prompt in voice mode.
    """
    system = _voice_sys(user_name) if voice_mode else _TEXT_SYS
    user_prompt = _with_memory_context(query)
    try:
        return _call(system, user_prompt, max_tokens=280 if voice_mode else 1024)
    except Exception as e:
        logger.warning(f"[Router] direct_answer failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Speech conversion  (structured / JSON response → spoken text)
# ─────────────────────────────────────────────────────────────────────────────

_MD_RE  = re.compile(r"(\*{1,3}|_{1,3}|`{1,3}|#{1,6}\s?|>\s?|\[([^\]]+)\]\([^)]*\))")
_URL_RE = re.compile(r"https?://\S+")
_REDACTED_RE = re.compile(r"\[REDACTED[^\]]*\]", re.IGNORECASE)


def _strip_markdown(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _MD_RE.sub("", text)
    text = _REDACTED_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_from_json(text: str) -> str:
    """
    If `text` is a JSON object or array, extract all string leaf values
    in order and join them into a single readable string.
    """
    stripped = text.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return text

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        # Not valid JSON — try extracting quoted strings as a best effort
        return " ".join(re.findall(r'"([^"]{10,})"', stripped))

    parts: list[str] = []

    def _walk(obj):
        if isinstance(obj, str) and len(obj) > 3:
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return "  ".join(parts)


def to_speech_text(response: str, user_name: str = "") -> str:
    """
    Convert a potentially structured/JSON/markdown response into natural
    spoken text suitable for TTS.

    Pipeline:
      1. Extract text from JSON (if applicable)
      2. Strip markdown + URLs
      3. If already short and clean → return as-is
      4. Otherwise ask the LLM to restate as 2–4 spoken sentences
    """
    if not response or not response.strip():
        return ""

    # Step 1 — pull text out of JSON structures
    clean = _extract_from_json(response)

    # Step 2 — strip markdown / URLs / redaction tokens
    clean = _strip_markdown(clean)

    if not clean:
        return ""

    # Step 3 — if it's already short and clean, return it directly
    word_count = len(clean.split())
    has_structure = re.search(r"[*#\[\]|{}\n]{2,}", clean)
    if word_count <= 55 and not has_structure:
        return clean

    # Step 4 — LLM restatement as natural speech
    system = _voice_sys(user_name)
    prompt = (
        "Restate the following as 2–4 natural spoken sentences. "
        "No bullet points, no markdown, no lists, no URLs, no JSON. "
        "Sound like a knowledgeable person speaking to the listener:\n\n"
        + clean[:1200]
    )
    try:
        spoken = _call(system, prompt, max_tokens=220)
        if spoken and len(spoken) > 15:
            return spoken
    except Exception as e:
        logger.debug(f"[Router] to_speech_text LLM failed: {e}")

    # Final fallback — first 180 words of cleaned text
    return " ".join(clean.split()[:180])
