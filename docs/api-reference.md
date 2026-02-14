# API Reference

This document provides complete API documentation for Smith's public interfaces.

## Core Functions

### smith_orchestrator

Main entry point for executing agent tasks.

```python
def smith_orchestrator(
    user_msg: str,
    require_approval: bool = config.require_approval,
    exclude_tools: list = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Execute an autonomous agent task with DAG-based planning.

    Args:
        user_msg: Natural language task description
        require_approval: If True, request user approval for dangerous tools
        exclude_tools: List of tool names to exclude from planning

    Yields:
        Event dictionaries with type and payload

    Event Types:
        - planning: Planning phase started
        - plan_complete: DAG generated successfully
        - tool_start: Tool execution beginning
        - tool_complete: Tool execution finished
        - final_answer: Task complete with synthesized response
        - error: Error occurred during execution

    Example:
        >>> for event in smith_orchestrator("Get AAPL stock price"):
        ...     if event["type"] == "final_answer":
        ...         print(event["payload"]["response"])
    """
```

### plan_task

Generate execution plan without executing.

```python
def plan_task(
    user_msg: str,
    available_tools: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compile natural language request into validated DAG.

    Args:
        user_msg: Natural language task description
        available_tools: List of tool metadata dictionaries

    Returns:
        Dictionary with:
            - status: "success" or "error"
            - plan: DAG object (if successful)
            - error: Error message (if failed)

    Example:
        >>> from smith.registry import get_tools_registry
        >>> tools = get_tools_registry()
        >>> result = plan_task("Search for AI news", tools)
        >>> if result["status"] == "success":
        ...     print(result["plan"]["nodes"])
    """
```

## Tool Registry

### get_tools_registry

Load all registered tools.

```python
def get_tools_registry() -> List[Dict[str, Any]]:
    """
    Load tool registry from static JSON file.

    Returns:
        List of tool metadata dictionaries

    Example:
        >>> tools = get_tools_registry()
        >>> print([t["name"] for t in tools])
        ['llm_caller', 'finance_fetcher', 'google_search', ...]
    """
```

### get_tool_by_name

Retrieve specific tool metadata.

```python
def get_tool_by_name(tool_name: str) -> Dict[str, Any]:
    """
    Get metadata for a specific tool.

    Args:
        tool_name: Name of the tool

    Returns:
        Tool metadata dictionary

    Raises:
        ValueError: If tool not found

    Example:
        >>> tool = get_tool_by_name("finance_fetcher")
        >>> print(tool["description"])
    """
```

## Configuration

### Config Object

Global configuration accessible via `smith.config.config`.

```python
class Config:
    # LLM Configuration
    groq_api_key: str
    default_model: str = "llama-3.3-70b-versatile"

    # Execution Configuration
    require_approval: bool = False
    max_retries: int = 2
    default_timeout: float = 45.0

    # Sub-Agent Configuration
    max_subagent_depth: int = 3
    max_fleet_size: int = 5

    # Rate Limiting
    enable_rate_limiting: bool = True
```

## Event Types

### Planning Events

```python
{
    "type": "planning",
    "payload": {
        "message": "Generating execution plan..."
    }
}
```

### Plan Complete Events

```python
{
    "type": "plan_complete",
    "payload": {
        "num_nodes": 3,
        "tools": ["google_search", "llm_caller"]
    }
}
```

### Tool Execution Events

```python
{
    "type": "tool_start",
    "payload": {
        "node_id": 0,
        "tool": "finance_fetcher",
        "function": "get_stock_price"
    }
}

{
    "type": "tool_complete",
    "payload": {
        "node_id": 0,
        "status": "success",
        "duration": 1.23
    }
}
```

### Final Answer Events

```python
{
    "type": "final_answer",
    "payload": {
        "response": "The stock price of AAPL is $185.23"
    }
}
```

### Error Events

```python
{
    "type": "error",
    "message": "Tool execution failed",
    "details": {
        "tool": "google_search",
        "error": "API key not configured"
    }
}
```

## Tool Development API

### Tool Metadata Schema

```python
METADATA = {
    "name": str,              # Unique tool identifier
    "description": str,       # Human-readable description
    "function": str,          # Python function name
    "dangerous": bool,        # Requires user approval
    "domain": str,            # Tool category
    "output_type": str,       # Output format
    "parameters": {
        "type": "object",
        "properties": {
            "param_name": {
                "type": str,
                "description": str,
                "default": Any  # Optional
            }
        },
        "required": List[str]
    },
    "notes": str             # Additional information
}
```

### Tool Function Signature

```python
def tool_function(**kwargs) -> Dict[str, Any]:
    """
    Tool functions must return standardized response.

    Returns:
        Dictionary with:
            - status: "success" or "error"
            - result: Tool output (if successful)
            - error: Error message (if failed)
    """
```

## Sub-Agent API

### run_sub_agent

Delegate task to child agent.

```python
def run_sub_agent(
    task: str,
    parent_agent_id: Optional[str] = None,
    max_depth: Optional[int] = None
) -> Dict[str, Any]:
    """
    Spawn a sub-agent for complex sub-tasks.

    Args:
        task: Task description for sub-agent
        parent_agent_id: Parent agent ID (auto-detected if None)
        max_depth: Maximum recursion depth

    Returns:
        Dictionary with:
            - status: "success" or "error"
            - result: Sub-agent output
            - agent_id: Sub-agent identifier
            - depth: Recursion depth

    Example:
        >>> result = run_sub_agent("Research Python frameworks")
        >>> print(result["result"])
    """
```

## Fleet Coordination API

### FleetCoordinator

Manage parallel multi-agent execution.

```python
class FleetCoordinator:
    def run_fleet(
        self,
        goal: str,
        num_agents: int = 3,
        decompose_strategy: str = "auto"
    ) -> Dict[str, Any]:
        """
        Run multiple agents in parallel.

        Args:
            goal: Overall objective
            num_agents: Number of agents to spawn
            decompose_strategy: Task decomposition method

        Returns:
            Dictionary with:
                - status: "success" or "error"
                - agent_results: List of individual results
                - final_result: Aggregated output
        """
```

## Error Handling

### Common Exceptions

```python
# Planning failures
PlanningError: Raised when DAG generation fails

# Tool execution failures
ToolExecutionError: Raised when tool fails after retries

# Validation failures
ValidationError: Raised when DAG validation fails

# Timeout failures
TimeoutError: Raised when tool exceeds timeout
```

### Error Response Format

```python
{
    "status": "error",
    "error": "Error message",
    "details": {
        "phase": "planning|execution|synthesis",
        "tool": "tool_name",  # If applicable
        "trace": []           # Partial execution trace
    }
}
```

## Type Definitions

### DAG Structure

```python
{
    "nodes": [
        {
            "id": int,
            "tool": str,
            "function": str,
            "inputs": Dict[str, Any],
            "depends_on": List[int],
            "retry": int,
            "timeout": float,
            "on_fail": "halt" | "continue",
            "metadata": {
                "purpose": str
            }
        }
    ],
    "final_output_node": int
}
```

### Execution Trace

```python
[
    {
        "node_id": int,
        "tool": str,
        "function": str,
        "inputs": Dict[str, Any],
        "output": Any,
        "status": "success" | "error",
        "duration": float,
        "timestamp": str
    }
]
```
