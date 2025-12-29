import pytest
from smith.planner import plan_task


def test_planner_validates_basic_schema(mock_db, mock_llm):
    """
    Test that the planner correctly accepts a valid DAG from the LLM.
    """
    valid_dag = {
        "status": "success",
        "nodes": [
            {
                "id": 0,
                "tool": "test_tool",
                "function": "fn",
                "inputs": {"x": 1},
                "depends_on": [],
                "retry": 1,
                "timeout": 10,
                "on_fail": "continue",
                "metadata": {"purpose": "test"},
            }
        ],
        "final_output_node": 0,
    }

    # Mock LLM to return this web-valid DAG
    mock_llm.return_value = {"status": "success", "response": ""}
    # effectively we need the _call_llm_for_plan to return this.
    # But plan_task internally calls _call_llm_for_plan.

    # We'll patch the internal _call_llm helper or just the LLM_CALLER response
    # The current mock_llm fixture mocks smith.tools.LLM_CALLER.call_llm
    # The planner calls that.

    # However, the planner expects the LLM to return a STRING (JSON string).
    # So the mock return value should be:
    import json

    mock_llm.return_value = {"status": "success", "response": json.dumps(valid_dag)}

    # We also need a registry that contains "test_tool"
    mock_db.read_many.return_value = {
        "status": "success",
        "data": [
            {
                "name": "test_tool",
                "function": "fn",
                "parameters": {"properties": {"x": {}}, "required": []},
            }
        ],
    }

    result = plan_task("do test", [])

    assert result["status"] == "success"
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["tool"] == "test_tool"


def test_planner_rejects_invalid_tool(mock_db, mock_llm):
    """
    Test that the planner validation catches non-existent tools.
    """
    bad_dag = {
        "status": "success",
        "nodes": [
            {
                "id": 0,
                "tool": "fake_tool",  # <--- Not in registry
                "function": "fn",
                "inputs": {},
                "depends_on": [],
                "retry": 1,
                "timeout": 10,
                "on_fail": "continue",
                "metadata": {"purpose": "test"},
            }
        ],
        "final_output_node": 0,
    }

    import json

    mock_llm.return_value = {"status": "success", "response": json.dumps(bad_dag)}

    # Empty registry
    mock_db.read_many.return_value = {"status": "success", "data": []}

    result = plan_task("do bad", [])

    # Should be an error or fallback, but definitely not success
    # If validation fails, it might retry or return error
    if result["status"] == "success":
        # If it returns success, it means validation failed to catch it?
        # Or maybe our mock logic bypassed it?
        # plan_task validates against the registry index.
        # If fake_tool not in registry, _validate_plan returns ok=False.
        # Then it loops to retry or returns error.
        pytest.fail("Planner should have rejected the plan with unknown tool")

    assert result["status"] == "error"
