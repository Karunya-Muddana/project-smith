"""
Agent State Tracking for Smith
Manages agent hierarchy, status, and results in multi-agent scenarios
"""

import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading


class AgentStatus(Enum):
    """Status of an agent"""

    INITIALIZING = "initializing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentInfo:
    """Information about an agent"""

    agent_id: str
    parent_id: Optional[str]
    depth: int
    task: str
    status: AgentStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    children: List[str] = field(default_factory=list)


class AgentStateManager:
    """
    Manages the state of all agents in the system.
    Tracks hierarchy, status, and results.
    """

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._lock = threading.Lock()

    def create_agent(self, task: str, parent_id: Optional[str] = None) -> str:
        """
        Create a new agent and return its ID.

        Args:
            task: The task description for this agent
            parent_id: ID of parent agent (None for root)

        Returns:
            The new agent's ID
        """
        agent_id = str(uuid.uuid4())[:8]  # Short ID for readability

        # Determine depth
        depth = 0
        if parent_id:
            with self._lock:
                if parent_id in self._agents:
                    depth = self._agents[parent_id].depth + 1
                    # Add this agent as a child of parent
                    self._agents[parent_id].children.append(agent_id)

        agent_info = AgentInfo(
            agent_id=agent_id,
            parent_id=parent_id,
            depth=depth,
            task=task,
            status=AgentStatus.INITIALIZING,
            created_at=datetime.now(),
        )

        with self._lock:
            self._agents[agent_id] = agent_info

        return agent_id

    def update_status(
        self,
        agent_id: str,
        status: AgentStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update the status of an agent.

        Args:
            agent_id: ID of the agent
            status: New status
            result: Result data (if completed)
            error: Error message (if failed)
        """
        with self._lock:
            if agent_id in self._agents:
                agent = self._agents[agent_id]
                agent.status = status

                if status in [
                    AgentStatus.COMPLETED,
                    AgentStatus.FAILED,
                    AgentStatus.CANCELLED,
                ]:
                    agent.completed_at = datetime.now()

                if result is not None:
                    agent.result = result

                if error is not None:
                    agent.error = error

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """
        Get information about an agent.

        Args:
            agent_id: ID of the agent

        Returns:
            AgentInfo or None if not found
        """
        with self._lock:
            return self._agents.get(agent_id)

    def get_children(self, agent_id: str) -> List[AgentInfo]:
        """
        Get all child agents of an agent.

        Args:
            agent_id: ID of the parent agent

        Returns:
            List of child AgentInfo objects
        """
        with self._lock:
            if agent_id not in self._agents:
                return []

            children_ids = self._agents[agent_id].children
            return [self._agents[cid] for cid in children_ids if cid in self._agents]

    def get_agent_tree(self, agent_id: str) -> Dict:
        """
        Get the full tree of an agent and all descendants.

        Args:
            agent_id: ID of the root agent

        Returns:
            Dict representing the agent tree
        """
        with self._lock:
            if agent_id not in self._agents:
                return {}

            agent = self._agents[agent_id]

            tree = {
                "agent_id": agent.agent_id,
                "task": agent.task,
                "status": agent.status.value,
                "depth": agent.depth,
                "created_at": agent.created_at.isoformat(),
                "children": [],
            }

            # Recursively build tree for children
            for child_id in agent.children:
                if child_id in self._agents:
                    tree["children"].append(self.get_agent_tree(child_id))

            return tree

    def get_all_active_agents(self) -> List[AgentInfo]:
        """
        Get all agents that are currently running.

        Returns:
            List of active AgentInfo objects
        """
        with self._lock:
            return [
                agent
                for agent in self._agents.values()
                if agent.status in [AgentStatus.INITIALIZING, AgentStatus.RUNNING]
            ]

    def get_root_agents(self) -> List[AgentInfo]:
        """
        Get all root agents (agents with no parent).

        Returns:
            List of root AgentInfo objects
        """
        with self._lock:
            return [agent for agent in self._agents.values() if agent.parent_id is None]

    def cleanup_agent(self, agent_id: str) -> None:
        """
        Remove an agent and all its descendants from tracking.

        Args:
            agent_id: ID of the agent to remove
        """
        with self._lock:
            if agent_id not in self._agents:
                return

            # Get all descendants
            to_remove = [agent_id]
            queue = [agent_id]

            while queue:
                current = queue.pop(0)
                if current in self._agents:
                    children = self._agents[current].children
                    to_remove.extend(children)
                    queue.extend(children)

            # Remove all
            for aid in to_remove:
                if aid in self._agents:
                    del self._agents[aid]

    def get_stats(self) -> Dict:
        """
        Get statistics about all agents.

        Returns:
            Dict with agent statistics
        """
        with self._lock:
            total = len(self._agents)
            by_status = {}

            for agent in self._agents.values():
                status = agent.status.value
                by_status[status] = by_status.get(status, 0) + 1

            return {
                "total_agents": total,
                "by_status": by_status,
                "active_agents": len(self.get_all_active_agents()),
                "root_agents": len(self.get_root_agents()),
            }


# Global singleton instance
_global_state_manager: Optional[AgentStateManager] = None


def get_state_manager() -> AgentStateManager:
    """Get the global agent state manager instance"""
    global _global_state_manager
    if _global_state_manager is None:
        _global_state_manager = AgentStateManager()
    return _global_state_manager
