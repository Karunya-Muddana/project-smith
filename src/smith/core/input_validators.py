"""
Input Validators — Upstream Shape Validation
----------------------------------------------
Validates that interpolated inputs match the expected schema
for each tool BEFORE execution. (Problem 3)

Tools register their input schemas in TOOL_INPUT_SCHEMAS.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.input_validators")


# ============================================================================
# INPUT SCHEMA REGISTRY
# ============================================================================
#
# Each entry maps tool_name -> {param_name -> validator_function}
# Validator functions take (value) and return (valid: bool, reason: str)
#


def _validate_articles_input(value: Any) -> Dict[str, Any]:
    """
    Validate the 'articles' input for news_fetcher.
    Must be a non-empty list of dicts with at least a 'url' or 'link' key.
    Strings (unresolved templates) are skipped — they haven't been interpolated yet.
    """
    # If it's still a string (template not resolved), skip validation
    if isinstance(value, str):
        return {"valid": True}

    # None is acceptable — news_fetcher handles it with DDG fallback
    if value is None:
        return {"valid": True}

    # Must be a list
    if not isinstance(value, list):
        return {
            "valid": False,
            "reason": (
                f"invalid_input: upstream shape mismatch — "
                f"'articles' must be a list, got {type(value).__name__}"
            ),
        }

    # Must be non-empty
    if len(value) == 0:
        return {
            "valid": False,
            "reason": (
                "invalid_input: upstream shape mismatch — "
                "'articles' is an empty list (upstream may have returned no results)"
            ),
        }

    # Each item must be a dict with 'url' or 'link'
    valid_count = 0
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        if "url" in item or "link" in item:
            valid_count += 1

    if valid_count == 0:
        return {
            "valid": False,
            "reason": (
                "invalid_input: upstream shape mismatch — "
                "'articles' contains no dicts with 'url' or 'link' key"
            ),
        }

    return {"valid": True}


def _validate_url_input(value: Any) -> Dict[str, Any]:
    """Validate 'url' input for url_reader."""
    if not isinstance(value, str):
        return {
            "valid": False,
            "reason": f"invalid_input: 'url' must be a string, got {type(value).__name__}",
        }
    if not value.startswith(("http://", "https://")):
        return {
            "valid": False,
            "reason": f"invalid_input: 'url' must start with http:// or https://, got '{value[:50]}'",
        }
    return {"valid": True}


def _validate_symbol_input(value: Any) -> Dict[str, Any]:
    """Validate 'symbol' input for finance_fetcher."""
    if not isinstance(value, str) or not value.strip():
        return {
            "valid": False,
            "reason": "invalid_input: 'symbol' must be a non-empty string",
        }
    return {"valid": True}


# Schema registry: tool_name -> {param_name -> validator_fn}
TOOL_INPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "news_fetcher": {
        "articles": _validate_articles_input,
    },
    "url_reader": {
        "url": _validate_url_input,
    },
    "finance_fetcher": {
        "symbol": _validate_symbol_input,
    },
}


# ============================================================================
# MAIN VALIDATION FUNCTION
# ============================================================================


def validate_inputs(tool_name: str, resolved_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that resolved (interpolated) inputs match the expected schema
    for the given tool.

    Args:
        tool_name: Name of the tool to validate for
        resolved_inputs: The fully resolved input dict (after template interpolation)

    Returns:
        {"valid": True} or {"valid": False, "reason": "invalid_input: ..."}
    """
    schema = TOOL_INPUT_SCHEMAS.get(tool_name)
    if not schema:
        # No schema registered — pass through
        return {"valid": True}

    for param_name, validator_fn in schema.items():
        if param_name not in resolved_inputs:
            continue  # Optional param not provided — skip

        value = resolved_inputs[param_name]
        result = validator_fn(value)

        if not result.get("valid", True):
            reason = result.get("reason", f"invalid_input: validation failed for '{param_name}'")
            logger.warning(
                f"Input validation failed for {tool_name}.{param_name}: {reason}"
            )
            return {"valid": False, "reason": reason}

    return {"valid": True}
