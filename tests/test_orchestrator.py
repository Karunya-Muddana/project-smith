import pytest

from smith.orchestrator import smith_orchestrator


def test_orchestrator_initialization_flow(mock_db, mock_llm):
    """Verifies the orchestrator initialization sequence."""

    # Run generator
    gen = smith_orchestrator("Hello")

    # 1. Status init
    evt = next(gen)
    assert evt["type"] == "status"
    assert "Initializing" in evt["message"]


def test_orchestrator_basic_dag_execution(mock_db, mock_llm, mock_loader):
    """
    Test a simple 1-step plan execution.
    We mock the PLANNER to return a valid DAG.
    """
    # 1. Mock Tools DB
    mock_db.read_many.return_value = {
        "status": "success",
        "data": [{"name": "test_tool", "module": "TEST_TOOL", "parameters": {}}],
    }

    # 2. Mock Planner
    dag = {
        "status": "success",
        "nodes": [
            {
                "id": 0,
                "tool": "test_tool",
                "function": "run_me",
                "inputs": {"arg": 1},
                "depends_on": [],
            }
        ],
        "final_output_node": 0,
    }

    with pytest.patch("smith.planner.plan_task", return_value=dag):
        events = list(smith_orchestrator("Run test tool"))

    # Verify sequence
    assert len(events) > 0

    # Check for execution steps
    step_start = next(e for e in events if e["type"] == "step_start")
    assert step_start["tool"] == "test_tool"

    step_complete = next(e for e in events if e["type"] == "step_complete")
    assert step_complete["status"] == "success"

    # Check final answer
    final = next(e for e in events if e["type"] == "final_answer")
    assert final["payload"]["response"] == "MOCK_RESPONSE"


def test_orchestrator_handles_planner_failure(mock_db):
    """Tests graceful exit if planner fails."""
    with pytest.patch(
        "smith.planner.plan_task",
        return_value={"status": "error", "error": "Planner failed"},
    ):
        events = list(smith_orchestrator("Fail me"))

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "Planner failed" in errors[0]["message"]
