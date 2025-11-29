# Smith Architecture

Smith is a deterministic autonomous agent runtime. It transforms natural-language requests into a validated execution graph (DAG), executes tools in a controlled sequence, and uses an LLM only once at the end to synthesize the execution trace into a human‑readable answer.

At a high level, Smith behaves less like a chatbot and more like a compiler plus runtime:

* The **Planner** compiles the user’s prompt into a JSON DAG.
* The **Orchestrator** executes that DAG deterministically.
* **Tools** are stateless functions described by metadata.
* The **Final LLM** summarizes the trace but never controls execution.

---

## 1. Runtime Architecture — Request → Response

Smith is built around a deterministic execution pipeline. A natural‑language prompt does not directly trigger tool calls. Instead, Smith converts the request into a structured execution graph (DAG), validates it, then executes it step‑by‑step with full traceability.

The lifecycle follows four phases:

1. **Input** → User enters a natural‑language request.
2. **Planning** → Planner uses an LLM to compile a JSON DAG.
3. **Execution** → Orchestrator executes tools deterministically.
4. **Final Synthesis** → Final LLM converts the execution trace into a human output.

```mermaid
flowchart TD

A[User enters prompt]
B[Orchestrator receives request]
C[Planner invoked]
D[LLM compiles DAG plan]
E{Is DAG valid?}
F[Planner returns DAG to orchestrator]
X[Planner returns error to user]

G[Orchestrator begins DAG execution]
H{Next step available with successful deps?}
I[Load tool via tool_loader]
J[Execute tool with retry and timeout]
K{Execution success?}
L[Append result to trace]
M[Stop execution and return failure]
N{More steps remaining?}

O[Final LLM synthesis]
P[Final answer returned to user]

A --> B --> C --> D --> E
E -->|yes| F --> G
E -->|no| X

G --> H
H -->|yes| I --> J --> K
H -->|no| O

K -->|success| L --> N
K -->|failure and on_fail=halt| M
K -->|failure and on_fail=continue| L

N -->|yes| G
N -->|no| O --> P
```

---

## 2. Planner Cycle — How a Prompt Becomes a DAG

The Planner behaves like a compiler — not an agent. It generates the execution plan once, and the Orchestrator executes it exactly as written. If the DAG cannot be validated, execution never begins.

**Planner responsibilities:**

* Build system prompt including the Tool Registry
* Call LLM for DAG generation
* Extract and sanitize JSON
* Validate schema + dependencies
* Retry on failure
* Return DAG or return planning error

```mermaid
flowchart TD

A[User request text]
B[Build system prompt with tool registry]
C[Call planning LLM]
D[Raw LLM output]
E[Extract JSON object]
F{JSON syntax valid?}
G[Syntax repair pass]
H[Parse into internal plan object]
I{Schema and DAG validation passed?}
J[Return validated DAG]
K[Return planning error]
R[Retry next attempt]

A --> B --> C --> D --> E --> F
F -->|yes| H --> I
F -->|no| G --> H --> I

I -->|yes| J
I -->|no| R --> B

R -->|max attempts reached| K
```

---

## 3. Orchestrator Cycle — Deterministic Execution of the DAG

The Orchestrator is the runtime engine of Smith. It never calls an LLM for decision‑making and never improvises — it executes exactly the DAG the Planner produced.

```mermaid
flowchart TD

A[Receive validated DAG]
B[Dependency sort / find eligible node]
C{Node ready for execution?}
D[Load tool module and function]
E[Run tool with timeout and retry]
F{Tool succeeded?}
G[Append result to execution trace]
H[Stop execution and return failure]
I[Return full trace — all nodes complete]

A --> B --> C
C -->|yes| D --> E --> F
C -->|no — completed| I
C -->|no — blocked| H

F -->|success| G --> B
F -->|fail — continue| G --> B
F -->|fail — halt| H
```


---

## 4. Tool Lifecycle — How New Tools Become Usable

Tools are **plug‑and‑play** and require **no modification of the core engine**.

1. Developer creates a Python file in `smith/tools/`
2. Developer runs `python -m smith.tools_populator`
3. Populator extracts METADATA and registers it in MongoDB
4. Planner immediately sees the tool in the next planning cycle

```mermaid
flowchart TD

A[Developer creates NEW_TOOL.py]
B[Run tools_populator]
C[Scan smith/tools directory]
D[Extract METADATA]
E[Write metadata to MongoDB registry]
F[Planner queries registry for available tools]

A --> B --> C --> D --> E --> F
```

---

## 5. Pipeline Summary & Core Principles

###  Smith Pipeline Summary

1. User enters request →
2. Planner builds DAG →
3. Orchestrator executes DAG →
4. Tools generate trace →
5. Final LLM generates answer

```mermaid
flowchart LR

A[User natural language request]
B[Planner builds JSON DAG]
C[Orchestrator validates DAG]
D[Deterministic tool execution]
E[Execution trace accumulated]
F[Final LLM synthesis]
G[Human-readable answer returned]

A --> B --> C --> D --> E --> F --> G
```

###  Core Principles

* **Determinism** — the same DAG always produces the same behavior.
* **Metadata‑Driven** — the engine does not "know" tools; it only reads their metadata.
* **Separation of Concerns** — planning, execution, and synthesis never overlap.
* **One‑Shot Planning** — LLM never participates during tool execution.
* **Fail‑Safety** — every tool has retry, timeout, and failure rules.
* **Security** — tools are stateless, isolated, and never invoked implicitly.

**Mental Model:**

* Planner = compiler
* Orchestrator = runtime
* Tools = system calls
* Final LLM = renderer, not controller
