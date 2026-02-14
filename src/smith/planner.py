"""
Smith Planner
------------
The Architect 📐

This module listens to what you want (e.g., "Find me stocks!") and draws up a blueprint (DAG)
for the Orchestrator to follow. It uses a clever multi-shot LLM approach to get the JSON just right.
"""

import json
from typing import List, Dict, Any

from smith.config import config
from smith.tools.LLM_CALLER import call_llm
from smith.core.logging import get_smith_logger

# Initialize Structured Logger
logger = get_smith_logger("smith.planner")

# Using config for constraints
MAX_PLANNER_ATTEMPTS = 3

# ============================================================
# PROMPTS
# ============================================================

PLANNER_SYSTEM_PROMPT = """
You are a COMPILER that transforms a user request into a JSON execution graph.
You do NOT write text. You do NOT answer the request. You ONLY produce the JSON graph.

──────────────────── CRITICAL: NO HALLUCINATIONS ────────────────────
You must ONLY use tools listed in the TOOL REGISTRY below.
If a tool is not listed, it DOES NOT EXIST. Do not invent tools.
Do not invent parameters. Use EXACT parameter names.

If you cannot solve the request with available tools, return:
{ "status": "error", "error": "Cannot fulfill request with available tools." }

──────────────────── GRAPH RULES ────────────────────
Each node in "nodes" represents ONE tool execution.
{
  "id": <int, MUST START AT 0 AND INCREMENT BY 1>,
  "thought": "<string, reasoning>",
  "tool": "<string, MUST MATCH REGISTRY EXACTLY>",
  "function": "<string, MUST MATCH REGISTRY EXACTLY>",
  "inputs": { <key>: <value> }, // Must match strict schema
  "depends_on": [ <int_ids_of_previous_steps> ],
  "retry": 2,
  "on_fail": "halt",
  "timeout": 45
}

──────────────────── MULTI-TOOL RULES ────────────────────
1. IDS MUST be 0-based indices (0, 1, 2...).
2. Identify dependencies explicitly. If Step 1 needs Step 0's output, Step 1 MUST have "depends_on": [0].
3. Use "llm_caller" SPARINGLY for logical processing, summarization, or decision making.
4. The FINAL node must be the one producing the user's answer (usually an llm_caller node).

──────────────────── COST CONSTRAINTS ────────────────────
⚠️ MINIMIZE PLAN SIZE - Each tool has a cost:
  - Data tools (google_search, finance_fetcher, weather_fetcher, arxiv_search): 1 point
  - Computation tools (news_clusterer): 2 points
  - LLM reasoning (llm_caller): 5 points
  - System tools (tool_diagnostics): 1 point

TARGET: Minimize total cost. Prefer data + computation over excessive LLM calls.
CONSTRAINT: Use minimum number of tools required.
PENALTY: Plans with >3 llm_caller nodes will be rejected.

──────────────────── TOOL DOMAIN AWARENESS ────────────────────
⚠️ NEVER ask llm_caller to produce:
  - Real-time facts (current weather, stock prices) → Use data tools
  - Factual claims without sources → Use google_search or other data tools
  - Article clustering → Use news_clusterer

──────────────────── SUB-AGENT DELEGATION ────────────────────
🔥 PREFER sub_agent FOR PARALLEL INDEPENDENT TASKS:
When the request involves researching/analyzing MULTIPLE independent topics:
  ✅ GOOD: Use sub_agent to delegate each topic to a separate agent
  ❌ BAD: Use sequential google_search calls for each topic

Example: "Research Python and JavaScript, compare them"
  ✅ CORRECT PLAN:
    - Node 0: sub_agent(task="Research Python programming language comprehensively")
    - Node 1: sub_agent(task="Research JavaScript programming language comprehensively")  
    - Node 2: llm_caller(prompt="Compare Python and JavaScript based on: {{STEPS.0}} and {{STEPS.1}}")
  
  ❌ WRONG PLAN:
    - Node 0: google_search(query="Python")
    - Node 1: google_search(query="JavaScript")
    - Node 2: llm_caller(...)

When to use sub_agent:
  - Multiple independent research topics (stocks, companies, technologies, etc.)
  - Parallel data gathering that doesn't depend on each other
  - Complex multi-step analysis that can be isolated
  - Any task that benefits from specialized focused attention

When NOT to use sub_agent:
  - Single simple lookup (just use the data tool directly)
  - Tasks that depend on previous results
  - Simple aggregation or formatting

If you CANNOT fulfill the request with available tools, you MUST return:
{ "status": "error", "error": "Missing capability: <describe what's missing>" }

Example missing capabilities:
  - "No tool for image processing" 
  - "No tool for database access"
  - "No tool for sending emails"

──────────────────── TOOL INPUTS ────────────────────
DO NOT use placeholders like {{STEPS...}} unless absolutely necessary and supported by the orchestrator.
Prefer implicit context passing via "depends_on". The orchestrator passes results automatically.

──────────────────── OUTPUT FORMAT ────────────────────
{
  "status": "success",
  "nodes": [ ... ],
  "final_output_node": <int_id>
}

TOOL REGISTRY:
{{TOOL_REGISTRY}}

USER REQUEST:
{{USER_REQUEST}}
"""


REPAIR_PROMPT_TEMPLATE = """
⚠️ PLANNER ERROR: YOUR PREVIOUS PLAN WAS INVALID ⚠️

You violated the strict tool registry or syntax rules.
You must regenerate the plan correcting the specific error below.

ERROR:
{{ERROR_MSG}}

INVALID PLAN:
{{LAST_OUTPUT}}

TOOL REGISTRY (ONLY USE THESE):
{{TOOL_REGISTRY}}

USER REQUEST:
{{USER_REQUEST}}

Return ONLY the corrected JSON. No apologies.
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
    for meta in available_tools:
        tool_name = meta.get("name")
        if tool_name:
            index[tool_name] = meta
    return index


def _validate_plan_constraints(plan_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate plan against constraints:
    - LLM usage limit (max 3 calls)
    - Minimum tool usage

    Returns:
        {"valid": bool, "violations": List[str], "warnings": List[str]}
    """
    violations = []
    warnings = []

    nodes = plan_obj.get("nodes", [])

    # Count LLM calls
    llm_calls = sum(1 for node in nodes if node.get("tool") == "llm_caller")

    if llm_calls > 3:
        violations.append(f"Excessive LLM usage: {llm_calls} calls (limit: 3)")

    if llm_calls > 2:
        warnings.append(
            f"High LLM usage: {llm_calls} calls - consider using computation tools"
        )

    # Check single-step plans that use LLM for data retrieval
    if len(nodes) == 1 and llm_calls == 1:
        node = nodes[0]
        thought = node.get("thought", "").lower()
        if any(
            keyword in thought
            for keyword in ["price", "weather", "stock", "current", "fetch", "get data"]
        ):
            warnings.append(
                "Single LLM step for data retrieval - consider using data tools"
            )

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
    }


def _detect_capability_gaps(
    plan_obj: Dict[str, Any], available_tools: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Detect if plan tries to do things beyond available tool capabilities.

    Returns:
        {"has_gaps": bool, "gaps": List[str], "suggestions": List[str]}
    """
    gaps = []
    suggestions = []

    nodes = plan_obj.get("nodes", [])

    # Check if LLM is being asked to compute numbers
    for node in nodes:
        if node.get("tool") == "llm_caller":
            thought = node.get("thought", "").lower()
            prompt = node.get("inputs", {}).get("prompt", "").lower()

            # Numeric computation detected
            if any(
                kw in thought or kw in prompt
                for kw in ["calculate", "compute", "trend", "percentage", "statistics"]
            ):
                gaps.append(
                    "Numeric computation requested but numeric_computer not available"
                )

            # Clustering detected
            if any(
                kw in thought or kw in prompt
                for kw in ["cluster", "group", "categorize articles"]
            ):
                if "news_clusterer" in available_tools:
                    suggestions.append(
                        "Consider using 'news_clusterer' for article clustering"
                    )
                else:
                    gaps.append(
                        "Article clustering requested but news_clusterer not available"
                    )

    # Check for impossible requests
    impossible_keywords = {
        "image": "image processing",
        "database": "database access",
        "email": "email sending",
        "file": "file system access",
        "video": "video processing",
    }

    user_request_text = str(plan_obj).lower()
    for keyword, capability in impossible_keywords.items():
        if keyword in user_request_text and keyword not in [
            t.lower() for t in available_tools.keys()
        ]:
            gaps.append(f"No tool available for {capability}")

    return {"has_gaps": len(gaps) > 0, "gaps": gaps, "suggestions": suggestions}


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
                    "error": (
                        f"Node {nid}: missing required input '{req}' for tool '{tool}'."
                    ),
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
                    "error": (
                        f"Node {nid}: depends_on id {dep} must be < {nid} to avoid cycles."
                    ),
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
            "description": meta.get("description"),
            "function": meta.get("function"),
            "parameters": meta.get("parameters"),
            "example": meta.get("example"),
            "tags": meta.get("tags"),
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

        # Post-validation: Check constraints and capability gaps
        constraint_check = _validate_plan_constraints(validated_plan)
        if not constraint_check["valid"]:
            # Hard violations - reject plan
            last_error = "; ".join(constraint_check["violations"])
            logger.warning(
                "Plan violates constraints on attempt %d: %s", attempt + 1, last_error
            )
            continue

        # Soft warnings - log but don't reject
        if constraint_check["warnings"]:
            for warning in constraint_check["warnings"]:
                logger.warning("Plan warning: %s", warning)

        # Capability gap detection
        capability_check = _detect_capability_gaps(validated_plan, registry)
        if capability_check["has_gaps"]:
            for gap in capability_check["gaps"]:
                logger.warning("Capability gap detected: %s", gap)

        if capability_check["suggestions"]:
            for suggestion in capability_check["suggestions"]:
                logger.info("Optimization suggestion: %s", suggestion)

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
