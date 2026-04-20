"""
Synthesis Router
----------------
Selects the best LLM model for the final synthesis step based on the
characteristics of the current run:
  - Estimated token count of the trace
  - Presence of numeric/finance/math signals in the user message
  - Total number of nodes executed

Decision matrix:
  ┌──────────────────────┬────────────────────────────┐
  │ Condition            │ Model                      │
  ├──────────────────────┼────────────────────────────┤
  │ small trace (<512t)  │ synthesis_fast_model       │
  │ math/finance heavy   │ synthesis_heavy_model      │
  │ default              │ primary_model              │
  └──────────────────────┴────────────────────────────┘
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.synthesis_router")

# Keywords that indicate a genuinely math/finance-heavy synthesis
# NOTE: Do NOT add generic analytical words like 'analysis', 'compare', 'statistics'
# Those apply to knowledge-synthesis queries that don't need the heavy model.
_MATH_SIGNALS = re.compile(
    r"\b(stock|price|finance|revenue|earnings|percent|ratio|growth|"
    r"calculate|average|median|return|yield|valuation|"
    r"weather|temperature|forecast)\b",
    re.IGNORECASE,
)

# Token approximation: 1 token ≈ 4 chars
_CHARS_PER_TOKEN = 4

# Threshold for "small" trace (tokens)
_SMALL_TRACE_THRESHOLD = 512

# Threshold for "large" trace that warrants heavy model (tokens)
_LARGE_TRACE_THRESHOLD = 4000


def _estimate_trace_tokens(trace: List[Optional[Dict[str, Any]]]) -> int:
    """Estimate the number of tokens in the trace data."""
    total_chars = 0
    for entry in trace:
        if entry is None:
            continue
        result = entry.get("result")
        if result is not None:
            try:
                import json
                total_chars += len(json.dumps(result, default=str))
            except Exception:
                total_chars += len(str(result))
    return total_chars // _CHARS_PER_TOKEN


def _is_math_heavy(user_msg: str, nodes: List[Dict[str, Any]]) -> bool:
    """Return True if the query or plan contains strong numeric/finance signals."""
    if _MATH_SIGNALS.search(user_msg):
        return True
    # Also check if any node used finance/weather tools
    for node in nodes:
        tool = node.get("tool", "")
        if tool in ("finance_fetcher", "weather_fetcher", "calculator"):
            return True
    return False


def select_synthesis_model(
    trace: List[Optional[Dict[str, Any]]],
    nodes: List[Dict[str, Any]],
    user_msg: str,
) -> str:
    """
    Select the best LLM for synthesis given the context.

    Args:
        trace: Execution trace (may contain None for skipped nodes).
        nodes: DAG node list from the planner.
        user_msg: Original user request string.

    Returns:
        LLM model name string.
    """
    from smith.config import config  # lazy import to avoid circular deps

    token_estimate = _estimate_trace_tokens(trace)
    math_heavy = _is_math_heavy(user_msg, nodes)
    n_nodes = len(nodes)

    # Route decision
    # Large analytical traces (many llm_caller nodes, no finance tools) should
    # use primary_model — heavy model is reserved for genuine math/finance queries.
    llm_heavy_nodes = sum(1 for n in nodes if n.get("tool") == "llm_caller")
    is_writing_task = llm_heavy_nodes >= 3 and not math_heavy

    if token_estimate < _SMALL_TRACE_THRESHOLD and n_nodes <= 2 and not math_heavy:
        chosen = config.synthesis_fast_model
        reason = f"small trace ({token_estimate}t, {n_nodes} nodes)"
    elif math_heavy:
        chosen = config.synthesis_heavy_model
        reason = "math/finance-heavy query"
    elif token_estimate >= _LARGE_TRACE_THRESHOLD and not is_writing_task:
        chosen = config.synthesis_heavy_model
        reason = f"large trace ({token_estimate}t)"
    else:
        chosen = config.primary_model
        reason = "analytical/writing query" if is_writing_task else "default (medium complexity)"

    logger.info(
        f"SynthesisRouter: selected '{chosen}' — {reason} "
        f"[tokens≈{token_estimate}, nodes={n_nodes}, math={math_heavy}]"
    )
    return chosen
