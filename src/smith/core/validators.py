"""
Tool Authority & Output Validators
------------------------------------
Prevents LLM from fabricating numeric data or factual claims.
Enforces tool domain boundaries.
"""

from typing import Dict, Any
import re

# Domain classifications
DOMAIN_DATA = "data"
DOMAIN_REASONING = "reasoning"
DOMAIN_COMPUTATION = "computation"
DOMAIN_SYSTEM = "system"


def validate_tool_authority(
    tool_meta: Dict, inputs: Dict, outputs: Dict
) -> Dict[str, Any]:
    """
    Validate that a tool's output respects its authority domain.

    Args:
        tool_meta: Tool metadata from registry (includes domain, prohibited_outputs)
        inputs: Tool inputs
        outputs: Tool outputs

    Returns:
        {
            "valid": bool,
            "quality": "correct" | "degraded" | "violated",
            "violations": List[str]
        }
    """
    violations = []
    domain = tool_meta.get("domain", "unknown")
    tool_name = tool_meta.get("name", "unknown")
    prohibited = tool_meta.get("prohibited_outputs", [])

    # If tool failed, skip validation
    if outputs.get("status") != "success":
        return {"valid": True, "quality": "failed", "violations": []}

    response_text = str(outputs.get("response", ""))

    # Check for prohibited output types
    if domain == DOMAIN_REASONING:
        # LLM should NOT produce:
        # 1. Numeric claims (prices, percentages, counts)
        # 2. Factual assertions about real-world data
        # 3. Timestamps or dates as facts

        if "numeric_data" in prohibited:
            if contains_numeric_claims(response_text):
                violations.append(f"LLM fabricated numeric data: {tool_name}")

        if "factual_claims" in prohibited:
            if contains_factual_assertions(response_text, inputs):
                violations.append(
                    f"LLM made factual claims without data source: {tool_name}"
                )

        if "real_time_data" in prohibited:
            if contains_time_references(response_text):
                violations.append(f"LLM referenced real-time data: {tool_name}")

    # Determine quality
    if violations:
        quality = "violated" if len(violations) > 1 else "degraded"
    else:
        quality = "correct"

    return {"valid": len(violations) == 0, "quality": quality, "violations": violations}


def contains_numeric_claims(text: str) -> bool:
    """Detect if text contains numeric claims (prices, percentages, trends)"""
    # Patterns for numeric claims
    patterns = [
        r"\$[\d,]+\.?\d*",  # Dollar amounts
        r"\d+\.?\d*%",  # Percentages
        r"(?:increased|decreased|rose|fell|dropped).*?\d+",  # Trend claims with numbers
        r"\d+\s*(?:points|basis points|percent)",  # Market metrics
        r"(?:price|value|cost).*?\d+",  # Price statements
    ]

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def contains_factual_assertions(text: str, inputs: Dict) -> bool:
    """Detect unsupported factual claims — only for data-fetching contexts."""
    # If prompt contains references to steps, it's synthesis (allowed)
    prompt = inputs.get("prompt", "")
    if re.search(r"step\s+\d+|from\s+step|based\s+on", prompt, re.IGNORECASE):
        return False  # This is synthesis, not fabrication

    # Only flag if the prompt itself was asking for real-world data
    # (not for writing, analysis, or explanation)
    data_request_patterns = [
        r"(?:what is|get|find|fetch|show me).*?(?:price|stock|weather|rate|score)",
        r"(?:how much|how many).*?(?:cost|worth|value)",
    ]
    prompt_is_data_request = any(
        re.search(p, prompt, re.IGNORECASE) for p in data_request_patterns
    )
    if not prompt_is_data_request:
        # This is a writing/analysis task — don't penalise factual prose
        return False

    # Only check time-specific claims in confirmed data-request context
    patterns = [
        r"(?:currently|as of today)\s+(?:the|a)\s+(?:price|rate|value|stock)",
        r"(?:is|are)\s+(?:priced|valued|trading)\s+at\s+\$?[\d,.]+",
    ]

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def contains_time_references(text: str) -> bool:
    """Detect real-time financial/weather data references — NOT general writing."""
    # Only flag if talking about real-time price/weather/stock data, not general 'recent research'
    patterns = [
        r"as of.*?(?:today|right now|this moment)",
        r"current.*?(?:price|stock price|temperature|weather reading)",
        r"(?:live|real-time)\s+(?:price|stock|data|feed)",
    ]

    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def check_fabrication_risk(tool_meta: Dict, inputs: Dict) -> Dict[str, Any]:
    """
    Predict if LLM is being asked to produce data it shouldn't.

    Called BEFORE execution to warn about risky queries.
    """
    tool_name = tool_meta.get("name")
    domain = tool_meta.get("domain")

    if tool_name != "llm_caller" or domain != DOMAIN_REASONING:
        return {"risk": "none"}

    prompt = inputs.get("prompt", "")

    # Risk indicators
    risks = []

    if re.search(
        r"(?:what is|get|find).*?(?:price|stock|weather)", prompt, re.IGNORECASE
    ):
        risks.append("LLM asked for real-time data")

    if re.search(r"calculate|compute|trend", prompt, re.IGNORECASE):
        # Check if it references previous steps (OK) or asks for new computation (risky)
        if not re.search(r"step\s+\d+|from\s+step", prompt, re.IGNORECASE):
            risks.append("LLM asked to compute without data")

    if risks:
        return {
            "risk": "high",
            "reasons": risks,
            "suggestion": "Consider using data/computation tools instead",
        }

    return {"risk": "none"}
