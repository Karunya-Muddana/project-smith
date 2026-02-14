import sys
import logging
from unittest.mock import patch

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

# Mock everything BEFORE importing orchestrator if possible,
# but orchestrator imports modules.
# We will patch modules.

with (
    patch("smith.tools.DB_TOOLS.DBTools") as MockDB,
    patch("smith.tool_loader.load_tool_function") as MockLoader,
    patch("smith.tools.LLM_CALLER.call_llm") as MockLLM,
    patch("smith.planner.plan_task") as MockPlan,
):
    print("Mocks active.")

    # Setup Mocks
    db_instance = MockDB.return_value
    db_instance.read_many.return_value = {
        "status": "success",
        "data": [{"name": "test_tool", "module": "TEST_TOOL", "parameters": {}}],
    }

    MockPlan.return_value = {
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

    MockLoader.return_value = lambda **kwargs: {"status": "success", "result": kwargs}
    MockLLM.return_value = {"status": "success", "response": "FINAL"}

    # Import orchestrator
    from smith.core.orchestrator import smith_orchestrator, reset_services

    reset_services()
    try:
        print("Starting orchestrator...")
        gen = smith_orchestrator("test")
        events = list(gen)
        print(f"Events captured: {len(events)}")
        for i, e in enumerate(events):
            print(f"[{i}] {e.get('type')}: {e.get('message') or ''}")
            if e["type"] == "error":
                print(f"ERROR DETAILS: {e}")
            if e["type"] == "step_complete":
                print(f"Payload: {e.get('payload')}")
    except Exception as e:
        print(f"CRASH: {e}")
        import traceback

        traceback.print_exc()
