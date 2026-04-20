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

PLANNING_CAPABILITY_PROMPT = """
You are SMITH 3.0: A powerful, multi-purpose, Zero-Trust Agent Runtime.
You are not restricted to finance. You are an omni-tool reasoning engine capable of general web research, technical analysis, coding assistance, mathematical computation, and data aggregation.

Your job is to transform a user request into a JSON execution graph ("the plan").
You do NOT write text. You do NOT answer the request directly. You ONLY produce the JSON graph.
"""

PLANNER_SYSTEM_PROMPT = PLANNING_CAPABILITY_PROMPT + """
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
  "on_fail": "continue",
  "timeout": 45
}

──────────────────── ON_FAIL POLICY ────────────────────
  "continue" — Default for data-fetching tools (google_search, news_fetcher, finance_fetcher,
               weather_fetcher, arxiv_search). Downstream nodes still execute even if this
               node fails. Use when partial results are acceptable.
  "halt"     — Use ONLY for critical nodes whose output is absolutely required.
               When a halt-node fails, ALL downstream dependents are skipped.
               Reserve for: authentication steps, critical data transforms, or
               nodes where running dependents without this data would be meaningless.

──────────────────── MULTI-TOOL RULES ────────────────────
1. IDS MUST be 0-based indices (0, 1, 2...).
2. Identify dependencies explicitly. If Step 1 needs Step 0's output, Step 1 MUST have "depends_on": [0].
3. Use "llm_caller" SPARINGLY for logical processing, summarization, or decision making.
4. The FINAL node must be the one producing the user's answer (usually an llm_caller node).

──────────────────── COST CONSTRAINTS ────────────────────
⚠️ MATCH PLAN DEPTH TO TASK COMPLEXITY:
  - Simple lookups ("what is X?", "what's the weather?"): 1–2 nodes
  - Research questions ("explain X", "find news about Y"): 3–5 nodes
  - Complex multi-part tasks ("design", "analyze and compare", "research + synthesize"): 6–30 nodes
  - Do NOT artificially truncate a complex task into a shallow DAG
  - Do NOT artificially pad a simple task with extra nodes

Costs per node type:
  - Data tools (google_search, finance_fetcher, weather_fetcher, arxiv_search): 1 point
  - LLM reasoning (llm_caller): 3 points
  - Coding (code_agent): 5 points

CONSTRAINT: Max 15 llm_caller nodes. Sub-agents count separately.
PENALTY: Plans with >15 llm_caller nodes will be rejected.

──────────────────── TASK TYPE CLASSIFICATION ────────────────────
Before building any plan, classify the request as ONE of:

TYPE A — FACTUAL LOOKUP
  Keywords: "what is X today", "current price", "latest news about", "who won"
  Needs: real-time data → google_search/finance_fetcher/news_fetcher + llm_caller to summarise
  Pattern: [data_tool × N] → [llm_caller final synthesis]

TYPE B — KNOWLEDGE SYNTHESIS / ANALYTICAL WRITING
  Keywords: "design", "explain how", "compare", "analyze", "describe the architecture of",
            "what are the tradeoffs", "how does X work", "write a guide on", "iteratively refine"
  ⚠️ The answer comes from the MODEL's knowledge, NOT from web search snippets.
  Web search snippets for these topics are low-quality noise. DO NOT spam google_search for
  topics like "AI safety alignment" or "DAG execution" — these return snippets, not explanations.
  Needs: structured LLM writing, broken into sections
  Pattern: [optional: 1-2 targeted google_search for specific facts] →
           [sub_agent per major section] → [llm_caller to combine into final doc]

  ✅ CORRECT — "Design an agentic AI system with DAG execution, memory, safety...":
    Node 0: llm_caller(prompt="Write a detailed section on: Agent Architecture (planner, executor, critic, router, memory manager, evaluator). Define each role, failure modes prevented, single vs multi-agent tradeoffs. Use ASCII diagrams.")
    Node 1: llm_caller(prompt="Write a detailed section on: DAG-based Control Flow. Cover node execution rules, dependency resolution, conditional branching, retry/rollback strategies. Use ASCII diagrams.")
    Node 2: llm_caller(prompt="Write a detailed section on: Planning & Reasoning. Compare ReAct, Tree-of-Thought, Graph-of-Thought. Justify a hybrid approach.")
    Node 3: llm_caller(prompt="Write a detailed section on: Memory Systems (short-term, long-term, episodic, semantic). Cover write/read policies and decay.")
    Node 4: llm_caller(prompt="Write a detailed section on: Tool Use, Self-Reflection, Safety & Alignment, Observability, Evaluation, and Production Scalability. Be specific and critical.")
    Node 5: llm_caller(prompt="Combine into a comprehensive design document:\n{{STEPS.0.response}}\n{{STEPS.1.response}}\n{{STEPS.2.response}}\n{{STEPS.3.response}}\n{{STEPS.4.response}}")

  ❌ WRONG — 10 parallel google_search nodes for "AI safety alignment", "DAG execution AI", etc.
     then ONE llm_caller to summarise all of them. This creates too much low-quality context.

TYPE C — HYBRID (facts + analysis)
  Keywords: "research X and write a report", "find data on X and explain implications"
  Needs: 1-3 targeted searches for current facts, then analytical writing grounded in those facts
  Pattern: [google_search × 1-3 targeted] → [llm_caller writes analysis referencing {{STEPS.N.response}}]

──────────────────── TOOL DOMAIN AWARENESS ────────────────────
⚠️ NEVER ask llm_caller to produce:
  - Real-time facts (current weather, stock prices) → Use data tools
  - Factual claims without sources → Use google_search or other data tools
  - Article clustering → Use news_clusterer

✅ DO USE llm_caller for:
  - Explaining concepts it was trained on (architecture, algorithms, tradeoffs)
  - Writing structured documents, guides, analyses, comparisons
  - Any output where quality > real-time accuracy

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

──────────────────── TOOL INPUTS & CONTEXT PASSING ────────────────────
Use {{STEPS.N}} to pass upstream results to downstream nodes.

⚡ CONTEXT PASSING STRATEGIES (pick the right one):

1. BARE REFERENCE — passes the full result (use for structured data tools):
   "articles": "{{STEPS.0}}"
   → Best for: news_fetcher, finance_fetcher, google_search results

2. DOTTED PATH — extracts a single field (use to avoid passing huge blobs):
   "prompt": "Summarize this: {{STEPS.0.response}}"
   → Best for: passing llm_caller, code_agent, or url_reader output to the next node
   Common sub-variables:
     - {{STEPS.N.response}}   — the human-readable answer text
     - {{STEPS.N.primary_code}} — for code_agent outputs only
     - {{STEPS.N.result}}    — raw result dict

3. PIPE DEFAULT — graceful fallback for optional dependencies:
   "prompt": "Use this if available: {{STEPS.0 | default: 'no data'}}"
   → Best for: optional searches where failure is acceptable

4. SUMMARIZER NODE PATTERN — insert a condensing llm_caller before a synthesis node
   when upstream data from multiple nodes is large:
   Node N:   llm_caller(prompt="In 3 bullet points summarize: {{STEPS.0.response}} {{STEPS.1.response}}")
   Node N+1: llm_caller(prompt="Final synthesis using summaries: {{STEPS.N.response}}")
   → Use when: ≥3 upstream nodes each produce ≥500 words of text

⚠️ RULE: Prefer DOTTED PATH ({{STEPS.N.response}}) over bare refs for llm_caller outputs.
   Bare refs on llm_caller outputs dump the full dict including metadata — wasteful.

──────────────────── CODING PIPELINE ────────────────────
🔥 Smith has TWO coding tools. Use the right one:

━━━ code_agent (USE THIS FOR TASKS WHERE THE OUTPUT IS CODE) ━━━
Full agentic pipeline: searches real documentation, generates informed code,
self-reviews and iterates until confident. Always higher quality than code_assistant.

USE code_agent ONLY when the PRIMARY DELIVERABLE is a runnable code file:
  • User says: "write", "build", "implement", "create a script/function/class"
  • User asks for "production-ready", "PR-ready", "fully secure" code
  • The output is a .py/.js/.ts/etc. file the user will run

❌ NEVER use code_agent when:
  • User asks to EXPLAIN, ANALYZE, COMPARE, or DESCRIBE something (even if it's about code)
  • User asks to DESIGN a system or architecture (answer in prose, not code)
  • User asks HOW something works, or WHY a design decision was made
  • The prompt says "tell me", "explain", "what is", "how does", "compare", "research"
  • The task is research, analysis, documentation, or a technical write-up
  → For these, use google_search + llm_caller (the research pipeline)

Parameters:
  task:        FULL description of everything required. Include:
               - Exact libraries (e.g. "use httpx NOT requests")
               - All constraints: async, typed, PR-ready, rate-limited, etc.
               - All features requested
  language:    Target language (default: python)
  skip_search: false (default) — searches real docs first (RECOMMENDED)
               true — skip search, faster but no doc context

⚠️ ALWAYS ONE SINGLE code_agent NODE. Never chain it.

EXAMPLE — "Write a Python async web scraper with httpx, retries, proxy, rate limiting, PR-ready":
  ✅ Node 0: code_agent(
       task="Production-ready async Python web scraper.
             MUST use httpx (not requests), BeautifulSoup.
             Include: async/await, asyncio.Semaphore rate limiter,
             exponential backoff with jitter, rotating modern user-agents (2024),
             proxy= parameter (not proxies=), structured logging,
             custom ScraperError exception, type hints, full docstrings.
             No unused imports. PR-ready.",
       language="python"
     )

COUNTER-EXAMPLE — "Design, analyze, and explain an agentic AI system with DAG execution...":
  ❌ NOT code_agent — this is a research/architecture question, not "write code"
  ✅ Use google_search + llm_caller to produce a structured analysis document

━━━ code_assistant (USE ONLY FOR SIMPLE TASKS) ━━━
Single LLM call, no research, no iteration. Use ONLY for:
  • operation="explain" — explain existing code
  • operation="fix" — fix a small bug (paste the broken code)
  • operation="review" — quick code review (paste the code)
  • Very simple one-liner generation (no complex requirements)

  ❌ NEVER use llm_caller for any coding task.
  ❌ NEVER chain multiple coding tool nodes for a single deliverable.
  ✅ code_agent for all real coding work → one node → great output.

──────────────────── NEWS_FETCHER PIPELINE ────────────────────
🔥 When the user asks for NEWS ARTICLES, ALWAYS use this exact 2-node pattern:

  Node 0: google_search  (on_fail: "continue")
    - query: a journalist-style keyword string targeting open news outlets.
      Append "site:reuters.com OR site:bbc.com OR site:apnews.com OR site:aljazeera.com"
      to bias results toward open, non-paywalled sources.
    - num_results: top_n + 3 (to account for paywalled/blocked URLs that return empty bodies).
      If the user does not specify top_n, default top_n = 5, so num_results = 8.
    ⚠️  google_search MUST use on_fail: "continue" — news_fetcher has its own
        NewsAPI fallback and can still produce results even if google_search fails.

  Node 1: news_fetcher  (depends_on: [0], on_fail: "continue")
    - articles: "{{STEPS.0}}"   ← this passes google_search results as a raw object
    - raw_query: the ORIGINAL user message (verbatim, NOT the optimized keywords)
    - fetch_body: true

  ❌ NEVER pass the raw user sentence as the google_search query — always optimize it.
  ❌ NEVER omit the "articles" input for news_fetcher — it MUST receive "{{STEPS.0}}".
  ✅ The final node (llm_caller) synthesizes the fetched articles for the user.

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

    # Hard limit: protect against runaway LLM chains
    # 20 = generous enough for complex multi-section papers
    if llm_calls > 20:
        violations.append(f"Excessive LLM usage: {llm_calls} calls (limit: 20)")

    if llm_calls > 15:
        warnings.append(
            f"High LLM usage: {llm_calls} calls — ensure each is necessary"
        )

    # Shallow DAG warning: complex multi-section requests need deeper plans
    total_nodes = len(nodes)
    # Detect multi-part requests by counting nodes with code_assistant
    code_assistant_nodes = sum(1 for n in nodes if n.get("tool") == "code_assistant")
    if code_assistant_nodes > 2:
        # Multiple code_assistant calls for what should be a single task is an antipattern
        violations.append(
            f"Anti-pattern: {code_assistant_nodes} code_assistant nodes chained together. "
            "Use ONE code_agent node for coding tasks, or llm_caller for analysis."
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
        # ── Auto-sanitize fields that weak fallback models often misformat ──
        # Coerce 'retry' to non-negative int (default 2)
        raw_retry = n.get("retry")
        try:
            retry = int(raw_retry)
            if retry < 0:
                retry = 2
        except (TypeError, ValueError):
            if raw_retry is not None:
                import logging as _log
                _log.getLogger("smith.planner").warning(
                    f"Node {n.get('id')}: coerced 'retry' from {raw_retry!r} to 2"
                )
            retry = 2
        n["retry"] = retry

        # Coerce 'on_fail' to 'halt' or 'continue' (default 'halt')
        raw_on_fail = n.get("on_fail", "halt")
        if raw_on_fail not in ("halt", "continue"):
            import logging as _log
            _log.getLogger("smith.planner").warning(
                f"Node {n.get('id')}: coerced 'on_fail' from {raw_on_fail!r} to 'halt'"
            )
            raw_on_fail = "halt"
        on_fail = raw_on_fail
        n["on_fail"] = on_fail

        # Coerce 'timeout' to positive int (default 60)
        raw_timeout = n.get("timeout")
        try:
            timeout = int(raw_timeout)
            if timeout <= 0:
                timeout = 60
        except (TypeError, ValueError):
            if raw_timeout is not None:
                import logging as _log
                _log.getLogger("smith.planner").warning(
                    f"Node {n.get('id')}: coerced 'timeout' from {raw_timeout!r} to 60"
                )
            timeout = 60
        n["timeout"] = timeout

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

        # retry/on_fail/timeout already sanitized above — these are guaranteed valid

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
