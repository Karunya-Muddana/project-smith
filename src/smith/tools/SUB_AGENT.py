"""
SUB-AGENT Tool for Smith
Enables fractal task delegation by spawning child Smith instances.

Sub-agents can use ALL tools except sub_agent itself (prevents infinite recursion).
Execution is serialized via a semaphore to prevent API rate limit cascades.
"""

import threading
import time
from typing import Optional, Dict, Any
from smith.core.agent_state import get_state_manager, AgentStatus
from smith.config import config


# Maximum recursion depth for sub-agents
MAX_SUBAGENT_DEPTH = getattr(config, "max_subagent_depth", 3)

# Global semaphore: only 1 sub-agent runs at a time to avoid rate limit cascades
_sub_agent_semaphore = threading.Semaphore(1)


def run_sub_agent(
    task: str, parent_agent_id: Optional[str] = None, max_depth: Optional[int] = None
) -> Dict[str, Any]:
    """
    Spawn a sub-agent to handle a delegated task.

    The sub-agent runs a full orchestrator with access to ALL tools
    except sub_agent itself (to prevent infinite recursion).
    Execution is serialized to prevent API rate limit cascades.

    Args:
        task: The task description for the sub-agent
        parent_agent_id: ID of the parent agent (auto-detected if None)
        max_depth: Maximum recursion depth (uses config default if None)

    Returns:
        Dict with status and result from sub-agent
    """
    if not task:
        return {"status": "error", "error": "Task description is required"}

    # Get state manager
    state_manager = get_state_manager()

    # Determine parent and depth
    if parent_agent_id is None:
        parent_agent_id = getattr(config, "_current_agent_id", None)

    # Check depth limit
    max_allowed_depth = max_depth if max_depth is not None else MAX_SUBAGENT_DEPTH

    current_depth = 0
    if parent_agent_id:
        parent = state_manager.get_agent(parent_agent_id)
        if parent:
            current_depth = parent.depth + 1

            if current_depth > max_allowed_depth:
                return {
                    "status": "error",
                    "error": f"Maximum sub-agent depth ({max_allowed_depth}) exceeded",
                }

    # Create new agent entry for tracking
    agent_id = state_manager.create_agent(task, parent_agent_id)

    # Serialize sub-agent execution to avoid rate limit cascades
    _sub_agent_semaphore.acquire()
    try:
        state_manager.update_status(agent_id, AgentStatus.RUNNING)

        # Import here to avoid circular dependency
        from smith.core.orchestrator import smith_orchestrator

        # Set current agent ID in config for child context
        old_agent_id = getattr(config, "_current_agent_id", None)
        config._current_agent_id = agent_id

        # Run the orchestrator with sub_agent excluded from tools
        results = []
        final_answer = None

        for event in smith_orchestrator(
            user_msg=task,
            require_approval=False,  # Sub-agents run autonomously
            exclude_tools=["sub_agent"],  # Prevent recursive spawning
        ):
            if event.get("type") == "final_answer":
                payload = event.get("payload", {})
                if isinstance(payload, dict):
                    final_answer = payload.get("response", str(payload))
                else:
                    final_answer = str(payload)
            elif event.get("type") == "error":
                raise Exception(
                    event.get("message", event.get("error", "Unknown error"))
                )

            results.append(event)

        # Restore parent agent ID
        config._current_agent_id = old_agent_id

        # Mark as completed
        state_manager.update_status(
            agent_id, AgentStatus.COMPLETED, result=final_answer
        )

        # Small delay after completion to let rate limits recover
        time.sleep(2.0)

        return {
            "status": "success",
            "agent_id": agent_id,
            "task": task,
            "depth": current_depth,
            "result": final_answer,
        }

    except Exception as e:
        # Mark as failed
        state_manager.update_status(agent_id, AgentStatus.FAILED, error=str(e))

        # Restore parent agent ID
        if "old_agent_id" in locals():
            config._current_agent_id = old_agent_id

        return {"status": "error", "agent_id": agent_id, "task": task, "error": str(e)}
    finally:
        _sub_agent_semaphore.release()


# Aliases for anti-hallucination
sub_agent = run_sub_agent
delegate = run_sub_agent
spawn_agent = run_sub_agent


METADATA = {
    "name": "sub_agent",
    "description": "Delegate a complex sub-task to a child Smith agent. The sub-agent has access to ALL tools (search, finance, weather, etc.) except creating more sub-agents.",
    "function": "run_sub_agent",
    "dangerous": False,
    "domain": "system",
    "output_type": "synthesis",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear description of the task for the sub-agent to complete",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum recursion depth (optional, default from config)",
                "default": 3,
            },
        },
        "required": ["task"],
    },
    "notes": "Sub-agents run a full orchestrator with all tools except sub_agent. Execution is serialized to prevent rate limits.",
}
