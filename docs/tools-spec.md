# tools-spec.md

## Smith Tool Specification — Developer Guide

This document defines the requirements and conventions for building tools in the Smith Runtime. Tools extend system capability, but they must follow strict metadata and execution rules to preserve determinism, safety, and interoperability with the Planner and Orchestrator.

---

### 1. Tool File Requirements

A Smith tool is a standalone Python file located in `src/smith/tools/`. Every tool **must** provide:

* a callable function that performs the operation
* a `METADATA` dictionary that formally describes the tool to the Planner

The runtime never analyzes code to infer behavior. Only metadata defines how a tool can be called.

---

### 2. METADATA Structure

Every `METADATA` object must contain these fields:

```
METADATA = {
  "name": "weather_fetcher",             # tool identifier
  "function": "run_weather",            # name of callable in this file
  "dangerous": False,                     # optional safety flag
  "parameters": {
    "type": "object",
    "properties": {
      "city": { "type": "string" }
    },
    "required": ["city"]
  }
}
```

Notes:

* `name` must be unique in the registry
* `function` must match the actual Python callable name
* `parameters` must follow JSON Schema conventions
* Use descriptive names rather than abbreviations

---

### 3. JSON Schema Conventions

Tool parameters use JSON Schema to ensure the Planner can reason about inputs at compile time.

Rules:

* Each parameter must declare a type (`string`, `number`, `boolean`, `object`, or `array`)
* Optional parameters must be omitted from `required`
* Nested objects are allowed but discouraged unless necessary
* Parameters should be atomic and serializable

Bad patterns:

* Inconsistent parameter naming ("location" sometimes, "city" other times)
* Using one field that encodes multiple inputs
* Accepting free‑form prompts when structure is possible

---

### 4. Examples — Good vs Bad Tools

#### Good Tool Example (correct)

```
METADATA = {
  "name": "finance_price",
  "function": "run_finance_price",
  "dangerous": False,
  "parameters": {
    "type": "object",
    "properties": {
      "symbol": { "type": "string" }
    },
    "required": ["symbol"]
  }
}

def run_finance_price(symbol: str):
  # deterministic output, validated inputs
  return fetch_price(symbol)
```

This tool:

* declares clear required input
* has deterministic behavior
* uses a function name that exactly matches metadata

#### Bad Tool Example (incorrect)

```
METADATA = {
  "name": "finance",
  "function": "run",        # vague and generic
  "parameters": {}
}

def run(payload):              # untyped and ambiguous
  return do_everything(payload)
```

Problems:

* function name does not describe a single purpose
* parameters are not structured
* encourages the LLM to misuse the tool
* unsafe and impossible to validate

The Planner rejects tools like this because they cannot be modeled safely.

---

### 5. Safety Flags and Execution Behavior

`dangerous` metadata determines Orchestrator handling:

| dangerous | Result                                              |
| --------- | --------------------------------------------------- |
| False     | normal execution allowed                            |
| True      | tool allowed only when explicitly requested by user |

> Tools that can modify files, delete data, write to DBs, send emails, or call payment processors must be marked `dangerous = True`.

Additional safety properties are inherited from DAG runtime:

* retry count
* timeout per execution
* explicit `on_fail: halt | continue`

Tools must never hide internal exceptions — they should raise errors clearly so the trace reflects the real failure.

---

### 6. Referencing the Function Name

The `function` field in METADATA must exactly match the function implemented in the file.

Good:

```
METADATA = { "function": "run_weather" }
def run_weather(city):
    ...
```

Bad:

```
METADATA = { "function": "weather" }
def run_weather(city):
    ...      # Orchestrator will fail to load
```

The Orchestrator performs dynamic imports and resolves functions strictly using `function`.

---

### 7. Testing a Tool Locally

Tools can be tested without the Planner or Orchestrator.

Checklist before registry population:

* Run the callable manually
* Validate parameter schema correctness
* Validate deterministic behavior
* Validate runtime error messages are clean and descriptive

Typical development loop:

```
python
>>> from smith.tools.WEATHER_FETCHER import run_weather
>>> run_weather("Berlin")
```

Everything must work without hidden global state.

---

### 8. Full Lifecycle of a Tool

The flow of a tool from creation to execution is deterministic:

1. Developer creates `src/smith/tools/MY_TOOL.py` with function + METADATA
2. Developer adds tool metadata to `src/smith/tools/registry.json`
3. Planner queries registry and uses tool metadata when compiling a DAG
4. Orchestrator loads the function dynamically at execution time
5. Execution result is appended to the trace
6. The trace becomes part of final LLM synthesis
7. The trace generated becomes available for subsequent tools and final synthesis

No core engine modification is ever required.

---

### 9. Principles for Reliable Tool Development

* Tools should be small and single‑responsibility
* Inputs must be explicit and typed
* No reliance on global or cached state
* No silent failure
* Return JSON‑serializable outputs
* Make failure clear rather than ambiguous

Smith scales horizontally by adding many small tools, not by creating large speculative ones.

---

End of specification.
