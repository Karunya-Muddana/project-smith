# Smith Autonomous Agent Runtime

Smith is a deterministic tool‑execution framework. It converts a natural‑language request into a strict JSON execution graph (DAG) and executes tools in a reproducible sequence. The LLM is not in the control loop. It is only used once at the end to synthesize the execution trace into a human‑readable answer.

Planner → JSON DAG → Orchestrator → Tool Execution → Final LLM (Optional)

---

## 1. Architecture Overview

Smith behaves like a compiler paired with a runtime. The Planner compiles the user request into a structured execution graph. The Orchestrator executes that graph deterministically. Tools are standalone functions configured only through metadata.

Key guarantees:

* No hidden loops
* No mid‑execution prompting
* No implicit tool calls
* No agent improvisation

Same input → same DAG → same behavior.

---

## 2. Installation & Startup

### Requirements

* Python 3.10+
* MongoDB running locally
* `.env` with tool‑specific API keys (Google, ArXiv, Weather, etc.)

### Run‑up

```
python -m smith.tools_populator   # register tools from /smith/tools
python -m smith.orchestrator      # start CLI runtime
```

---

## 3. CLI Usage

User types plain language. Smith handles planning and execution.

Example input:

```
get weather for Berlin then summarize headlines into a report
```

Runtime behavior:

1. Planner builds a JSON DAG selecting correct tools
2. Orchestrator executes them in dependency order
3. Final llm_caller synthesizes results (only if the request demands a written answer)

No JSON needs to be written by the user.

---

## 4. Tool System

Smith supports plug‑and‑play Python tools. Every tool is defined only by metadata.

A valid tool file must define:

* a callable Python function
* a `METADATA` object (JSON‑schema compliant)

After adding a tool:

```
python -m smith.tools_populator
```

No engine edits required.

---

## 5. Metadata Specification

Each tool describes its interface using JSON Schema.

Example:

```
METADATA = {
    "name": "weather_fetcher",
    "function": "run_weather",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string"}
        },
        "required": ["city"]
    }
}
```

Smith enforces:

* exact parameter names
* exact required fields
* no invented inputs
* no placeholders like {{...}}

Planner selects tools strictly from metadata. It does not read function bodies.

---

## 6. Planner Output (Execution Graph)

Planner output is always pure JSON.

Shape:

```
{
  "status": "success",
  "nodes": [
     { ... one tool execution ... }
  ],
  "final_output_node": <id>
}
```

Each node describes:

* id
* tool
* function
* inputs
* depends_on
* retry
* on_fail
* timeout
* metadata.purpose

If the request requires narrative or formatted results → final_output_node is an `llm_caller`.

---

## 7. Orchestrator Behavior

The Orchestrator is deterministic.

* Executes only when dependencies of a node are satisfied
* Respects retry, timeout, and on_fail policies
* Appends every step to the execution trace

If a final_output_node exists, its output is returned to the user. Otherwise raw trace data is printed.

---

## 8. Adding New Capabilities

Any stateless and JSON‑serializable function can be turned into a Smith tool.

Workflow:

1. Add Python file to `/smith/tools`
2. Implement function
3. Define `METADATA`
4. Run `smith.tools_populator`

No further configuration is needed.

---

## 9. Debugging

Failures do not hide. Planner and Orchestrator both report exact reasons.

* If planning fails → no execution occurs
* If execution halts → trace contains the cause

For deep troubleshooting see `troubleshooting.md`.

---

## 10. Design Philosophy

Smith is not an LLM wrapper or agent‑persona system.
It is a compiler‑runtime approach to automated workflows.

LLMs generate instructions.
Tools perform the work.
The DAG makes execution inspectable and reliable.

---

## 11. Contributing

Pull requests for tools and improvements are welcome.

Requirements for contributions:

* stateless functions only
* strict metadata
* explicit timeouts for network tools
* deterministic behavior preferred over stochastic behavior

---

## 12. Credits

Smith was built by **Karunya Muddana**.
LinkedIn: [https://www.linkedin.com/in/karunya-muddana/](https://www.linkedin.com/in/karunya-muddana/)

---