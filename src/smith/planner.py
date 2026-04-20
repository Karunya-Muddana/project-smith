"""
Smith Planner v4.0
------------------
The Architect 📐

Compiles natural language requests into validated JSON DAGs.
Uses a dedicated planner model separate from the synthesis model.
"""

import json
from typing import List, Dict, Any

from smith.config import config
from smith.tools.LLM_CALLER import call_llm
from smith.core.logging import get_smith_logger

logger = get_smith_logger("smith.planner")

MAX_PLANNER_ATTEMPTS = 3

# ─────────────────────────────────────────────────────────────────────────────
# DEDICATED PLANNER MODEL
# Separate from config.primary_model — planner needs reliable JSON output,
# not the best reasoning model. Maverick is fast and structured.
# ─────────────────────────────────────────────────────────────────────────────
PLANNER_MODEL = "meta/llama-4-maverick-17b-128e-instruct"

# ============================================================
# PROMPTS
# ============================================================

PLANNER_SYSTEM_PROMPT = """\
You are a JSON execution graph compiler for an AI agent runtime.
Your ONLY job: read a user request and output a valid JSON plan.

OUTPUT CONTRACT:
- Emit ONLY a JSON object. No prose, no markdown fences, no explanation.
- Never answer the user's question. Only plan how to answer it.

════════════════════════════════════════════════════
SECTION 1 — HARD CONSTRAINTS (never violate these)
════════════════════════════════════════════════════

C1. Only use tools from TOOL REGISTRY. Unlisted tools do not exist.
C2. Only use parameter names from the tool's schema. Never invent parameters.
C3. node.id = 0-based integers, sequential, no gaps (0, 1, 2, …)
C4. depends_on = only ids with LOWER values than current node (enforces DAG)
C5. final_output_node = id of the last node that produces the user's answer
C6. Max 15 llm_caller nodes per plan

If request cannot be fulfilled: {"status": "error", "error": "Missing capability: <what>"}

════════════════════════════════════════════════════
SECTION 2 — TASK CLASSIFICATION
════════════════════════════════════════════════════

Classify the request as ONE type before planning:

TYPE A — Real-time lookup ("current price", "latest news", "weather today")
  Pattern: [data_tool(s)] → [llm_caller: final answer]
  Depth: 2–4 nodes

TYPE B — Knowledge/analysis ("explain X", "compare X vs Y from knowledge")
  Pattern: [llm_caller per section in parallel] → [llm_caller: combine]
  Depth: 3–8 nodes
  Note: Do NOT use google_search for pure knowledge questions.

TYPE C — Hybrid: live data + analysis ("research X and analyze", "find news on X and compare")
  Pattern: [google_search × N] → [deep_summarizer] → [llm_caller: final]
  Depth: 4–8 nodes

TYPE D — Code generation ("write", "build", "implement", "create script")
  Pattern: [code_agent: single node]
  Depth: 1 node

════════════════════════════════════════════════════
SECTION 3 — NODE SCHEMA
════════════════════════════════════════════════════

{
  "id":         <int>     0-based sequential integer
  "thought":    <string>  one sentence: why this tool for this step
  "tool":       <string>  EXACT tool name from TOOL REGISTRY
  "function":   <string>  EXACT function name from TOOL REGISTRY
  "inputs":     {}        only keys listed in tool schema
  "depends_on": [<int>]   upstream node ids this node needs
  "retry":      2
  "on_fail":    "continue" for data tools, "halt" for critical transforms
  "timeout":    45        use 90 for code_agent
}

════════════════════════════════════════════════════
SECTION 4 — TOOL RULES
════════════════════════════════════════════════════

── google_search ──────────────────────────────────
- Use for: real-time research, news, deep content fetching
- Always set fetch_webpages: true for research queries
- For comparing two topics: use TWO separate google_search nodes in parallel
  (depends_on: [] for both — they run simultaneously)
- Pass output downstream using: "{{STEPS.N.response}}"

── news_fetcher ───────────────────────────────────
STANDALONE ONLY. Fetches its own news via DuckDuckGo News.
- Use when: user wants "news headlines" or "news articles"
- NEVER chain after google_search
- NEVER pass {{STEPS.N}} or {{STEPS.N.response}} into news_fetcher
- Correct usage: news_fetcher(raw_query=<query>, top_n=5, fetch_body=true)
- Omit the articles parameter entirely
- For two topics: TWO separate news_fetcher nodes with depends_on: [] for both

── deep_summarizer ────────────────────────────────
MUST USE when: ≥2 data nodes feed into analysis
MUST NOT USE when: single source, simple lookup, no analysis needed
HARD LIMITS: max ONE per plan, placed after data nodes, before final llm_caller

WIRING — CRITICAL, DO NOT SKIP:
  deep_summarizer MUST list ALL upstream data node ids in depends_on.
  The final llm_caller MUST depend on deep_summarizer.

  CORRECT example for "get AMD and Intel news and compare":
    {"id": 0, "tool": "news_fetcher", "depends_on": []}
    {"id": 1, "tool": "news_fetcher", "depends_on": []}
    {"id": 2, "tool": "deep_summarizer", "depends_on": [0, 1],
              "inputs": {"text": "{{STEPS.0.response}}\n\n{{STEPS.1.response}}", "query": "..."}}
    {"id": 3, "tool": "llm_caller", "depends_on": [2],
              "inputs": {"prompt": "{{STEPS.2.response}}"}}

  WRONG — missing depends_on (causes empty input):
    {"id": 2, "tool": "deep_summarizer", "depends_on": []}  ← NEVER DO THIS

INPUT RULE: ALWAYS use dotted path:
  "text": "{{STEPS.0.response}}\n\n{{STEPS.1.response}}"
  NEVER use bare refs like {{STEPS.0}} — they pass raw dicts, not text

── llm_caller ─────────────────────────────────────
PERMITTED: writing docs, explaining concepts, final answer synthesis, ≤2 source synthesis
FORBIDDEN: real-time data, coding tasks, synthesizing ≥3 large sources (use deep_summarizer)
WIRING: final llm_caller MUST have depends_on pointing to previous node — NEVER empty

── sub_agent ──────────────────────────────────────
Use ONLY when ≥2 truly independent research domains need parallel deep investigation.
WRONG: "AMD news" and "Intel news" — these are same domain, use two google_search nodes
RIGHT: "Python history" and "JavaScript history" — unrelated topics needing full research
FORBIDDEN: single topic, sequential dependent steps

── code_agent ─────────────────────────────────────
Use for all code generation. ONE node, never chained, timeout: 90.
Include ALL requirements in task parameter.

── code_assistant ─────────────────────────────────
Use ONLY for: explain/fix/review of code the user already has.
NEVER for generating new code.

════════════════════════════════════════════════════
SECTION 5 — CONTEXT PASSING
════════════════════════════════════════════════════

Dotted path (use for text content):
  "text": "{{STEPS.0.response}}"      ← deep_summarizer, llm_caller inputs
  "prompt": "{{STEPS.2.response}}"    ← llm_caller inputs

Bare ref (use ONLY for news_fetcher articles fallback — rarely needed):
  "articles": "{{STEPS.0}}"

Pipe default (use when upstream node has on_fail: continue):
  "prompt": "{{STEPS.0.response | default: 'no data'}}"

════════════════════════════════════════════════════
SECTION 6 — PRE-OUTPUT CHECKLIST (run mentally before emitting)
════════════════════════════════════════════════════

□ Are all node.id values 0-based sequential integers with no gaps?
□ Does every depends_on only reference lower-numbered ids?
□ Is final_output_node set to the id of the last answer-producing node?
□ Does every tool/function EXACTLY match the registry?
□ If ≥2 data nodes exist → is there a deep_summarizer with depends_on listing ALL of them?
□ Does deep_summarizer have depends_on: [<all upstream data node ids>]? NEVER empty.
□ Does the final llm_caller have depends_on: [<deep_summarizer id>]? NEVER empty.
□ Is deep_summarizer using {{STEPS.N.response}} (not bare {{STEPS.N}})?
□ Is news_fetcher standalone (no articles parameter, no depends_on from google_search)?
□ Are there ≤15 llm_caller nodes?

Fix any violation before emitting.

════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════

{
  "status": "success",
  "nodes": [ <node>, ... ],
  "final_output_node": <int>
}

TOOL REGISTRY:
{{TOOL_REGISTRY}}

USER REQUEST:
{{USER_REQUEST}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# REPAIR PROMPT
# Key improvement: includes the core rules inline so the model doesn't
# forget constraints while fixing a single violation.
# ─────────────────────────────────────────────────────────────────────────────

REPAIR_PROMPT_TEMPLATE = """\
Your previous JSON plan was REJECTED. Fix ONLY the violation below.

VIOLATION: {{ERROR_MSG}}

REJECTED PLAN:
{{LAST_OUTPUT}}

REMINDER — These constraints are absolute:
- node.id must be 0-based sequential integers (0, 1, 2, …) with no gaps
- depends_on must only reference ids LOWER than the current node
- deep_summarizer depends_on MUST list ALL upstream data node ids — NEVER empty
- final llm_caller depends_on MUST point to the previous node — NEVER empty
- final_output_node must equal the id of the last node in the plan
- Every tool and function must EXACTLY match the registry
- deep_summarizer text input: use {{STEPS.N.response}}, never {{STEPS.N}}
- news_fetcher: standalone only, no articles parameter, depends_on: []

TOOL REGISTRY:
{{TOOL_REGISTRY}}

USER REQUEST:
{{USER_REQUEST}}

Return ONLY the corrected JSON. No prose. No markdown.
"""

SYNTAX_REPAIR_PROMPT = """\
You are a strict JSON syntax fixer.
Fix ONLY the syntax. Do not change content.
Return ONLY a single valid JSON object. No prose, no markdown fences.

<<<BROKEN_JSON>>>
{{BROKEN_JSON}}
<<<END>>>

Error: {{PARSE_ERROR}}

Fixed JSON:
"""


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _clean_json_output(text: str) -> str:
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


def _build_registry_index(available_tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {meta["name"]: meta for meta in available_tools if meta.get("name")}


def _validate_plan_constraints(plan_obj: Dict[str, Any]) -> Dict[str, Any]:
    violations = []
    warnings = []
    nodes = plan_obj.get("nodes", [])

    llm_calls = sum(1 for n in nodes if n.get("tool") == "llm_caller")
    if llm_calls > 20:
        violations.append(f"Excessive LLM usage: {llm_calls} calls (limit: 20)")
    if llm_calls > 15:
        warnings.append(f"High LLM usage: {llm_calls} calls")

    code_assistant_nodes = sum(1 for n in nodes if n.get("tool") == "code_assistant")
    if code_assistant_nodes > 2:
        violations.append(
            f"Anti-pattern: {code_assistant_nodes} code_assistant nodes. "
            "Use ONE code_agent node for coding tasks."
        )

    # Detect news_fetcher chained after google_search (the bug we just fixed)
    node_map = {n["id"]: n for n in nodes}
    for n in nodes:
        if n.get("tool") == "news_fetcher":
            for dep_id in n.get("depends_on", []):
                dep = node_map.get(dep_id, {})
                if dep.get("tool") == "google_search":
                    violations.append(
                        f"Node {n['id']}: news_fetcher chained after google_search. "
                        "news_fetcher must be standalone."
                    )

    # Detect deep_summarizer with empty depends_on — root cause of empty input bug
    for n in nodes:
        if n.get("tool") == "deep_summarizer":
            if not n.get("depends_on"):
                violations.append(
                    f"Node {n['id']}: deep_summarizer has empty depends_on. "
                    "It MUST list all upstream data node ids e.g. depends_on: [0, 1]"
                )

    # Detect final node (final_output_node) with empty depends_on
    final_id = plan_obj.get("final_output_node")
    if final_id is not None:
        final_node = node_map.get(final_id, {})
        if final_node.get("id") is not None and not final_node.get("depends_on") and len(nodes) > 1:
            violations.append(
                f"Node {final_id} (final_output_node) has empty depends_on. "
                "The final node must depend on the previous node."
            )

    # Detect deep_summarizer using bare refs instead of dotted path
    for n in nodes:
        if n.get("tool") == "deep_summarizer":
            text_input = n.get("inputs", {}).get("text", "")
            import re
            bare_refs = re.findall(r"\{\{STEPS\.\d+\}\}", text_input)
            if bare_refs:
                violations.append(
                    f"Node {n['id']}: deep_summarizer uses bare refs {bare_refs}. "
                    "Must use {{STEPS.N.response}} dotted path."
                )

    return {"valid": len(violations) == 0, "violations": violations, "warnings": warnings}


def _detect_capability_gaps(plan_obj: Dict[str, Any], available_tools: Dict[str, Any]) -> Dict[str, Any]:
    gaps = []
    suggestions = []
    nodes = plan_obj.get("nodes", [])

    for node in nodes:
        if node.get("tool") == "llm_caller":
            thought = node.get("thought", "").lower()
            prompt = node.get("inputs", {}).get("prompt", "").lower()
            if any(kw in thought or kw in prompt for kw in ["cluster", "group articles", "categorize articles"]):
                gaps.append("Article clustering requested but news_clusterer not available")

    return {"has_gaps": len(gaps) > 0, "gaps": gaps, "suggestions": suggestions}


# ============================================================
# PLAN VALIDATION (DAG + SCHEMA)
# ============================================================

def _validate_plan(plan: Dict[str, Any], registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {"ok": False, "error": "Plan is not a JSON object."}

    if plan.get("status") == "error":
        return {"ok": True, "plan": plan}

    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {"ok": False, "error": "Missing or empty 'nodes' list."}

    id_set = set()
    for n in nodes:
        nid = n.get("id")
        if not isinstance(nid, int):
            return {"ok": False, "error": "Every node.id must be an integer."}
        if nid in id_set:
            return {"ok": False, "error": f"Duplicate node id {nid}."}
        id_set.add(nid)

    for n in nodes:
        nid = n["id"]
        tool = n.get("tool")
        func = n.get("function")
        inputs = n.get("inputs", {})
        depends_on = n.get("depends_on", [])

        # Sanitize retry
        try:
            n["retry"] = max(0, int(n.get("retry", 2)))
        except (TypeError, ValueError):
            n["retry"] = 2

        # Sanitize on_fail
        if n.get("on_fail") not in ("halt", "continue"):
            n["on_fail"] = "halt"

        # Sanitize timeout
        try:
            n["timeout"] = max(1, int(n.get("timeout", 60)))
        except (TypeError, ValueError):
            n["timeout"] = 60

        if not tool or not func:
            return {"ok": False, "error": f"Node {nid}: missing 'tool' or 'function'."}

        if tool not in registry:
            return {"ok": False, "error": f"Node {nid}: tool '{tool}' not in registry."}

        meta = registry[tool]
        if func != meta.get("function"):
            return {"ok": False, "error": f"Node {nid}: invalid function '{func}' for tool '{tool}' (expected '{meta.get('function')}')."}

        if not isinstance(inputs, dict):
            return {"ok": False, "error": f"Node {nid}: 'inputs' must be an object."}

        props = (meta.get("parameters") or {}).get("properties") or {}
        required = (meta.get("parameters") or {}).get("required") or []

        for key in inputs:
            if key not in props:
                return {"ok": False, "error": f"Node {nid}: invalid input '{key}' for tool '{tool}'."}

        for req in required:
            if req not in inputs:
                return {"ok": False, "error": f"Node {nid}: missing required input '{req}' for tool '{tool}'."}

        if not isinstance(depends_on, list):
            return {"ok": False, "error": f"Node {nid}: 'depends_on' must be a list."}

        for dep in depends_on:
            if not isinstance(dep, int):
                return {"ok": False, "error": f"Node {nid}: depends_on contains non-int id {dep}."}
            if dep not in id_set:
                return {"ok": False, "error": f"Node {nid}: depends_on references unknown id {dep}."}
            if dep >= nid:
                return {"ok": False, "error": f"Node {nid}: depends_on id {dep} must be < {nid}."}

    fon = plan.get("final_output_node")
    if not isinstance(fon, int) or fon not in id_set:
        return {"ok": False, "error": "Invalid or missing 'final_output_node' id."}

    return {"ok": True, "plan": plan}


# ============================================================
# LLM CALL HELPERS
# ============================================================

def _call_llm(prompt: str, model: str = None) -> Dict[str, Any]:
    target_model = model or PLANNER_MODEL
    try:
        resp = call_llm(prompt, model=target_model)
    except TypeError:
        resp = call_llm(prompt)

    if resp.get("status") != "success":
        return {"status": "error", "error": resp.get("error", "Planner LLM call failed")}
    return {"status": "success", "raw": resp.get("response", "")}


def _call_llm_for_plan(prompt: str) -> Dict[str, Any]:
    return _call_llm(prompt, model=PLANNER_MODEL)


def _call_llm_for_syntax_fix(broken_json: str, parse_error: str) -> Dict[str, Any]:
    prompt = SYNTAX_REPAIR_PROMPT \
        .replace("{{BROKEN_JSON}}", broken_json) \
        .replace("{{PARSE_ERROR}}", parse_error)
    return _call_llm(prompt, model=PLANNER_MODEL)


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def plan_task(user_msg: str, available_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compiles a user request into a validated JSON DAG.
    Uses a dedicated planner model for reliable structured output.
    """
    registry = _build_registry_index(available_tools)
    minimal_view = [
        {
            "name": meta.get("name"),
            "description": meta.get("description"),
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
            prompt = PLANNER_SYSTEM_PROMPT \
                .replace("{{TOOL_REGISTRY}}", registry_str) \
                .replace("{{USER_REQUEST}}", user_msg)
        else:
            prompt = REPAIR_PROMPT_TEMPLATE \
                .replace("{{TOOL_REGISTRY}}", registry_str) \
                .replace("{{LAST_OUTPUT}}", last_raw) \
                .replace("{{ERROR_MSG}}", last_error) \
                .replace("{{USER_REQUEST}}", user_msg)

        logger.info("Planner LLM attempt %d/%d...", attempt + 1, MAX_PLANNER_ATTEMPTS)
        llm_result = _call_llm_for_plan(prompt)

        if llm_result.get("status") != "success":
            last_error = llm_result.get("error", "Planner LLM call failed.")
            continue

        raw_text = llm_result["raw"]
        last_raw = raw_text
        cleaned = _clean_json_output(raw_text)

        # JSON parse with syntax-fix fallback
        try:
            plan_obj = json.loads(cleaned)
        except Exception as parse_err:
            parse_msg = str(parse_err)
            logger.warning("JSON parse error attempt %d: %s — invoking syntax-fix", attempt + 1, parse_msg)
            fix_result = _call_llm_for_syntax_fix(cleaned, parse_msg)
            if fix_result.get("status") != "success":
                last_error = f"Syntax fix failed: {fix_result.get('error', 'unknown')}"
                continue
            fixed_clean = _clean_json_output(fix_result["raw"])
            last_raw = fixed_clean
            try:
                plan_obj = json.loads(fixed_clean)
            except Exception as e2:
                last_error = f"JSON still invalid after syntax fix: {e2}"
                continue

        # Structural validation
        validation = _validate_plan(plan_obj, registry)
        if not validation["ok"]:
            last_error = validation["error"]
            logger.warning("Planner validation failed attempt %d: %s", attempt + 1, last_error)
            continue

        validated_plan = validation["plan"]
        if "status" not in validated_plan:
            validated_plan["status"] = "success"

        # Constraint + anti-pattern checks
        constraint_check = _validate_plan_constraints(validated_plan)
        if not constraint_check["valid"]:
            last_error = "; ".join(constraint_check["violations"])
            logger.warning("Plan constraint violation attempt %d: %s", attempt + 1, last_error)
            continue

        for w in constraint_check.get("warnings", []):
            logger.warning("Plan warning: %s", w)

        # Capability gap detection (soft warnings only)
        cap_check = _detect_capability_gaps(validated_plan, registry)
        for gap in cap_check.get("gaps", []):
            logger.warning("Capability gap: %s", gap)

        logger.info("Planner produced a valid DAG with %d node(s).", len(validated_plan.get("nodes", [])))
        return validated_plan

    logger.error("Planner failed after %d attempts: %s", MAX_PLANNER_ATTEMPTS, last_error)
    return {
        "status": "error",
        "error": f"Unable to build valid plan. Reason: {last_error}",
        "raw": last_raw,
    }