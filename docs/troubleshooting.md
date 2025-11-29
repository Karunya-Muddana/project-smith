# troubleshooting.md

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

## 4. Populator and Registry failures

#### Case 11 — "No metadata found" during population

Meaning:
The tool file does not define METADATA.
Fix:
Add METADATA and run the populator again.

#### Case 12 — "Insert failed: duplicate name"

Meaning:
Two tools share the same metadata.name.
Fix:
Every tool must have a globally unique name.

#### Case 13 — "Planner does not see the tool"

Meaning:
Metadata exists in the file but the populator was not run after adding the tool.
Fix:
Run python -m smith.tools_populator.

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

## 6. Confirming fixes

After resolving an issue, rerun in this order:

1. python -m smith.tools_populator
2. python -m smith.orchestrator

If Planner succeeds and DAG executes without halt, the system is healthy.

End of document.
