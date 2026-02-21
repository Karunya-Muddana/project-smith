"""
Fabrication Guard — Enforcement Layer
---------------------------------------
Detects and redacts fabricated numeric data in LLM synthesis responses. (Problem 4)

Replaces the previous warning-only system with active enforcement:
  1. Ground truth registry populated from finance/weather tool results
  2. Numeric extraction and comparison with ±2% tolerance
  3. Redaction of fabricated numbers
  4. Fabrication report and confidence scoring
"""

import re
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("smith.fabrication_guard")


# ============================================================================
# GROUND TRUTH REGISTRY
# ============================================================================


class GroundTruthRegistry:
    """
    Collects verified numeric values from data tool results during execution.
    Used as the reference for detecting fabricated numbers in LLM output.
    """

    def __init__(self):
        self._numbers: Dict[str, float] = {}  # label -> value
        self._all_values: Set[float] = set()

    def register_finance(self, trace_entry: Dict[str, Any]) -> None:
        """Extract verified numbers from a finance_fetcher result."""
        result = trace_entry.get("result", {})
        if isinstance(result, dict) and result.get("status") == "success":
            inner = result
        elif isinstance(result, dict) and "result" in result:
            inner = result["result"]
            if isinstance(inner, dict) and inner.get("status") == "success":
                pass  # inner is already the right dict
            elif isinstance(inner, dict):
                pass
            else:
                return
        else:
            return

        # Extract price
        price = inner.get("price")
        if price is not None:
            try:
                val = float(price)
                symbol = inner.get("symbol", "unknown")
                self._numbers[f"finance:{symbol}:price"] = val
                self._all_values.add(val)
                logger.debug(f"Ground truth registered: {symbol} price = {val}")
            except (ValueError, TypeError):
                pass

        # Extract from history if present
        history = inner.get("history", [])
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict):
                    close = item.get("close")
                    if close is not None:
                        try:
                            self._all_values.add(float(close))
                        except (ValueError, TypeError):
                            pass

    def register_weather(self, trace_entry: Dict[str, Any]) -> None:
        """Extract verified numbers from a weather_fetcher result."""
        result = trace_entry.get("result", {})
        if isinstance(result, dict) and "result" in result:
            inner = result.get("result", result)
        else:
            inner = result

        if not isinstance(inner, dict):
            return

        for key in ("temperature", "humidity", "wind_speed"):
            val = inner.get(key)
            if val is not None:
                try:
                    fval = float(val)
                    city = inner.get("city", "unknown")
                    self._numbers[f"weather:{city}:{key}"] = fval
                    self._all_values.add(fval)
                    logger.debug(f"Ground truth registered: {city} {key} = {fval}")
                except (ValueError, TypeError):
                    pass

    def register_from_trace(self, trace: List[Optional[Dict[str, Any]]]) -> None:
        """Scan full trace and register all data tool results."""
        for entry in trace:
            if entry is None:
                continue
            tool = entry.get("tool", "")
            if tool == "finance_fetcher":
                self.register_finance(entry)
            elif tool == "weather_fetcher":
                self.register_weather(entry)

    def get_all_values(self) -> Set[float]:
        """Return all registered ground truth numeric values."""
        return self._all_values.copy()

    def get_labeled_values(self) -> Dict[str, float]:
        """Return labeled ground truth values."""
        return self._numbers.copy()


# ============================================================================
# NUMERIC EXTRACTION
# ============================================================================

# Patterns to extract numbers from text
_NUMBER_PATTERNS = [
    # Dollar amounts: $16.45, $1,234.56
    (r"\$[\d,]+\.?\d*", lambda m: float(m.group().replace("$", "").replace(",", ""))),
    # Percentages: 45.2%, 3%
    (r"\d+\.?\d*%", lambda m: float(m.group().replace("%", ""))),
    # Decimal numbers (standalone, not part of dates/versions): 16.45, 629.3
    (r"(?<!\d[./])\b\d+\.\d+\b(?![./]\d)", lambda m: float(m.group())),
    # Integers in context of prices/values (preceded by currency or value words)
    (r"(?:price|value|cost|worth|at|₹|€|£)\s*(\d[\d,]*)", lambda m: float(m.group(1).replace(",", ""))),
]


def extract_numbers(text: str) -> List[Tuple[float, str]]:
    """
    Extract all numeric values from text along with their context.
    Returns list of (value, surrounding_context) tuples.
    """
    numbers = []
    seen = set()

    for pattern, extractor in _NUMBER_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                value = extractor(match)
                
                # Skip trivially common numbers (0, 1, 2, etc.)
                if value < 3 and value == int(value):
                    continue
                # Skip year-like numbers
                if 1900 <= value <= 2100 and value == int(value):
                    continue

                # Get surrounding context (±30 chars)
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end].strip()

                # Deduplicate by value
                if value not in seen:
                    numbers.append((value, context))
                    seen.add(value)

            except (ValueError, TypeError):
                continue

    return numbers


# ============================================================================
# FABRICATION CHECK & REDACTION
# ============================================================================


def _is_within_tolerance(value: float, ground_truth: Set[float], tolerance: float = 0.02) -> bool:
    """
    Check if a value matches any ground truth number within ±tolerance (default 2%).
    """
    for gt in ground_truth:
        if gt == 0:
            if value == 0:
                return True
            continue
        if abs(value - gt) / abs(gt) <= tolerance:
            return True
    return False


def check_and_redact(
    response_text: str,
    ground_truth: GroundTruthRegistry,
) -> Dict[str, Any]:
    """
    Check LLM response for fabricated numeric data and redact it.

    Args:
        response_text: The LLM's synthesis response text
        ground_truth: Registry of verified numbers from data tools

    Returns:
        {
            "redacted_text": str,       # Response with fabrications replaced
            "fabrication_report": {
                "total_numbers": int,
                "verified": int,
                "redacted": int,
                "redacted_details": [{"value": float, "context": str, "reason": str}],
            },
            "confidence": "high" | "medium" | "low_confidence",
        }
    """
    gt_values = ground_truth.get_all_values()

    # If no ground truth data, we can't verify — pass through with warning
    if not gt_values:
        return {
            "redacted_text": response_text,
            "fabrication_report": {
                "total_numbers": 0,
                "verified": 0,
                "redacted": 0,
                "redacted_details": [],
                "note": "No ground truth data available for verification",
            },
            "confidence": "medium",
        }

    # Extract numbers from response
    numbers = extract_numbers(response_text)

    if not numbers:
        return {
            "redacted_text": response_text,
            "fabrication_report": {
                "total_numbers": 0,
                "verified": 0,
                "redacted": 0,
                "redacted_details": [],
            },
            "confidence": "high",
        }

    # Check each number against ground truth
    redacted_text = response_text
    verified_count = 0
    redacted_details = []

    for value, context in numbers:
        if _is_within_tolerance(value, gt_values):
            verified_count += 1
        else:
            # This number is fabricated — redact it
            redacted_details.append({
                "value": value,
                "context": context,
                "reason": "Number not found in any upstream tool result (±2% tolerance)",
            })

            # Replace the number in the text
            # Handle dollar amounts
            dollar_pattern = re.compile(
                r"\$" + re.escape(f"{value:,.2f}".rstrip("0").rstrip("."))
                + r"|"
                + r"\$" + re.escape(f"{value:.2f}")
                + r"|"
                + r"\$" + re.escape(str(value))
            )
            redacted_text = dollar_pattern.sub("[REDACTED - verify manually]", redacted_text)

            # Handle the plain number
            plain_patterns = [
                re.escape(f"{value:.2f}"),
                re.escape(f"{value:.1f}"),
                re.escape(str(value)),
            ]
            for pp in plain_patterns:
                redacted_text = re.sub(
                    r"(?<!\d)" + pp + r"(?!\d)",
                    "[REDACTED - verify manually]",
                    redacted_text,
                )

    total = len(numbers)
    redacted_count = len(redacted_details)

    # Determine confidence level
    if total > 0 and redacted_count / total > 0.3:
        confidence = "low_confidence"
        logger.warning(
            f"Fabrication guard: {redacted_count}/{total} numbers fabricated "
            f"(>{30}%) — marking as low_confidence"
        )
    elif redacted_count > 0:
        confidence = "medium"
        logger.warning(
            f"Fabrication guard: {redacted_count}/{total} numbers redacted"
        )
    else:
        confidence = "high"

    return {
        "redacted_text": redacted_text,
        "fabrication_report": {
            "total_numbers": total,
            "verified": verified_count,
            "redacted": redacted_count,
            "redacted_details": redacted_details,
        },
        "confidence": confidence,
    }
