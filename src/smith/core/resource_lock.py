"""
Resource Lock Manager for Smith
Prevents concurrent tool execution conflicts in multi-agent scenarios
"""

import threading
import time
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LockInfo:
    """Information about a locked resource"""

    tool_name: str
    agent_id: str
    acquired_at: datetime
    lock: threading.Lock = field(default_factory=threading.Lock)


class ResourceLockManager:
    """
    Thread-safe resource lock manager for tools.
    Prevents multiple agents from using the same tool concurrently.
    """

    def __init__(self):
        self._locks: Dict[str, LockInfo] = {}
        self._manager_lock = threading.Lock()

    def acquire_tool_lock(
        self, tool_name: str, agent_id: str, timeout: float = 30.0
    ) -> bool:
        """
        Acquire a lock for a tool.

        Args:
            tool_name: Name of the tool to lock
            agent_id: ID of the agent requesting the lock
            timeout: Maximum time to wait for lock (seconds)

        Returns:
            True if lock acquired, False if timeout
        """
        start_time = time.time()

        while True:
            with self._manager_lock:
                # Check if tool is already locked
                if tool_name not in self._locks:
                    # Create new lock
                    self._locks[tool_name] = LockInfo(
                        tool_name=tool_name,
                        agent_id=agent_id,
                        acquired_at=datetime.now(),
                    )
                    return True

                # Tool is locked by another agent
                lock_info = self._locks[tool_name]
                if lock_info.agent_id == agent_id:
                    # Same agent can re-acquire (reentrant)
                    return True

            # Check timeout
            if time.time() - start_time > timeout:
                return False

            # Wait a bit before retrying
            time.sleep(0.1)

    def release_tool_lock(self, tool_name: str, agent_id: str) -> None:
        """
        Release a lock for a tool.

        Args:
            tool_name: Name of the tool to unlock
            agent_id: ID of the agent releasing the lock
        """
        with self._manager_lock:
            if tool_name in self._locks:
                lock_info = self._locks[tool_name]
                # Only the agent that acquired the lock can release it
                if lock_info.agent_id == agent_id:
                    del self._locks[tool_name]

    def is_tool_locked(self, tool_name: str) -> bool:
        """
        Check if a tool is currently locked.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if locked, False otherwise
        """
        with self._manager_lock:
            return tool_name in self._locks

    def get_lock_info(self, tool_name: str) -> Optional[Dict]:
        """
        Get information about a lock.

        Args:
            tool_name: Name of the tool

        Returns:
            Dict with lock info or None if not locked
        """
        with self._manager_lock:
            if tool_name in self._locks:
                lock_info = self._locks[tool_name]
                return {
                    "tool_name": lock_info.tool_name,
                    "agent_id": lock_info.agent_id,
                    "acquired_at": lock_info.acquired_at.isoformat(),
                    "duration": (
                        (datetime.now() - lock_info.acquired_at).total_seconds()
                    ),
                }
            return None

    def get_all_locks(self) -> Dict[str, Dict]:
        """
        Get information about all current locks.

        Returns:
            Dict mapping tool names to lock info
        """
        with self._manager_lock:
            return {
                tool_name: {
                    "agent_id": info.agent_id,
                    "acquired_at": info.acquired_at.isoformat(),
                    "duration": (datetime.now() - info.acquired_at).total_seconds(),
                }
                for tool_name, info in self._locks.items()
            }

    def release_all_locks_for_agent(self, agent_id: str) -> int:
        """
        Release all locks held by a specific agent.
        Useful for cleanup when an agent terminates.

        Args:
            agent_id: ID of the agent

        Returns:
            Number of locks released
        """
        with self._manager_lock:
            tools_to_release = [
                tool_name
                for tool_name, info in self._locks.items()
                if info.agent_id == agent_id
            ]

            for tool_name in tools_to_release:
                del self._locks[tool_name]

            return len(tools_to_release)


# Global singleton instance
_global_lock_manager: Optional[ResourceLockManager] = None


def get_lock_manager() -> ResourceLockManager:
    """Get the global resource lock manager instance"""
    global _global_lock_manager
    if _global_lock_manager is None:
        _global_lock_manager = ResourceLockManager()
    return _global_lock_manager
