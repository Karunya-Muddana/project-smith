"""
Fleet Coordinator for Smith
Manages multiple agents working together on a complex goal
"""

from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from smith.core.agent_state import get_state_manager, AgentStatus
from smith.config import config


class FleetCoordinator:
    """
    Coordinates multiple Smith agents working in parallel on a complex goal.
    """

    def __init__(self, max_agents: int = None):
        self.max_agents = max_agents or config.max_fleet_size
        self.state_manager = get_state_manager()
        self._active = False
        self._results = []

    def run_fleet(
        self, goal: str, num_agents: int = 3, decompose_strategy: str = "auto"
    ) -> Dict[str, Any]:
        """
        Run a fleet of agents to accomplish a goal.

        Args:
            goal: The overall goal to accomplish
            num_agents: Number of agents to spawn (max: max_fleet_size)
            decompose_strategy: How to break down the goal ("auto", "parallel", "sequential")

        Returns:
            Dict with aggregated results from all agents
        """
        if num_agents > self.max_agents:
            return {
                "status": "error",
                "error": f"Requested {num_agents} agents, but max is {self.max_agents}",
            }

        if num_agents < 1:
            return {"status": "error", "error": "Must have at least 1 agent"}

        # Mark fleet as active
        self._active = True
        self._results = []

        try:
            # Step 1: Decompose the goal into sub-tasks
            sub_tasks = self._decompose_goal(goal, num_agents, decompose_strategy)

            if not sub_tasks:
                return {
                    "status": "error",
                    "error": "Could not decompose goal into sub-tasks",
                }

            # Step 2: Create fleet coordinator agent
            fleet_id = self.state_manager.create_agent(
                task=f"Fleet: {goal}", parent_id=None
            )
            self.state_manager.update_status(fleet_id, AgentStatus.RUNNING)

            # Step 3: Spawn agents in parallel
            agent_results = []

            with ThreadPoolExecutor(max_workers=num_agents) as executor:
                # Submit all sub-tasks
                futures = {}
                for i, sub_task in enumerate(sub_tasks):
                    future = executor.submit(
                        self._run_single_agent, sub_task, fleet_id, i
                    )
                    futures[future] = i

                # Collect results as they complete
                for future in as_completed(futures):
                    agent_idx = futures[future]
                    try:
                        result = future.result()
                        agent_results.append(
                            {
                                "agent_index": agent_idx,
                                "task": sub_tasks[agent_idx],
                                "result": result,
                            }
                        )
                    except Exception as e:
                        agent_results.append(
                            {
                                "agent_index": agent_idx,
                                "task": sub_tasks[agent_idx],
                                "error": str(e),
                            }
                        )

            # Step 4: Aggregate results
            final_result = self._aggregate_results(goal, agent_results)

            # Mark fleet as completed
            self.state_manager.update_status(
                fleet_id, AgentStatus.COMPLETED, result=final_result
            )

            return {
                "status": "success",
                "fleet_id": fleet_id,
                "goal": goal,
                "num_agents": num_agents,
                "sub_tasks": sub_tasks,
                "agent_results": agent_results,
                "final_result": final_result,
            }

        except Exception as e:
            return {"status": "error", "error": f"Fleet execution failed: {str(e)}"}
        finally:
            self._active = False

    def _decompose_goal(self, goal: str, num_agents: int, strategy: str) -> List[str]:
        """
        Decompose a goal into sub-tasks for multiple agents.

        Args:
            goal: The overall goal
            num_agents: Number of sub-tasks to create
            strategy: Decomposition strategy

        Returns:
            List of sub-task descriptions
        """
        # Use LLM to decompose the goal
        try:
            from smith.tools.LLM_CALLER import call_llm

            prompt = f"""You are a task decomposition expert. Break down the following goal into {num_agents} independent, parallel sub-tasks that can be worked on simultaneously by different agents.

Goal: {goal}

Strategy: {strategy}

Requirements:
1. Each sub-task should be self-contained and independent
2. Sub-tasks should not depend on each other's results
3. Together, the sub-tasks should fully accomplish the goal
4. Each sub-task should be clear and actionable

Return ONLY a JSON array of {num_agents} sub-task strings, nothing else.
Example: ["Sub-task 1 description", "Sub-task 2 description", ...]
"""

            result = call_llm(prompt)

            if result.get("status") == "success":
                import json

                response = result.get("response", "[]")
                # Try to parse JSON
                try:
                    sub_tasks = json.loads(response)
                    if isinstance(sub_tasks, list) and len(sub_tasks) == num_agents:
                        return sub_tasks
                except json.JSONDecodeError:
                    pass

            # Fallback: Simple split
            return [f"{goal} - Part {i + 1}/{num_agents}" for i in range(num_agents)]

        except Exception:
            # Fallback: Simple split
            return [f"{goal} - Part {i + 1}/{num_agents}" for i in range(num_agents)]

    def _run_single_agent(self, task: str, fleet_id: str, agent_index: int) -> Any:
        """
        Run a single agent as part of the fleet.

        Args:
            task: The task for this agent
            fleet_id: ID of the fleet coordinator
            agent_index: Index of this agent in the fleet

        Returns:
            Result from the agent
        """
        try:
            # Import here to avoid circular dependency
            from smith.tools.SUB_AGENT import run_sub_agent

            # Run as sub-agent of the fleet
            result = run_sub_agent(task, parent_agent_id=fleet_id)

            return result.get("result") if result.get("status") == "success" else result

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _aggregate_results(self, goal: str, agent_results: List[Dict]) -> str:
        """
        Aggregate results from all agents into a final answer.

        Args:
            goal: The original goal
            agent_results: List of results from each agent

        Returns:
            Aggregated final result
        """
        try:
            from smith.tools.LLM_CALLER import call_llm

            # Format results for LLM
            results_text = "\n\n".join(
                [
                    f"Agent {r['agent_index']} (Task: {r['task']}):\n{r.get('result', r.get('error', 'No result'))}"
                    for r in agent_results
                ]
            )

            prompt = f"""You are a result aggregation expert. Multiple agents worked on different parts of a goal. Synthesize their results into a comprehensive final answer.

Original Goal: {goal}

Agent Results:
{results_text}

Provide a comprehensive, well-structured final answer that combines all agent results to fully address the original goal."""

            result = call_llm(prompt)

            if result.get("status") == "success":
                return result.get("response", "Unable to aggregate results")

            return "Unable to aggregate results: " + result.get(
                "error", "Unknown error"
            )

        except Exception as e:
            return f"Aggregation failed: {str(e)}"

    def is_active(self) -> bool:
        """Check if fleet is currently active"""
        return self._active

    def get_status(self) -> Dict:
        """Get current fleet status"""
        return {
            "active": self._active,
            "max_agents": self.max_agents,
            "results_count": len(self._results),
        }


# Global singleton
_global_fleet_coordinator: Optional[FleetCoordinator] = None


def get_fleet_coordinator() -> FleetCoordinator:
    """Get the global fleet coordinator instance"""
    global _global_fleet_coordinator
    if _global_fleet_coordinator is None:
        _global_fleet_coordinator = FleetCoordinator()
    return _global_fleet_coordinator
