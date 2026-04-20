"""
Template Engine — Labeled Interpolation & Budget Truncation
------------------------------------------------------------
Handles {{STEPS.N}} interpolation with:
  - Labeled headers for llm_caller synthesis prompts (Problem 1)
  - Null/failure fallback with custom default syntax (Problem 2)
  - Token budget truncation per upstream tool (Problem 6)
"""

import re
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.template_engine")

# ============================================================================
# CONSTANTS
# ============================================================================

# Anti-fabrication system instruction prepended to llm_caller prompts that have result data
SYNTHESIS_SYSTEM_INSTRUCTION = (
    "Prioritize the data in the <result> tags below when answering. "
    "If a result is marked UNAVAILABLE, acknowledge the gap. "
    "Never fabricate numbers, prices, costs, or statistics. "
    "If no result data is provided, use your training knowledge to answer.\n\n"
)

# Maximum total tokens for synthesis prompt (leaves room for system + output)
MAX_SYNTHESIS_TOKENS = 6000

# Per-tool-type token budgets
TOKEN_BUDGETS = {
    "finance_fetcher":  200,
    "weather_fetcher":  200,
    "wikipedia_lookup": 800,
    "google_search":    400,
    "news_fetcher":     1500,
    "arxiv_search":     600,
    "url_reader":       800,
    "code_agent":       2000,   # can be large; extract .response or condense
    "code_assistant":   1000,
    "llm_caller":       800,    # prefer .response dotted path for these
    "sub_agent":        1200,
}
DEFAULT_TOKEN_BUDGET = 500

# Regex patterns
# Matches {{STEPS.N}} (bare reference) and {{STEPS.N.path}} (dotted path)
STEP_REF_BARE = re.compile(r"\{\{\s*STEPS\.(\d+)\s*\}\}", re.IGNORECASE)
# Matches {{STEPS.N | default: "message"}} pipe syntax
STEP_REF_PIPE = re.compile(
    r"\{\{\s*STEPS\.(\d+)\s*\|\s*default:\s*\"([^\"]*)\"\s*\}\}", re.IGNORECASE
)
# Matches {{STEPS.N.path}} dotted access
STEP_REF_DOT = re.compile(r"\{\{\s*STEPS\.(\d+)\.([^}]+)\}\}", re.IGNORECASE)


# ============================================================================
# TOKEN HELPERS
# ============================================================================


def count_tokens(text: str) -> int:
    """Approximate token count using len(text) // 4."""
    if not text:
        return 0
    return len(text) // 4


def truncate_to_budget(text: str, tool_name: str) -> str:
    """
    Truncate text to fit within the token budget for a given tool type.
    Appends [truncated] marker when content is cut.
    """
    budget = TOKEN_BUDGETS.get(tool_name, DEFAULT_TOKEN_BUDGET)
    max_chars = budget * 4  # Reverse the token approximation

    if not text or len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # Try to break at a word boundary
    last_space = truncated.rfind(" ", max(0, max_chars - 100))
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]

    return truncated + "\n[truncated]"


# Threshold above which we condense rather than hard-truncate (chars)
CONDENSE_THRESHOLD_CHARS = 3000


def condense_result(text: str, tool_name: str) -> str:
    """
    For large results, return a head + tail slice with a marker in the middle.
    Preserves the start (usually the most important) and the end (conclusion).
    Falls back to truncate_to_budget for very large results.
    """
    if not text or len(text) <= CONDENSE_THRESHOLD_CHARS:
        return text

    # Tools where we want a proper budget truncation, not head+tail
    hard_truncate_tools = {"finance_fetcher", "weather_fetcher", "google_search"}
    if tool_name in hard_truncate_tools:
        return truncate_to_budget(text, tool_name)

    head_chars = 1800
    tail_chars = 400
    omitted = len(text) - head_chars - tail_chars

    if omitted <= 0:
        return text

    head = text[:head_chars].rstrip()
    tail = text[-tail_chars:].lstrip()
    return f"{head}\n\n[... {omitted} chars condensed ...]\n\n{tail}"


# ============================================================================
# RESULT SERIALIZATION
# ============================================================================


def safe_serialize(obj: Any) -> str:
    """Safe JSON dump for logs / prompts."""
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _unwrap_result(data: Any) -> Any:
    """Unwrap common result container patterns."""
    if not isinstance(data, dict):
        return data
    if "result" in data and len(data) <= 4:
        return data["result"]
    if "results" in data and len(data) <= 4:
        return data["results"]
    return data


def _format_result_text(result_data: Any) -> str:
    """Convert a result payload to a readable string for the synthesis prompt."""
    if result_data is None:
        return ""

    unwrapped = _unwrap_result(result_data)

    if isinstance(unwrapped, str):
        return unwrapped
    if isinstance(unwrapped, (dict, list)):
        return safe_serialize(unwrapped)
    return str(unwrapped)


# ============================================================================
# NULL / FAILURE HANDLING (Problem 2)
# ============================================================================


def _is_result_unavailable(trace_entry: Optional[Dict]) -> bool:
    """Check if a trace entry represents an unavailable/failed result."""
    if trace_entry is None:
        return True
    status = trace_entry.get("status")
    if status in ("error", "skipped"):
        return True
    result = trace_entry.get("result")
    if result is None:
        return True
    # Check for empty result containers
    if isinstance(result, dict):
        if result.get("status") == "error":
            return True
        inner = _unwrap_result(result)
        if inner is None or inner == "" or inner == [] or inner == {}:
            return True
    if isinstance(result, str) and not result.strip():
        return True
    return False


def _unavailable_message(idx: int, trace_entry: Optional[Dict] = None) -> str:
    """Generate an UNAVAILABLE message for a failed/missing step."""
    if trace_entry and trace_entry.get("status") == "skipped":
        reason = "node was skipped due to upstream failure"
    elif trace_entry and trace_entry.get("status") == "error":
        error = ""
        result = trace_entry.get("result")
        if isinstance(result, dict):
            error = result.get("error", "")
        reason = f"node failed: {error}" if error else "node failed or returned no data"
    else:
        reason = "node failed or returned no data"

    return f"[STEP {idx} result: UNAVAILABLE - {reason}]"


# ============================================================================
# LABELED PROMPT BUILDER (Problem 1 + 2 + 6)
# ============================================================================


def resolve_llm_prompt(
    prompt: str,
    trace: List[Optional[Dict[str, Any]]],
    nodes: List[Dict[str, Any]],
) -> str:
    """
    Build a labeled synthesis prompt for llm_caller nodes.

    Transforms flat {{STEPS.N}} references into labeled, structured blocks:
        [STEP N - tool_name: thought]
        <result>...content...</result>

    Also handles:
      - Null/failure fallback with UNAVAILABLE markers (Problem 2)
      - Pipe syntax {{STEPS.N | default: "msg"}} (Problem 2)
      - Token budget truncation per tool (Problem 6)
      - Anti-fabrication system instruction (Problem 1)
    """

    # Step 1: Handle pipe syntax {{STEPS.N | default: "msg"}} FIRST
    def replace_pipe(m: re.Match) -> str:
        idx = int(m.group(1))
        default_msg = m.group(2)

        if idx < 0 or idx >= len(trace):
            logger.warning(f"Template references out-of-range STEPS.{idx}")
            return default_msg

        entry = trace[idx]
        if _is_result_unavailable(entry):
            logger.warning(f"Null substitution for STEPS.{idx} — using custom default")
            return default_msg

        # Build labeled block
        return _build_labeled_block(idx, entry, nodes)

    prompt = STEP_REF_PIPE.sub(replace_pipe, prompt)

    # Step 2: Handle bare {{STEPS.N}} references
    def replace_bare(m: re.Match) -> str:
        idx = int(m.group(1))

        if idx < 0 or idx >= len(trace):
            logger.warning(f"Template references out-of-range STEPS.{idx}")
            return _unavailable_message(idx)

        entry = trace[idx]
        if _is_result_unavailable(entry):
            logger.warning(f"Null substitution for STEPS.{idx} — result unavailable")
            return _unavailable_message(idx, entry)

        return _build_labeled_block(idx, entry, nodes)

    prompt = STEP_REF_BARE.sub(replace_bare, prompt)

    # Step 3: Handle dotted path {{STEPS.N.path}} references
    def replace_dot(m: re.Match) -> str:
        idx = int(m.group(1))
        path = m.group(2)

        if idx < 0 or idx >= len(trace):
            return ""

        entry = trace[idx]
        if entry is None:
            logger.warning(f"Null substitution for STEPS.{idx}.{path}")
            return ""

        data = entry.get("result")
        value = _deep_get(data, path)
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return safe_serialize(value)
        return str(value)

    prompt = STEP_REF_DOT.sub(replace_dot, prompt)

    # Step 4: Prepend anti-fabrication instruction only if result tags are present
    if "<result>" in prompt:
        prompt = SYNTHESIS_SYSTEM_INSTRUCTION + prompt

    return prompt


def _build_labeled_block(
    idx: int,
    trace_entry: Dict[str, Any],
    nodes: List[Dict[str, Any]],
) -> str:
    """
    Build a labeled block for a single step result:
        [STEP N - tool_name: thought]
        <result>...content...</result>
    """
    # Get tool name and thought from the node definition
    tool_name = "unknown"
    thought = "Executing tool..."

    if idx < len(nodes):
        node = nodes[idx]
        tool_name = node.get("tool", "unknown")
        thought = node.get("thought", "Executing tool...")
    elif trace_entry:
        tool_name = trace_entry.get("tool", "unknown")

    # Smart response extraction:
    # For text-rich tools, prefer the 'response' field over the full dict.
    # This cuts noise and saves context window space for downstream nodes.
    TEXT_RICH_TOOLS = {
        "llm_caller", "code_agent", "code_assistant", "sub_agent",
        "url_reader", "news_fetcher",
    }
    result_data = trace_entry.get("result")
    if tool_name in TEXT_RICH_TOOLS and isinstance(result_data, dict):
        preferred = result_data.get("response") or result_data.get("content") or result_data.get("summary")
        if preferred and isinstance(preferred, str) and len(preferred) > 20:
            result_text = preferred  # use the clean text form directly
        else:
            result_text = _format_result_text(result_data)
    else:
        result_text = _format_result_text(result_data)

    # Apply context condenser (head+tail) for large results, then budget truncation
    result_text = condense_result(result_text, tool_name)
    result_text = truncate_to_budget(result_text, tool_name)

    header = f"[STEP {idx} - {tool_name}: {thought}]"
    return f"{header}\n<result>{result_text}</result>"


# ============================================================================
# DOTTED PATH RESOLVER (carried over from orchestrator)
# ============================================================================


def _deep_get(obj: Any, path: str) -> Any:
    """
    Resolve dotted / indexed paths like `result.0.link`
    against tool output.
    """
    obj = _unwrap_result(obj)
    path = path.replace("[", ".").replace("]", "")
    parts = [p for p in path.split(".") if p]

    cur: Any = obj
    for key in parts:
        if isinstance(cur, dict):
            if key in cur:
                cur = cur[key]
            else:
                return None
        elif isinstance(cur, list):
            if key.isdigit():
                i = int(key)
                if 0 <= i < len(cur):
                    cur = cur[i]
                else:
                    return None
            else:
                return None
        else:
            return None
    return cur


# ============================================================================
# GENERAL STEP REFERENCE RESOLVER (for non-llm tools)
# ============================================================================


def resolve_step_reference(
    value: str, trace: List[Optional[Dict[str, Any]]]
) -> Any:
    """
    Resolve a bare {{STEPS.N}} reference to the raw result object.
    Used for non-llm tools that need the actual data structure.
    Returns the original string if no match.
    Returns None with warning if result is unavailable.
    """
    m = re.match(r"^\s*\{\{\s*STEPS\.(\d+)\s*\}\}\s*$", value, re.IGNORECASE)
    if not m:
        return value

    idx = int(m.group(1))
    if idx < 0 or idx >= len(trace) or trace[idx] is None:
        logger.warning(f"Null substitution for STEPS.{idx} in step reference")
        return None

    entry = trace[idx]
    if _is_result_unavailable(entry):
        logger.warning(f"Unavailable result for STEPS.{idx} in step reference")
        return None

    raw = entry.get("result")
    return _unwrap_result(raw)
