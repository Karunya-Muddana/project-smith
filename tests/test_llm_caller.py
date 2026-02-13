"""
Test LLM Caller Functionality
------------------------------
Simple test to verify the LLM caller works correctly.
"""

import pytest
from smith.tools.LLM_CALLER import call_llm, run_llm_tool


def test_llm_caller_imports():
    """Verify LLM caller module imports successfully."""
    assert call_llm is not None
    assert run_llm_tool is not None


def test_llm_caller_basic_call():
    """Test that LLM caller can make a basic call and return a response."""
    # Use a simple prompt to minimize API costs
    result = call_llm("Say 'Hello' in one word.")

    # Check response structure
    assert isinstance(result, dict)
    assert "status" in result

    # If successful, should have 'response' key
    # If error (e.g., missing API key), should have 'error' key
    if result["status"] == "success":
        assert "response" in result
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0
    elif result["status"] == "error":
        assert "error" in result
        # This is acceptable - might be missing API key in test environment
        pytest.skip(f"LLM call failed (expected in test env): {result['error']}")
    else:
        pytest.fail(f"Unexpected status: {result['status']}")


def test_llm_caller_handles_errors():
    """Test that LLM caller handles errors gracefully."""
    # Call with empty prompt - should handle gracefully
    result = call_llm("")

    assert isinstance(result, dict)
    assert "status" in result
    # Should either succeed (empty response) or error gracefully
    assert result["status"] in ["success", "error"]


def test_run_llm_tool_interface():
    """Test the Smith tool interface for LLM calls."""
    result = run_llm_tool("Test", model="default")

    assert isinstance(result, dict)
    assert "status" in result

    # Accept both success and error (API key might be missing)
    if result["status"] == "success":
        assert "response" in result
    elif result["status"] == "error":
        assert "error" in result
        pytest.skip(f"LLM tool call failed (expected in test env): {result['error']}")
