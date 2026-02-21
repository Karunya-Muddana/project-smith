"""
Test DAG Failure Handling
--------------------------
Tests for the on_fail policy logic in the orchestrator's DAG execution.

These tests mock the planner and tool execution to verify:
1. on_fail: "continue"  → downstream nodes still execute
2. on_fail: "halt"      → downstream nodes are skipped
3. Partial-failure trace entries are correctly generated
4. Multi-level cascades respect per-node policy
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: build a minimal DAG node
# ---------------------------------------------------------------------------

def _node(id, tool, function, depends_on=None, on_fail="continue", inputs=None):
    """Build a minimal DAG node dict for testing."""
    return {
        "id": id,
        "thought": f"Test step {id}",
        "tool": tool,
        "function": function,
        "inputs": inputs or {},
        "depends_on": depends_on or [],
        "retry": 0,
        "on_fail": on_fail,
        "timeout": 10,
    }


# ---------------------------------------------------------------------------
# Helper: collect orchestrator events from a mocked plan
# ---------------------------------------------------------------------------

def _run_orchestrator_with_plan(plan, tool_results):
    """
    Run the orchestrator with a pre-built plan and mocked tool results.

    Args:
        plan: dict with "status", "nodes", "final_output_node"
        tool_results: dict mapping (tool_name, step_index) -> return value

    Returns:
        list of events yielded by the orchestrator
    """
    from smith.core.orchestrator import smith_orchestrator

    # Mock planner to return our plan directly
    with patch("smith.core.orchestrator.planner") as mock_planner, \
         patch("smith.core.orchestrator.tool_loader") as mock_loader, \
         patch("smith.core.orchestrator.LLM_CALLER") as mock_llm:

        mock_planner.plan_task.return_value = plan

        # Tool loader returns a function that looks up our result map
        def fake_load(module, fn_name):
            def fake_tool(**kwargs):
                # Find matching result by function name
                for (tool, idx), result in tool_results.items():
                    if tool == fn_name:
                        return result
                return {"status": "error", "error": "No mock result"}
            return fake_tool

        mock_loader.load_tool_function.side_effect = fake_load

        # Final LLM call returns a simple summary
        mock_llm.call_llm.return_value = {
            "status": "success",
            "response": "Test final answer",
        }

        events = list(smith_orchestrator("test query", require_approval=False))
    return events


# ---------------------------------------------------------------------------
# Helper: build registry mock
# ---------------------------------------------------------------------------

def _build_registry_entry(name, function):
    """Build a minimal tool registry entry."""
    return {
        "name": name,
        "function": function,
        "module": f"smith.tools.{name.upper()}",
        "dangerous": False,
        "domain": "data",
        "output_type": "factual",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }


MOCK_REGISTRY = [
    _build_registry_entry("tool_a", "run_tool_a"),
    _build_registry_entry("tool_b", "run_tool_b"),
    _build_registry_entry("tool_c", "run_tool_c"),
    _build_registry_entry("llm_caller", "call_llm"),
]


# ===========================================================================
# TESTS
# ===========================================================================


class TestOnFailContinue:
    """Test that on_fail: 'continue' lets downstream nodes execute."""

    def test_downstream_runs_despite_upstream_failure(self):
        """
        DAG: [0: tool_a (continue)] → [1: tool_b]
        Node 0 fails. Node 1 should still execute because node 0 has on_fail=continue.
        """
        plan = {
            "status": "success",
            "nodes": [
                _node(0, "tool_a", "run_tool_a", on_fail="continue"),
                _node(1, "tool_b", "run_tool_b", depends_on=[0]),
            ],
            "final_output_node": 1,
        }

        tool_results = {
            ("run_tool_a", 0): {"status": "error", "error": "HTTP 403 Forbidden"},
            ("run_tool_b", 1): {"status": "success", "result": {"data": "from_b"}},
        }

        with patch("smith.core.orchestrator.registry") as mock_reg:
            mock_reg.get_tools_registry.return_value = MOCK_REGISTRY

            events = _run_orchestrator_with_plan(plan, tool_results)

        # Find step_complete events
        step_completes = [e for e in events if e.get("type") == "step_complete"]

        # Node 0 should have completed (with error)
        node0_events = [e for e in step_completes if e.get("step_index") == 0]
        assert len(node0_events) == 1
        assert node0_events[0]["status"] == "error"

        # Node 1 should have completed (with success) — NOT skipped
        node1_events = [e for e in step_completes if e.get("step_index") == 1]
        assert len(node1_events) == 1
        assert node1_events[0]["status"] == "success"

        # There should be NO "skipped" status in the trace
        skipped_events = [
            e for e in events
            if e.get("type") == "step_complete" and e.get("status") == "skipped"
        ]
        assert len(skipped_events) == 0


class TestOnFailHalt:
    """Test that on_fail: 'halt' skips downstream nodes."""

    def test_downstream_skipped_on_upstream_halt_failure(self):
        """
        DAG: [0: tool_a (halt)] → [1: tool_b]
        Node 0 fails with on_fail=halt. Node 1 should be skipped.
        """
        plan = {
            "status": "success",
            "nodes": [
                _node(0, "tool_a", "run_tool_a", on_fail="halt"),
                _node(1, "tool_b", "run_tool_b", depends_on=[0]),
            ],
            "final_output_node": 1,
        }

        tool_results = {
            ("run_tool_a", 0): {"status": "error", "error": "HTTP 403 Forbidden"},
            ("run_tool_b", 1): {"status": "success", "result": {"data": "from_b"}},
        }

        with patch("smith.core.orchestrator.registry") as mock_reg:
            mock_reg.get_tools_registry.return_value = MOCK_REGISTRY

            events = _run_orchestrator_with_plan(plan, tool_results)

        # Node 0 should have completed with error
        step_completes = [e for e in events if e.get("type") == "step_complete"]
        node0_events = [e for e in step_completes if e.get("step_index") == 0]
        assert len(node0_events) == 1
        assert node0_events[0]["status"] == "error"

        # Node 1 should NOT have a step_complete event (it was skipped before submission)
        node1_complete = [e for e in step_completes if e.get("step_index") == 1]
        assert len(node1_complete) == 0


class TestMultiLevelCascade:
    """Test cascade behavior across multiple DAG levels."""

    def test_three_node_continue_cascade(self):
        """
        DAG: [0: tool_a (continue)] → [1: tool_b (continue)] → [2: tool_c]
        Node 0 fails. Nodes 1 and 2 should still execute.
        """
        plan = {
            "status": "success",
            "nodes": [
                _node(0, "tool_a", "run_tool_a", on_fail="continue"),
                _node(1, "tool_b", "run_tool_b", depends_on=[0], on_fail="continue"),
                _node(2, "tool_c", "run_tool_c", depends_on=[1]),
            ],
            "final_output_node": 2,
        }

        tool_results = {
            ("run_tool_a", 0): {"status": "error", "error": "Network timeout"},
            ("run_tool_b", 1): {"status": "success", "result": {"data": "partial"}},
            ("run_tool_c", 2): {"status": "success", "result": {"data": "final"}},
        }

        with patch("smith.core.orchestrator.registry") as mock_reg:
            mock_reg.get_tools_registry.return_value = MOCK_REGISTRY

            events = _run_orchestrator_with_plan(plan, tool_results)

        step_completes = [e for e in events if e.get("type") == "step_complete"]

        # All 3 nodes should have step_complete events
        assert len(step_completes) == 3

        # Node 0: error, Node 1: success, Node 2: success
        statuses = {e["step_index"]: e["status"] for e in step_completes}
        assert statuses[0] == "error"
        assert statuses[1] == "success"
        assert statuses[2] == "success"

    def test_halt_in_middle_stops_rest(self):
        """
        DAG: [0: tool_a (continue)] → [1: tool_b (halt)] → [2: tool_c]
        Node 0 succeeds. Node 1 fails with on_fail=halt. Node 2 should be skipped.
        """
        plan = {
            "status": "success",
            "nodes": [
                _node(0, "tool_a", "run_tool_a", on_fail="continue"),
                _node(1, "tool_b", "run_tool_b", depends_on=[0], on_fail="halt"),
                _node(2, "tool_c", "run_tool_c", depends_on=[1]),
            ],
            "final_output_node": 2,
        }

        tool_results = {
            ("run_tool_a", 0): {"status": "success", "result": {"data": "ok"}},
            ("run_tool_b", 1): {"status": "error", "error": "Critical failure"},
            ("run_tool_c", 2): {"status": "success", "result": {"data": "should not run"}},
        }

        with patch("smith.core.orchestrator.registry") as mock_reg:
            mock_reg.get_tools_registry.return_value = MOCK_REGISTRY

            events = _run_orchestrator_with_plan(plan, tool_results)

        step_completes = [e for e in events if e.get("type") == "step_complete"]

        # Node 0: success
        node0 = [e for e in step_completes if e.get("step_index") == 0]
        assert len(node0) == 1
        assert node0[0]["status"] == "success"

        # Node 1: error
        node1 = [e for e in step_completes if e.get("step_index") == 1]
        assert len(node1) == 1
        assert node1[0]["status"] == "error"

        # Node 2: should not have a step_complete (skipped)
        node2 = [e for e in step_completes if e.get("step_index") == 2]
        assert len(node2) == 0


class TestFinalAnswerAlwaysProduced:
    """Test that the final answer is always produced, even with failures."""

    def test_final_answer_on_all_failures(self):
        """
        Even when all steps fail, the orchestrator should still produce
        a final_answer event (not just an error event).
        """
        plan = {
            "status": "success",
            "nodes": [
                _node(0, "tool_a", "run_tool_a", on_fail="continue"),
            ],
            "final_output_node": 0,
        }

        tool_results = {
            ("run_tool_a", 0): {"status": "error", "error": "Total failure"},
        }

        with patch("smith.core.orchestrator.registry") as mock_reg:
            mock_reg.get_tools_registry.return_value = MOCK_REGISTRY

            events = _run_orchestrator_with_plan(plan, tool_results)

        # Should have a final_answer event
        final_events = [e for e in events if e.get("type") == "final_answer"]
        assert len(final_events) == 1
