# Smith Planner — Technical Overview

The Planner is the compilation stage of the Smith Runtime. Its only objective is to transform a natural‑language request into a fully validated JSON execution graph (DAG) that the Orchestrator can run deterministically. It does not execute tools, does not generate human answers, and does not improvise.

---

### 1. Purpose and Role

The Planner acts as a compiler:

* Input: natural‑language request
* Output: JSON DAG

If the DAG is not perfectly valid, the Planner does not allow execution to begin. The Orchestrator receives a plan only when it is safe, deterministic, and complete.

The Planner is also responsible for protecting runtime safety by preventing:

* missing required inputs
* invented parameters
* cyclical dependencies
* unexpected tool calls
* hidden placeholders or template expressions

---

### 2. Prompt Design and Behavioral Constraints

The Planner operates through a strict prompt that makes the LLM behave as a JSON generator rather than a conversational model. The prompt includes:

* the user's natural‑language request
* the Tool Registry (metadata for all tools)
* structural rules for nodes
* dependency rules
* failure and timeout rules
* output formatting requirements

The direct intention is to constrain the LLM to behave deterministically:

* No prose
* No markdown
* No explanation
* Only one valid JSON object

The Planner does not permit the LLM to fabricate new tool capabilities or rename function signatures.

---

### 3. Node Structure and Semantics

Each node in a DAG represents a single tool call and must observe this exact structure:

```
{
  "id": 0,
  "tool": "tool_name",
  "function": "function_name",
  "inputs": { ... },
  "depends_on": [],
  "retry": 2,
  "on_fail": "continue",
  "timeout": 45,
  "metadata": { "purpose": "<short reason>" }
}
```

Semantics:

* `id` increments sequentially with no gaps.
* `tool` and `function` must match entries in the Tool Registry.
* `inputs` must match the declared parameter schema exactly.
* `depends_on` establishes ordering guarantees.
* `on_fail` determines whether execution stops or continues on failure.
* `metadata.purpose` improves transparency and debugging.

The Planner never decides what a tool does — metadata already encodes that.

---

### 4. Dependency Rules and Graph Validity

A valid Smith DAG:

* contains no cycles
* references only past node IDs in dependencies
* can run deterministically in topological order

If dependencies are missing or create execution dead ends, validation fails. Independent nodes run in parallel if `depends_on` is empty.

The Planner is forbidden from inferring dependencies implicitly. All ordering requirements must appear in the JSON explicitly.

---

### 5. Multi‑LLM Rules

When the user asks for narrative results or multiple written outputs, the Planner generates one or more `llm_caller` nodes. These rules are mandatory:

* narrative output requires at least one llm_caller
* multiple narrative outputs require multiple llm nodes
* each llm node after the first depends on the previous llm node
* the final llm node becomes the `final_output_node`
* the `prompt` in each llm node must be a complete instruction, not a reference like "use previous result"

These constraints ensure that the LLM never influences execution flow after planning.

---

### 6. Validation Logic

Before a DAG is accepted, the Planner verifies:

* JSON syntax correctness
* presence of a non‑empty `nodes` list
* unique and integer `id` values
* valid tool names and matching function names
* inputs match metadata parameters and include required fields
* `depends_on` only references earlier IDs
* legitimate values for retry, timeout and on_fail
* valid `final_output_node` referencing an existing ID

If any rule fails, the DAG is rejected immediately.

---

### 7. Repair and Retry Strategy

The Planner supports multiple attempts to achieve a valid plan. The pipeline is:

1. First attempt using the normal system prompt
2. If JSON is invalid:

   * self‑correction prompt leveraging previous output and error reason
3. If syntax alone is incorrect:

   * dedicated syntax‑repair LLM pass
4. Revalidate

If after all attempts the plan is still invalid, the Planner returns an error and the Orchestrator does not run.

This ensures safety by guaranteeing that every executed plan is structurally valid.

---

### 8. Failure Scenarios and Resolutions

Typical failures include:

* missing required input parameters
* tool function mismatch
* invented fields
* cyclical dependencies
* missing `final_output_node`
* multiple llm nodes not chained

The Planner provides the invalid JSON plus the validation error to the LLM for correction. This closed feedback loop allows convergence without runtime risk.

---

### 9. Extension and Hacking Notes

To change Planner behavior, the recommended access points are:

* `PLANNER_SYSTEM_PROMPT` for default planning logic
* `REPAIR_PROMPT_TEMPLATE` to influence correction attempts
* `SYNTAX_REPAIR_PROMPT` to improve JSON recovery
* `MAX_PLANNER_ATTEMPTS` to tune reliability vs throughput
* validation rules if supporting new DAG shapes or tool metadata structures

Avoid modifying:

* Orchestrator logic (not part of planning)
* Metadata interpretations in tools (Planner should remain metadata‑driven)

A safe mental model when modifying the Planner:

> Everything the Planner produces must be executable without interpretation.

---

### 10. Summary

* The Planner is not an agent.
* The Planner is not a chatbot.
* The Planner does not execute tools.
* The Planner compiles requests into JSON, validates it, and stops if unsafe.

A valid plan is deterministically executable and guarantees that the Orchestrator needs no reasoning or improvisation at runtime.

The runtime stays safe because **execution never starts until planning is perfect**.
