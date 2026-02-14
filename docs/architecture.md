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
2. Developer adds METADATA block to the tool file
3. Tool metadata is included in `registry.json`
4. Planner immediately sees the tool in the next planning cycle

```mermaid
flowchart TD

A[Developer creates NEW_TOOL.py]
B[Add METADATA block to tool]
C[Update registry.json]
D[Planner loads registry]
E[Tool available for planning]

A --> B --> C --> D --> E
```

---

## 5. Sub-Agent Architecture — Recursive Task Delegation

Sub-agents enable hierarchical task decomposition by spawning child Smith instances that run complete planning and execution cycles.

### Sub-Agent Execution Model

```mermaid
flowchart TD

A[Parent agent receives complex task]
B[Planner generates DAG with sub_agent nodes]
C[Orchestrator encounters sub_agent node]
D[Spawn child Smith instance]
E[Child runs full planning cycle]
F[Child executes its own DAG]
G[Child returns final result]
H[Parent continues with result]

A --> B --> C --> D
D --> E --> F --> G --> H
```

### Key Characteristics

**Serialization**: Sub-agents execute one at a time via global semaphore to prevent API rate limit cascades.

**Depth Limiting**: Maximum recursion depth (default: 3) prevents infinite delegation chains.

**Tool Access**: Sub-agents have access to all tools except `sub_agent` itself, preventing recursive spawning.

**State Tracking**: Parent-child relationships are tracked in the agent state manager for debugging and monitoring.

### Sub-Agent Lifecycle

```mermaid
sequenceDiagram
    participant Parent as Parent Agent
    participant SubAgent as Sub-Agent
    participant Planner as Planner
    participant Tools as Tools

    Parent->>SubAgent: Delegate task
    SubAgent->>Planner: Generate plan
    Planner-->>SubAgent: Return DAG
    SubAgent->>Tools: Execute tools
    Tools-->>SubAgent: Return results
    SubAgent->>SubAgent: Synthesize answer
    SubAgent-->>Parent: Return final result
```

### Use Cases

**Multi-Topic Research**: Delegate independent research topics to separate sub-agents that run in sequence.

**Hierarchical Decomposition**: Break complex tasks into sub-tasks, each handled by a dedicated agent.

**Specialized Processing**: Use sub-agents for tasks requiring different tool combinations or execution strategies.

---

## 6. Fleet Coordination — Parallel Multi-Agent Execution

Fleet coordination enables parallel execution of multiple independent agents working toward a common goal.

### Fleet Architecture

```mermaid
flowchart TD

A[User submits complex goal]
B[Fleet Coordinator receives goal]
C[LLM decomposes into N sub-tasks]
D[Spawn N agents in parallel]
E1[Agent 1 executes sub-task 1]
E2[Agent 2 executes sub-task 2]
E3[Agent N executes sub-task N]
F[Collect all results]
G[LLM aggregates results]
H[Return final answer]

A --> B --> C --> D
D --> E1
D --> E2
D --> E3
E1 --> F
E2 --> F
E3 --> F
F --> G --> H
```

### Fleet Execution Model

**Decomposition**: Fleet coordinator uses LLM to break goal into independent sub-tasks.

**Parallel Execution**: Agents run concurrently using ThreadPoolExecutor.

**Result Aggregation**: LLM synthesizes individual agent results into comprehensive final answer.

**Fault Tolerance**: Individual agent failures do not halt entire fleet execution.

### Fleet vs Sub-Agent Comparison

| Aspect | Sub-Agents | Fleet Coordination |
|--------|-----------|-------------------|
| **Execution** | Sequential (serialized) | Parallel (concurrent) |
| **Use Case** | Hierarchical decomposition | Independent parallel tasks |
| **Coordination** | Parent-child relationship | Peer agents with coordinator |
| **Failure Handling** | Propagates to parent | Isolated per agent |
| **Resource Usage** | Lower (one at a time) | Higher (multiple concurrent) |

---

## 7. Pipeline Summary & Core Principles

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
* **Hierarchical Execution** — sub-agents and fleet coordination enable complex task decomposition.
* **Controlled Parallelism** — fleet coordination provides parallelism while maintaining determinism.

**Mental Model:**

* Planner = compiler
* Orchestrator = runtime
* Tools = system calls
* Final LLM = renderer, not controller
* Sub-agents = recursive function calls
* Fleet = parallel process execution
