"""
Smith Planner
------------
The Architect 📐

This module listens to what you want (e.g., "Find me stocks!") and draws up a blueprint (DAG)
for the Orchestrator to follow. It uses a clever multi-shot LLM approach to get the JSON just right.
"""

import json
import logging
from typing import List, Dict, Any

from smith.config import config
from smith.tools.LLM_CALLER import call_llm

# Initialize Structured Logger
logging.basicConfig(
    level=logging.DEBUG if config.debug_mode else logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("smith.planner")

# Using config for constraints
MAX_PLANNER_ATTEMPTS = 3

# ============================================================
# PROMPTS
# ============================================================

PLANNER_SYSTEM_PROMPT = """
You are not a chatbot.
You are a COMPILER that transforms a natural-language USER REQUEST
into a JSON EXECUTION GRAPH for an autonomous agent.

You do NOT write text.
You do NOT answer the request.
You ONLY produce the graph.

Return ONLY a single valid JSON object. No markdown. No commentary.

──────────────────── FUNDAMENTAL CONTRACT ────────────────────
Your output represents a DAG (Directed Acyclic Graph) of tool calls.
Each node = ONE concrete tool execution.

You MUST follow the TOOL REGISTRY exactly — every tool has
required parameters and correct function names. Do NOT improvise.

──────────────────── REQUIRED FIELDS FOR EVERY NODE ────────────────────
Each node MUST have these exact fields:
{
  "id"          : integer (starting at 0 → 1 → 2 ... no gaps),
  "tool"        : string (must match TOOL REGISTRY),
  "function"    : string (must match TOOL REGISTRY),
  "inputs"      : object (keys MUST match the tool parameter names),
  "depends_on"  : array of integer ids (dependencies; may be empty),
  "retry"       : integer (usually 2),
  "on_fail"     : "halt" | "continue",
  "timeout"     : integer seconds (usually 45),
  "metadata"    : object with at least:
                  { "purpose": "<short reason for running this node>" }
}

──────────────────── TOOL INPUT RULES ────────────────────
You MUST respect EXACT parameter names from the TOOL REGISTRY:
• google_search       → inputs = { "query": "<search string>" }
• weather_fetcher     → inputs = { "city": "<city name>" }
• finance_fetcher     → inputs = { "operation": "price", "symbol": "<ticker>" }
• llm_caller          → inputs = { "prompt": "<clear instruction>" }

Do NOT create new parameter names.
Do NOT remove required parameters.
Do NOT rename parameters.
Do NOT embed placeholders like {{STEPS.0}} anywhere.

──────────────────── DEPENDENCY RULES ────────────────────
• If a tool must run after another → list the dependency in `depends_on`.
• Do NOT place future ids (no cycles).
• If no dependency is needed → use [] (parallel-eligible).

──────────────────── MULTI-LLM RULES (CRITICAL) ────────────────────
A USER REQUEST may require multiple llm_caller nodes.
You MUST follow all of these rules:

1) If ANY kind of report / summary / comparison / ranking / insight /
   pitch / speech / storyline / thread / post is requested → include llm_caller.

2) If the USER REQUEST asks for multiple narrative outputs (e.g. report → summary → tweet thread → speech):
   → You MUST generate SEPARATE llm_caller nodes.

3) Chaining:
   • Every llm_caller AFTER the first one MUST depend_on the PREVIOUS llm_caller.
   • Do NOT skip. Do NOT branch. A → B → C exact chain.
   Example: If node 7 is llm_caller and node 9 is the next llm_caller,
            then node 9 MUST have "depends_on": [7].

4) The LAST llm_caller in the chain MUST be the "final_output_node".

5) llm_caller.prompt MUST be a complete instruction on its own.
   It MUST NOT say things like “use the report above” or “based on earlier data”.
   It MUST specify WHAT to produce, not WHERE the data comes from.
   The orchestrator injects context automatically.

──────────────────── GENERAL SAFETY RULES ────────────────────
• NO string placeholders like {{...}} anywhere in any node.
• NO explanation outside JSON.
• NO markdown code fences.
• NO text before or after the JSON.

──────────────────── OUTPUT FORMAT (MUST MATCH EXACTLY) ────────────────────
{
  "status": "success",
  "nodes": [
     {
       "id": 0,
       "tool": "<tool_name>",
       "function": "<function_name>",
       "inputs": { ... },
       "depends_on": [],
       "retry": 2,
       "on_fail": "continue",
       "timeout": 45,
       "metadata": { "purpose": "<short reason>" }
     },
     ...
  ],
  "final_output_node": <id_of_last_llm_caller_or_last_node_if_no_llm>
}

TOOL REGISTRY:
{{TOOL_REGISTRY}}

USER REQUEST:
{{USER_REQUEST}}

JSON PLAN:
"""


REPAIR_PROMPT_TEMPLATE = """
The previous JSON plan for the autonomous agent was INVALID.

You MUST RETURN a corrected JSON plan following ALL rules and constraints.

TOOL REGISTRY:
{{TOOL_REGISTRY}}

INVALID PLAN:
{{LAST_OUTPUT}}

VALIDATION ERROR:
{{ERROR_MSG}}

USER REQUEST:
{{USER_REQUEST}}

Return ONLY the corrected JSON object. No commentary.
"""

SYNTAX_REPAIR_PROMPT = """
You are a strict JSON syntax fixer.

You will be given text that is INTENDED to be a single JSON object describing a
plan, but it contains syntax errors.

YOUR JOB:
- Fix ONLY the JSON SYNTAX.
- Do NOT change content more than necessary.
- Return ONLY a single valid JSON object.

<<<BROKEN_JSON_START>>>
{{BROKEN_JSON}}
<<<BROKEN_JSON_END>>>

Python json library error:
"{{PARSE_ERROR}}"

Return corrected JSON:
"""

# ============================================================
# INTERNAL HELPERS
# ============================================================


def _clean_json_output(text: str) -> str:
    """
    Strip markdown fences + isolate the first JSON object.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    first_obj = text.find("{")
    if first_obj == -1:
        return text
    end_brace = text.rfind("}")
    end = end_brace + 1 if end_brace != -1 else len(text)
    return text[first_obj:end]


def _build_registry_index(
    available_tools: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Build name → metadata index from DB registry.
    """
    index: Dict[str, Dict[str, Any]] = {}
    for t in available_tools:
        name = t.get("name")
        if name:
            index[name] = t
    return index


# ============================================================
# PLAN VALIDATION (DAG + SCHEMA)
# ============================================================


def _validate_plan(
    plan: Dict[str, Any], registry: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate DAG JSON produced by the LLM:
    - Must have nodes[]
    - Each node must respect tool schema
    - Depends_on must reference valid ids
    - final_output_node must exist
    """
    if not isinstance(plan, dict):
        return {"ok": False, "error": "Plan is not a JSON object."}

    if plan.get("status") == "error":
        # Planner explicitly failed; treat as valid error-plan
        return {"ok": True, "plan": plan}

    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {"ok": False, "error": "Missing or empty 'nodes' list."}

    # Collect node ids
    id_set = set()
    for n in nodes:
        nid = n.get("id")
        if not isinstance(nid, int):
            return {"ok": False, "error": "Every node.id must be an integer."}
        if nid in id_set:
            return {"ok": False, "error": f"Duplicate node id {nid}."}
        id_set.add(nid)

    # Validate per-node
    for n in nodes:
        nid = n["id"]
        tool = n.get("tool")
        func = n.get("function")
        inputs = n.get("inputs", {})
        depends_on = n.get("depends_on", [])
        retry = n.get("retry")
        on_fail = n.get("on_fail")
        timeout = n.get("timeout")

        if not tool or not func:
            return {"ok": False, "error": f"Node {nid}: missing 'tool' or 'function'."}

        if tool not in registry:
            return {"ok": False, "error": f"Node {nid}: tool '{tool}' not in registry."}

        meta = registry[tool]
        expected_func = meta.get("function")
        if func != expected_func:
            return {
                "ok": False,
                "error": (
                    f"Node {nid}: invalid function '{func}' for tool '{tool}' "
                    f"(expected '{expected_func}')."
                ),
            }

        if not isinstance(inputs, dict):
            return {"ok": False, "error": f"Node {nid}: 'inputs' must be an object."}

        params = meta.get("parameters") or {}
        props = params.get("properties") or {}
        required = params.get("required") or []

        # validate allowed keys
        for key in inputs.keys():
            if key not in props:
                return {
                    "ok": False,
                    "error": f"Node {nid}: invalid input '{key}' for tool '{tool}'.",
                }

        # validate required keys
        for req in required:
            if req not in inputs:
                return {
                    "ok": False,
                    "error": f"Node {nid}: missing required input '{req}' for tool '{tool}'.",
                }

        # depends_on: must be array of ids, only existing, and < nid (DAG)
        if not isinstance(depends_on, list):
            return {"ok": False, "error": f"Node {nid}: 'depends_on' must be a list."}
        for dep in depends_on:
            if not isinstance(dep, int):
                return {
                    "ok": False,
                    "error": f"Node {nid}: depends_on contains non-int id {dep}.",
                }
            if dep not in id_set:
                return {
                    "ok": False,
                    "error": f"Node {nid}: depends_on references unknown id {dep}.",
                }
            if dep >= nid:
                return {
                    "ok": False,
                    "error": f"Node {nid}: depends_on id {dep} must be < {nid} to avoid cycles.",
                }

        # retry
        if not isinstance(retry, int) or retry < 0:
            return {
                "ok": False,
                "error": f"Node {nid}: 'retry' must be a non-negative integer.",
            }

        # on_fail
        if on_fail not in ("halt", "continue"):
            return {
                "ok": False,
                "error": f"Node {nid}: 'on_fail' must be 'halt' or 'continue'.",
            }

        # timeout
        if not isinstance(timeout, int) or timeout <= 0:
            return {
                "ok": False,
                "error": f"Node {nid}: 'timeout' must be a positive integer.",
            }

    # final_output_node must exist
    fon = plan.get("final_output_node")
    if not isinstance(fon, int) or fon not in id_set:
        return {"ok": False, "error": "Invalid or missing 'final_output_node' id."}

    return {"ok": True, "plan": plan}


# ============================================================
# LLM CALL HELPERS
# ============================================================


def _call_llm(prompt: str, model: str = None) -> Dict[str, Any]:
    """
    Thin wrapper around smith.tools.LLM_CALLER.call_llm
    to normalize the response shape.
    """
    target_model = model or config.primary_model
    try:
        resp = call_llm(prompt, model=target_model)
    except TypeError:
        resp = call_llm(prompt)

    if resp.get("status") != "success":
        return {
            "status": "error",
            "error": resp.get("error", "Planner LLM call failed"),
        }
    return {"status": "success", "raw": resp.get("response", "")}


def _call_llm_for_plan(prompt: str) -> Dict[str, Any]:
    return _call_llm(prompt)


def _call_llm_for_syntax_fix(broken_json: str, parse_error: str) -> Dict[str, Any]:
    """
    Second-layer LLM pass whose ONLY job is to fix JSON syntax.
    """
    prompt = SYNTAX_REPAIR_PROMPT.replace("{{BROKEN_JSON}}", broken_json).replace(
        "{{PARSE_ERROR}}", parse_error
    )
    return _call_llm(prompt)


# ============================================================
# MAIN ENTRYPOINT
# ============================================================


def plan_task(user_msg: str, available_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The Main Planning Function.
    
    Think of this as the "Compiler". It takes your fuzzy English and turns it into precise JSON instructions.
    
    How it works:
      1. Looks at all the tools we have (the Registry).
      2. Asks the LLM: "Hey, how do I solve this user request with these tools?"
      3. Validates the answer. If the LLM goofed up the JSON, we ask it to fix it (Self-Correction).
      4. Hand over the solid plan to the Orchestrator!
    """

    registry = _build_registry_index(available_tools)
    minimal_view = [
        {
            "name": meta.get("name"),
            "function": meta.get("function"),
            "parameters": meta.get("parameters"),
        }
        for meta in registry.values()
    ]

    try:
        registry_str = json.dumps(minimal_view, indent=2)
    except Exception:
        registry_str = json.dumps(minimal_view, default=str)

    last_raw = ""
    last_error = "Unknown error"

    for attempt in range(MAX_PLANNER_ATTEMPTS):
        if attempt == 0:
            prompt = PLANNER_SYSTEM_PROMPT.replace(
                "{{TOOL_REGISTRY}}", registry_str
            ).replace("{{USER_REQUEST}}", user_msg)
        else:
            prompt = (
                REPAIR_PROMPT_TEMPLATE.replace("{{TOOL_REGISTRY}}", registry_str)
                .replace("{{LAST_OUTPUT}}", last_raw)
                .replace("{{ERROR_MSG}}", last_error)
                .replace("{{USER_REQUEST}}", user_msg)
            )

        logger.info("Planner LLM attempt %d/%d...", attempt + 1, MAX_PLANNER_ATTEMPTS)
        llm_result = _call_llm_for_plan(prompt)
        if llm_result.get("status") != "success":
            last_error = llm_result.get("error", "Planner LLM call failed.")
            continue

        raw_text = llm_result["raw"]
        last_raw = raw_text
        cleaned = _clean_json_output(raw_text)

        # JSON PARSING + SYNTAX FIX
        try:
            plan_obj = json.loads(cleaned)
        except Exception as parse_err:
            parse_msg = str(parse_err)
            logger.warning(
                "Planner JSON parse error on attempt %d: %s — invoking syntax-fix LLM",
                attempt + 1,
                parse_msg,
            )
            fix_result = _call_llm_for_syntax_fix(cleaned, parse_msg)
            if fix_result.get("status") != "success":
                last_error = (
                    f"Syntax fix LLM failed: {fix_result.get('error', 'unknown')}"
                )
                continue

            fixed_raw = fix_result["raw"]
            fixed_clean = _clean_json_output(fixed_raw)
            last_raw = fixed_clean

            try:
                plan_obj = json.loads(fixed_clean)
            except Exception as e2:
                last_error = f"JSON parse error after syntax fix: {e2}"
                logger.warning(
                    "Planner syntax-fix still invalid JSON on attempt %d: %s",
                    attempt + 1,
                    last_error,
                )
                continue

        # STRUCTURAL VALIDATION (DAG + tool schema)
        validation = _validate_plan(plan_obj, registry)
        if not validation["ok"]:
            last_error = validation["error"]
            logger.warning(
                "Planner validation failed on attempt %d: %s",
                attempt + 1,
                last_error,
            )
            continue

        validated_plan = validation["plan"]
        if "status" not in validated_plan:
            validated_plan["status"] = "success"

        logger.info(
            "Planner produced a valid DAG with %d node(s).",
            len(validated_plan.get("nodes", [])),
        )
        return validated_plan

    # All attempts failed
    logger.error(
        "Planner failed after %d attempts: %s", MAX_PLANNER_ATTEMPTS, last_error
    )
    return {
        "status": "error",
        "error": f"Unable to build valid plan with given tools. Reason: {last_error}",
        "raw": last_raw,
    }
