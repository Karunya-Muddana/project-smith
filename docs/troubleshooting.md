# Troubleshooting Guide

This file is written for developers who want to debug Smith under real failure conditions. No theory, no generic advice. If you see a specific error message, this document tells you exactly what it means and what to do next.

Format throughout the file:
If you see THIS error message → it means THAT → do THIS.

---

## 1. Planner failures

The Planner is the most common failure source because it interacts with the LLM and must satisfy strict JSON and DAG validation rules.

#### Case 1 — "Planner returned status=error"

Meaning:
The LLM failed to produce a DAG after maximum retry attempts.
Fix:
Check tool names and parameters in your prompt. Planner cannot invent inputs that do not match tool metadata.

#### Case 2 — "Missing or empty 'nodes' list"

Meaning:
The LLM produced a JSON object but no DAG nodes.
Fix:
User prompt likely did not imply any tool usage. Rephrase prompt to require tool calls or add a tool that satisfies the task.

#### Case 3 — "invalid input '<X>' for tool '<Y>'"

Meaning:
The DAG referenced a parameter name not present in the tool schema.
Fix:
Check the METADATA.properties of the referenced tool and use those exact parameter names.

#### Case 4 — "Duplicate node id" or "depends_on references unknown id"

Meaning:
JSON was almost correct but LLM produced illegal DAG numbering.
Fix:
No code change required. Add more structure in the prompt or add context to remove ambiguity.

---

## 2. Orchestrator failures

Orchestrator failures are not random. They always indicate a structural or runtime issue.

#### Case 5 — "Blocked execution: no eligible node"

Meaning:
Dependencies cannot be resolved. A node depends on another node that failed or never executed.
Fix:
Check the DAG. Ensure that nodes that depend_on another have a valid successful path.

#### Case 6 — "Halt triggered by node failure"

Meaning:
A tool failed and its on_fail policy was set to halt.
Fix:
If failure should be tolerated, change on_fail to continue in the DAG. If failure should stop execution, inspect trace for the real error message from the failing tool.

#### Case 7 — "Tool load error: function not found"

Meaning:
The metadata.function field does not match the Python function name.
Fix:
Rename either the callable or the metadata so both names are identical.

---

## 3. Tool failures

If a tool itself fails to run, the trace captures the actual stack trace.

#### Case 8 — "TypeError: missing required parameter"

Meaning:
A tool received incomplete inputs relative to its schema.
Fix:
Inspect the DAG node inputs. Add the missing fields or modify metadata.required if the tool logic changed.

#### Case 9 — "Timeout reached"

Meaning:
The tool exceeded the timeout value defined in the DAG.
Fix:
Check network calls or heavy computations. Increase timeout only when necessary.

#### Case 10 — "Unhandled exception inside tool"

Meaning:
The tool raised an exception that was not caught.
Fix:
Add controlled error handling inside the tool so that failures become predictable.

---

## 4. Registry failures

#### Case 11 — "Tool not found in registry"

Meaning:
The tool is not listed in `registry.json`.
Fix:
Add the tool metadata to `src/smith/tools/registry.json` and restart Smith.

#### Case 12 — "Duplicate tool name in registry"

Meaning:
Two tools share the same metadata.name in registry.json.
Fix:
Every tool must have a globally unique name. Rename one of the tools.

#### Case 13 — "Planner does not see the tool"

Meaning:
Tool exists in code but not in registry.json.
Fix:
Add tool metadata to `registry.json` and restart Smith.

---

## 5. Final synthesis failures

#### Case 14 — "Final LLM failed"

Meaning:
This does not affect deterministic execution but prevents user-friendly output formatting.
Fix:
Retry. If it happens frequently, simplify the execution trace or shorten tool outputs.

#### Case 15 — "Empty trace provided to synthesis"

Meaning:
Execution finished but no nodes produced results.
Fix:
Planner generated a DAG with no meaningful work. Improve the prompt or expand available tools.

---

## 6. Recent Issues (v0.1.0)

This section documents issues discovered and resolved in recent development.

#### Case 16 — "Sub-agent deadlock"

**Symptoms**: Sub-agent execution hangs indefinitely, never returning to parent agent.

**Meaning**: Event key mismatch between sub-agent and parent orchestrator. Sub-agent emits `final_answer` event but parent expects different key structure.

**Fix**: 
- Ensure sub-agent uses correct event schema matching orchestrator expectations
- Verify `final_answer` event payload structure
- Check that sub-agent properly propagates events to parent

**Resolution**: Fixed in v0.1.0 by standardizing event handling in `SUB_AGENT.py`.

#### Case 17 — "Rate limit exceeded (429 errors)"

**Symptoms**: Frequent 429 errors from LLM API, especially with fleet coordination or multiple sub-agents.

**Meaning**: Too many concurrent API calls exceeding provider rate limits.

**Fix**:
- Increase rate limit delays in configuration
- Reduce fleet size (`MAX_FLEET_SIZE`)
- Use sub-agents instead of fleet for sequential tasks
- Implement exponential backoff for retries

**Configuration**:
```python
DEFAULT_LIMITS = {
    "llm_caller": 2.0,  # Increase from 1.0
    "google_search": 1.0,
}
```

#### Case 18 — "Parallel execution causes resource contention"

**Symptoms**: Tools fail intermittently when parallel execution is enabled.

**Meaning**: Multiple tools accessing same resource simultaneously without proper locking.

**Fix**:
- Add resource declarations to tool metadata
- Use resource locking for shared resources
- Disable parallel execution if tools are not thread-safe

**Example**:
```python
METADATA = {
    "name": "database_writer",
    "resources": ["database_connection"],  # Declare resource
    # ...
}
```

#### Case 19 — "CLI command 'smith' not found after installation"

**Symptoms**: `smith` command not available in terminal after `pip install -e .`

**Meaning**: Entry point not registered or virtual environment not activated.

**Fix**:
- Ensure virtual environment is activated
- Reinstall: `pip install -e .`
- Check `pyproject.toml` has correct entry point configuration
- Try `python -m smith.cli.main` as fallback

#### Case 20 — "ASCII banner syntax warning"

**Symptoms**: SyntaxWarning about invalid escape sequences in ASCII art.

**Meaning**: Backslashes in ASCII art not properly escaped.

**Fix**: Use raw strings (r"...") for ASCII art or escape backslashes properly.

**Example**:
```python
# Before
banner = "  ____   __  __  _____"

# After
banner = r"  ____   __  __  _____"
```

#### Case 21 — "Sub-agent exceeds timeout"

**Symptoms**: Sub-agent tasks timeout even though individual tools complete successfully.

**Meaning**: Default timeout too short for full sub-agent orchestration cycle (planning + execution + synthesis).

**Fix**: Increase sub-agent timeout in DAG node:
```python
{
    "id": 0,
    "tool": "sub_agent",
    "timeout": 120,  # Increase from default 45
    # ...
}
```

#### Case 22 — "Fleet coordination returns partial results"

**Symptoms**: Fleet completes but some agent results are missing.

**Meaning**: Individual agents failed but fleet continued execution.

**Fix**:
- Check individual agent error logs
- Reduce fleet size to isolate failing agents
- Ensure all sub-tasks are truly independent
- Add error handling in fleet aggregation

---

## 7. Confirming fixes

After resolving an issue, verify the fix:

1. Restart Smith: `smith`
2. Test with simple query
3. Check execution trace: `/trace`
4. Verify no errors in logs

If Planner succeeds and DAG executes without halt, the system is healthy.

---

## 8. Getting Help

If you encounter an issue not covered here:

1. Check execution trace with `/trace` command
2. Export session for analysis: `/export`
3. Review logs for detailed error messages
4. Search GitHub issues for similar problems
5. Open new issue with:
   - Smith version
   - Python version
   - Full error message
   - Minimal reproducible example
   - Execution trace

End of document.
