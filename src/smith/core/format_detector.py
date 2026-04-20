"""
Format Detector
---------------
Classifies user intent into one of three output modes:
  - summary    → compact panels (key findings, caveats, sources)
  - full_paper → full markdown body rendered directly
  - default    → structured answer with key findings panel
"""

from __future__ import annotations

import re
from typing import Literal

FormatType = Literal["summary", "full_paper", "default"]

# ─────────────────────────────────────────────────────────────────────────────
# Signal patterns
# ─────────────────────────────────────────────────────────────────────────────

_SUMMARY_SIGNALS = re.compile(
    r"\b("
    r"tl;?dr|briefly|brief|quick\s+(?:summary|overview|answer)|"
    r"in\s+a\s+(?:few|couple\s+of)\s+(?:words|sentences|lines|paragraphs)|"
    r"short\s+(?:answer|summary|version)|"
    r"give\s+me\s+(?:a\s+)?(?:short|brief|quick)|"
    r"summarize|summarise|sum\s+up|"
    r"overview|high.?level|key\s+points\s+only|"
    r"keep\s+it\s+(?:short|brief|concise)"
    r")\b",
    re.IGNORECASE,
)

_FULL_PAPER_SIGNALS = re.compile(
    r"\b("
    r"research\s+paper|white\s+paper|technical\s+report|full\s+report|"
    r"comprehensive|in.?depth|in\s+detail|detailed|"
    r"write\s+(?:a\s+)?(?:full|complete|comprehensive|detailed)|"
    r"cover\s+(?:all|every|each)\s+(?:section|aspect|topic|part)|"
    r"every\s+section|all\s+sections|"
    r"don.t\s+skip|include\s+everything|"
    r"thorough|exhaustive|extensive|"
    r"step.by.step\s+explanation|"
    r"explain\s+(?:everything|it\s+all|in\s+full|in\s+detail)|"
    # Also trigger on structured multi-section asks
    r"\d+\.\s+\w+.*\d+\.\s+\w+"  # "1. Section ... 2. Section" numbered lists
    r")\b",
    re.IGNORECASE,
)


def detect_format(user_msg: str) -> FormatType:
    """
    Classify user intent as 'summary', 'full_paper', or 'default'.

    Decision logic:
    1. Action-oriented queries (send email, etc.) → default (never full_paper)
    2. If both summary and full_paper signals are present, full_paper wins
       (user explicitly asked for detail, the brief mention was incidental)
    3. If only summary signals → summary
    4. If only full_paper signals → full_paper
    5. Otherwise → default

    Args:
        user_msg: The original user query string.

    Returns:
        One of "summary", "full_paper", "default".
    """
    # Action-oriented queries should never produce full_paper output.
    # "Send a detailed email" means the EMAIL is detailed, not the synthesis.
    _ACTION_SIGNALS = re.compile(
        r"\b(send|email|mail|forward|reply|compose|draft\s+(?:an?\s+)?(?:email|message|letter))\b",
        re.IGNORECASE,
    )
    is_action_query = bool(_ACTION_SIGNALS.search(user_msg))

    has_summary    = bool(_SUMMARY_SIGNALS.search(user_msg))
    has_full_paper = bool(_FULL_PAPER_SIGNALS.search(user_msg))

    # For action queries (send email, etc.), default format is always correct
    if is_action_query:
        return "summary" if has_summary else "default"

    if has_full_paper:
        # Explicit detail request always wins
        return "full_paper"
    if has_summary:
        return "summary"
    return "default"


def format_instructions(format_type: FormatType) -> str:
    """
    Return synthesis prompt instructions for the given format type.
    Injected into the final synthesis prompt so the LLM knows what to produce.
    """
    if format_type == "summary":
        return (
            "OUTPUT FORMAT: Brief, direct answer.\n"
            "Return a JSON object with this exact schema:\n"
            '{"summary": "<2-3 sentences, plain factual language>", '
            '"key_findings": ["<specific point>", ...], '
            '"caveats": ["<optional>"], "sources": ["<optional>"]}\n'
            "Keep key_findings to 3-5 items. No marketing language. Be precise.\n"
        )
    elif format_type == "full_paper":
        return (
            "OUTPUT FORMAT: Full detailed response in PURE MARKDOWN.\n"
            "Do NOT return JSON.\n"
            "Structure with # Title, ## sections, ### subsections.\n"
            "Use prose paragraphs and ``` code blocks where relevant.\n"
            "Do NOT truncate. Cover every section fully.\n"
        )
    else:  # default
        return (
            "OUTPUT FORMAT: Return a JSON object:\n"
            '{"summary": "<direct answer in plain language, 1-3 sentences>", '
            '"key_findings": ["<specific factual point>", ...], '
            '"caveats": ["<optional>"], "sources": ["<optional>"]}\n'
            "key_findings: 3-6 specific items. No filler. No marketing language.\n"
            "If you cannot produce JSON, return plain text.\n"
        )
