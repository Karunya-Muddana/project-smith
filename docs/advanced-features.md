# Advanced Features

This guide covers Smith's advanced capabilities including sub-agents, fleet coordination, and sophisticated execution patterns.

## Sub-Agent Delegation

Sub-agents allow you to delegate complex sub-tasks to independent Smith instances that run with full tool access.

### Overview

When a task is too complex for a single execution plan, you can use sub-agents to break it down recursively. Each sub-agent:

- Runs its own planning and execution cycle
- Has access to all tools except `sub_agent` (prevents infinite recursion)
- Executes serially to prevent API rate limit cascades
- Tracks depth to prevent runaway recursion

### Basic Usage

Sub-agents are automatically used by the planner when appropriate, but you can also invoke them programmatically:

```python
from smith.tools.SUB_AGENT import run_sub_agent

result = run_sub_agent("Research the history of quantum computing")

if result["status"] == "success":
    print(result["result"])
```

### Configuration

```python
# In smith.config
max_subagent_depth = 3  # Maximum recursion levels
```

### Execution Model

Sub-agents execute with these guarantees:

1. **Serialization**: Only one sub-agent runs at a time (global semaphore)
2. **Depth Limiting**: Maximum depth prevents infinite recursion
3. **State Tracking**: Parent-child relationships are tracked
4. **Autonomous Execution**: No approval required for sub-agent tools

### Example Scenarios

**Multi-Topic Research**

```
Request: "Research Python, JavaScript, and Rust. Compare their performance."

Plan:
- Node 0: sub_agent(task="Research Python comprehensively")
- Node 1: sub_agent(task="Research JavaScript comprehensively")
- Node 2: sub_agent(task="Research Rust comprehensively")
- Node 3: llm_caller(prompt="Compare findings from previous nodes")
```

**Hierarchical Task Decomposition**

```
Request: "Analyze the tech industry in Germany"

Main Agent:
- Sub-agent 1: "Research top tech companies in Germany"
  - Sub-sub-agent: "Get financial data for SAP"
  - Sub-sub-agent: "Get financial data for Siemens"
- Sub-agent 2: "Research German tech policy"
- LLM synthesis
```

### Best Practices

**When to Use Sub-Agents:**
- Multiple independent research topics
- Complex multi-step workflows
- Tasks requiring different tool combinations

**When NOT to Use Sub-Agents:**
- Simple sequential workflows (use regular DAG)
- Tasks requiring shared state between steps
- Performance-critical applications (serialization overhead)

### Error Handling

Sub-agents handle errors gracefully:

```python
result = run_sub_agent("Invalid task")

if result["status"] == "error":
    print(f"Sub-agent failed: {result['error']}")
    # Main agent continues execution
```

---

## Fleet Coordination

Fleet coordination enables parallel execution of multiple independent agents working toward a common goal.

### Overview

The Fleet Coordinator:
- Decomposes goals into independent sub-tasks
- Spawns multiple agents in parallel
- Aggregates results into a final answer
- Manages agent lifecycle and state

### Basic Usage

```python
from smith.core.fleet_coordinator import get_fleet_coordinator

coordinator = get_fleet_coordinator()

result = coordinator.run_fleet(
    goal="Research AI developments in healthcare, finance, and education",
    num_agents=3,
    decompose_strategy="auto"
)

print(result["final_result"])
```

### Configuration

```python
# In smith.config
max_fleet_size = 5  # Maximum concurrent agents
```

### Decomposition Strategies

**Auto (Default)**
- LLM automatically breaks down goal into independent tasks
- Best for general-purpose use

**Parallel**
- Assumes tasks are already independent
- Minimal decomposition overhead

**Sequential**
- Tasks have dependencies but can be parallelized at sub-task level

### Example Usage

```python
result = coordinator.run_fleet(
    goal="Analyze stock market trends across tech, healthcare, and energy sectors",
    num_agents=3
)

# Access individual agent results
for agent_result in result["agent_results"]:
    print(f"Agent {agent_result['agent_index']}: {agent_result['task']}")
    print(f"Result: {agent_result['result']}\n")

# Access aggregated final result
print("Final Analysis:", result["final_result"])
```

### Performance Considerations

**Parallelism:**
- Agents run in parallel using ThreadPoolExecutor
- Sub-agents within fleet still execute serially (semaphore)
- Effective parallelism limited by API rate limits

**Resource Usage:**
- Each agent consumes LLM tokens for planning and synthesis
- Monitor API quotas when using large fleets

---

## Resource Locking

Smith includes resource locking to prevent deadlocks and race conditions.

### Lock Manager

```python
from smith.core.resource_lock import get_lock_manager

lock_manager = get_lock_manager()

# Acquire lock
lock_manager.acquire("resource_name", agent_id="agent_123")

try:
    # Perform resource-sensitive operation
    pass
finally:
    # Always release locks
    lock_manager.release("resource_name", agent_id="agent_123")
```

### Automatic Locking

Tools can declare resource requirements in metadata:

```python
METADATA = {
    "name": "database_writer",
    "resources": ["database_connection"],
    # ...
}
```

The orchestrator automatically acquires and releases locks.

---

## Rate Limiting

Smith includes built-in rate limiting to prevent API quota exhaustion.

### Default Limits

```python
DEFAULT_LIMITS = {
    "llm_caller": 1.0,        # 1 second between calls
    "google_search": 0.5,     # 0.5 seconds
    "news_fetcher": 0.5,
    "weather_fetcher": 0.2,
}
```

### Custom Rate Limits

Modify limits in orchestrator configuration:

```python
from smith.core.orchestrator import RateLimiter

rate_limiter = RateLimiter()
rate_limiter.DEFAULT_LIMITS["custom_tool"] = 2.0  # 2 seconds
```

### Behavior

- Rate limiter uses token bucket algorithm
- Blocks execution until rate limit window passes
- Per-tool tracking (independent limits)

---

## Parallel Execution

Smith supports parallel execution of independent DAG nodes.

### Enabling Parallelism

Currently experimental. Nodes with no dependencies can execute concurrently:

```python
# In DAG
{
    "nodes": [
        {"id": 0, "tool": "google_search", "depends_on": []},
        {"id": 1, "tool": "finance_fetcher", "depends_on": []},
        {"id": 2, "tool": "weather_fetcher", "depends_on": []},
        {"id": 3, "tool": "llm_caller", "depends_on": [0, 1, 2]}
    ]
}
```

Nodes 0, 1, 2 can execute in parallel. Node 3 waits for all dependencies.

### Limitations

- Sub-agents still execute serially (global semaphore)
- Rate limiting may serialize execution
- Resource locks may create contention

---

## Error Recovery Patterns

### Graceful Degradation

```python
# In DAG node
{
    "id": 0,
    "tool": "google_search",
    "on_fail": "continue",  # Continue execution even if this fails
    "retry": 2
}
```

### Fallback Tools

Plan alternative tools for critical operations:

```python
# Primary: google_search
# Fallback: web_scraper + manual URL
```

### Partial Results

Even if some tools fail, Smith returns partial execution trace:

```python
for event in smith_orchestrator("Complex task"):
    if event["type"] == "error":
        # Access partial trace
        trace = event.get("details", {}).get("trace", [])
        # Use successful results
```

---

## Advanced DAG Patterns

### Fan-Out / Fan-In

```python
{
    "nodes": [
        {"id": 0, "tool": "google_search", "depends_on": []},
        {"id": 1, "tool": "process_result_1", "depends_on": [0]},
        {"id": 2, "tool": "process_result_2", "depends_on": [0]},
        {"id": 3, "tool": "process_result_3", "depends_on": [0]},
        {"id": 4, "tool": "llm_caller", "depends_on": [1, 2, 3]}
    ]
}
```

Node 0 fans out to 1, 2, 3. Node 4 fans in from all.

### Pipeline Pattern

```python
{
    "nodes": [
        {"id": 0, "tool": "data_source"},
        {"id": 1, "tool": "transform_1", "depends_on": [0]},
        {"id": 2, "tool": "transform_2", "depends_on": [1]},
        {"id": 3, "tool": "transform_3", "depends_on": [2]},
        {"id": 4, "tool": "output", "depends_on": [3]}
    ]
}
```

Linear data pipeline with sequential transformations.

---

## Monitoring and Observability

### Execution Traces

Access full execution history:

```python
for event in smith_orchestrator("Task"):
    if event["type"] == "tool_complete":
        payload = event["payload"]
        print(f"Tool: {payload['tool']}")
        print(f"Duration: {payload['duration']}s")
        print(f"Status: {payload['status']}")
```

### Exporting Traces

```bash
# In CLI
/trace          # View last execution trace
/dag            # Export DAG as JSON
/inspect        # ASCII visualization
/export         # Export session to markdown
```

### Programmatic Access

```python
# Save trace to file
import json

trace = []
for event in smith_orchestrator("Task"):
    trace.append(event)

with open("trace.json", "w") as f:
    json.dump(trace, f, indent=2)
```

---

## Performance Optimization

### Minimize LLM Calls

LLM calls are expensive. Optimize by:
- Using data tools (search, finance) instead of LLM reasoning
- Batching multiple questions into single LLM call
- Caching LLM results for repeated queries

### Tool Timeout Tuning

```python
# In DAG
{
    "id": 0,
    "tool": "slow_tool",
    "timeout": 120,  # Increase for slow operations
}
```

### Retry Strategy

```python
{
    "id": 0,
    "tool": "unreliable_api",
    "retry": 3,  # Retry up to 3 times
}
```

---

## Security Considerations

### Tool Approval

Mark dangerous tools:

```python
METADATA = {
    "name": "file_deleter",
    "dangerous": True,  # Requires user approval
}
```

### API Key Management

Never hardcode keys:

```python
# Use environment variables
import os
api_key = os.getenv("GROQ_API_KEY")
```

### Input Validation

Always validate tool inputs:

```python
def my_tool(file_path: str):
    # Validate input
    if not file_path.startswith("/safe/directory/"):
        return {"status": "error", "error": "Invalid path"}
```
