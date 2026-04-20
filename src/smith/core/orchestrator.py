"""
Smith Orchestration Engine
-------------------------
Welcome to the brain of the operation! 🧠

This is where the magic happens. The Orchestrator takes the plan (DAG) creating by the Planner
and executes it step-by-step. It's like a conductor leading an orchestra of tools.

Here's how it flows:
    1. Planner says "Do X, then Y".
    2. Orchestrator says "On it!", runs X, gets the result, passes it to Y.
    3. Tool Loader grabs the actual code for X and Y.
    4. Safety first! If a tool is dangerous, we ask the human (you) for permission.
"""

import json
import logging
import re
import threading
import time
import traceback
import uuid
import sys
import concurrent.futures
from typing import Any, Callable, Dict, List, Generator, Set, Optional

# Third-party imports
# Third-party imports
try:
    from smith.config import config
    from smith.tools import LLM_CALLER
    from smith import planner
    from smith import registry  # Static registry instead of MongoDB
    from smith import tool_loader
    from smith.core.validators import validate_tool_authority  # Authority validation
    from smith.core.resource_lock import get_lock_manager  # Resource locking
    from smith.core.agent_state import get_state_manager  # noqa: F401
    from smith.core.template_engine import resolve_llm_prompt, resolve_step_reference  # P1/P2/P6
    from smith.core.input_validators import validate_inputs  # P3
    from smith.core.fabrication_guard import GroundTruthRegistry, check_and_redact  # P4
    from smith.core.synthesis_router import select_synthesis_model  # I1
    from smith.core.cache_manager import CacheManager  # I5
    from smith.core.run_context import RunContextManager  # RAG step accumulator
    from smith.core.synthesis_engine import run_synthesis  # Critic+RAG synthesis
except ImportError as e:
    # Fail fast if the package structure is invalid
    sys.stderr.write(
        f"CRITICAL: Failed to import core modules. Ensure 'smith' is installed.\nError: {e}\n"
    )
    sys.exit(1)

# Initialize Structured Logger
logger = logging.getLogger("smith.orchestrator")

TRACE_VERSION = "3.0"
PLACEHOLDER_RE = re.compile(r"\{\{\s*STEPS\.(\d+)\.([^}]+)\}\}", re.IGNORECASE)
STEP_REF_RE = re.compile(r"^\{\{\s*STEPS\.(\d+)\s*\}\}$", re.IGNORECASE)

# No longer need DB service - using static registry


def execute_with_timeout(
    fn: Callable, args: Dict[str, Any], timeout: float
) -> Dict[str, Any]:
    """
    Run a tool function in a thread with a hard timeout.
    Normalize output to {status, result|error}.
    """
    res: Dict[str, Any] = {"ok": False, "value": None, "error": None}

    def target():
        try:
            res["value"] = fn(**args)
            res["ok"] = True
        except Exception as exc:
            res["error"] = str(exc)
            if config.debug_mode:
                traceback.print_exc()

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)

    if th.is_alive():
        return {"status": "error", "error": f"Execution timed out ({timeout}s)"}

    if not res["ok"]:
        return {"status": "error", "error": res["error"]}

    out = res["value"]
    if isinstance(out, dict):
        if "status" in out:
            return out
        return {"status": "success", "result": out}
    return {"status": "success", "result": out}


# ============================================================================ #
# RATE LIMITER                                                                #
# ============================================================================ #


class RateLimiter:
    """
    Simple token-bucket-style rate limiter (1 request per interval).
    """

    # Default delays in seconds
    DEFAULT_LIMITS = {
        "llm_caller": 0.2,  # Minimal delay between LLM calls
        "google_search": 0.1,
        "news_fetcher": 0.1,
        "weather_fetcher": 0.05,
    }

    def __init__(self):
        self._last_call: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait_if_needed(self, tool_name: str):
        delay = self.DEFAULT_LIMITS.get(tool_name, 0.0)
        if delay <= 0:
            return

        with self._lock:
            now = time.time()
            last = self._last_call.get(tool_name, 0.0)
            elapsed = now - last

            if elapsed < delay:
                sleep_time = delay - elapsed
                time.sleep(sleep_time)
                # Update time after sleep
                self._last_call[tool_name] = time.time()
            else:
                self._last_call[tool_name] = now


# ============================================================================ #
# SMALL HELPERS                                                               #
# ============================================================================ #


def safe_serialize(obj: Any) -> str:
    """Safe JSON dump for logs / prompts."""
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _unwrap_result_container(data: Any) -> Any:
    """
    Normalize common result container patterns:
    - {"status": "success", "result": ...}
    - {"status": "success", "results": [...]}
    """
    if not isinstance(data, dict):
        return data
    if "result" in data and len(data) <= 4:
        return data["result"]
    if "results" in data and len(data) <= 4:
        return data["results"]
    return data


def _deep_get(obj: Any, path: str) -> Any:
    """
    Resolve dotted / indexed paths like `result.0.link` or `results[1].title`
    against the tool output.
    """
    obj = _unwrap_result_container(obj)
    # Normalize bracket indices to dots
    path = path.replace("[", ".").replace("]", "")
    parts = [p for p in path.split(".") if p]

    cur: Any = obj
    for key in parts:
        if isinstance(cur, dict):
            if key in cur:
                cur = cur[key]
            else:
                return None
        elif isinstance(cur, list):
            if key.isdigit():
                idx = int(key)
                if 0 <= idx < len(cur):
                    cur = cur[idx]
                else:
                    return None
            else:
                return None
        else:
            return None
    return cur


# ============================================================================ #
# ORCHESTRATOR (DAG-AWARE)                                                    #
# ============================================================================ #


def smith_orchestrator(
    user_msg: str,
    require_approval: bool = config.require_approval,
    exclude_tools: list = None,
    verify_finance: bool = False,
    cache_manager: "Optional[CacheManager]" = None,
    recent_context: str = "",
) -> Generator[Dict[str, Any], None, None]:
    """
    The Main Event Loop.

    This generator yields events so the UI (or CLI) can show you exactly what's happening
    in real-time. No more staring at a blank screen wondering if it hung!
    """
    run_id = str(uuid.uuid4())
    yield {
        "type": "status",
        "message": "Initializing planner...",
        "run_id": run_id,
        "trace_version": TRACE_VERSION,
    }

    # 1) Read tool registry (static JSON) ------------------------------------
    try:
        tools_list = registry.get_tools_registry()
        # Filter out excluded tools (e.g., sub_agent inside sub-agents)
        if exclude_tools:
            tools_list = [t for t in tools_list if t.get("name") not in exclude_tools]
        tool_registry = {t["name"]: t for t in tools_list}
    except Exception as e:
        msg = f"Failed to load tool registry: {e}"
        logger.error(msg)
        yield {"type": "error", "message": msg, "run_id": run_id}
        return

    # 2) Call planner -------------------------------------------------------
    # Inject recent short-term context + long-term memory to reduce redundant tool calls.
    _planning_sections: List[str] = []

    if recent_context and recent_context.strip():
        _planning_sections.append(
            "[Recent conversation context]\n"
            f"{recent_context.strip()}\n"
            "[End recent conversation context]\n"
            "Guidance: if this is a follow-up to very recent time-sensitive data, "
            "prefer reusing the recent context instead of re-calling live APIs unless "
            "the user explicitly asks for refresh, latest, live, current, or update."
        )

    if config.memory_enabled:
        try:
            from smith.memory import get_memory_manager

            _mem_ctx = get_memory_manager().read_context(user_msg)
            if _mem_ctx:
                _planning_sections.append(
                    f"[Relevant context from past sessions]\n{_mem_ctx}\n"
                    f"[End memory context]"
                )
        except Exception as _mem_err:
            logger.debug(f"Memory read skipped: {_mem_err}")

    _planning_sections.append(f"Current query: {user_msg}")
    _planning_msg = "\n\n".join(_planning_sections)

    try:
        plan = planner.plan_task(_planning_msg, tools_list)
        if not isinstance(plan, dict):
            raise RuntimeError("Planner returned non-dict result")
        if plan.get("status") == "error":
            raise RuntimeError(plan.get("error", "Planner reported error"))

        # Try DAG first
        nodes = None
        if isinstance(plan.get("nodes"), list):
            nodes = plan["nodes"]
        elif isinstance(plan.get("steps"), list):
            # legacy shape, treat as nodes
            nodes = plan["steps"]
        elif isinstance(plan.get("plan"), dict):
            inner = plan["plan"]
            if isinstance(inner.get("nodes"), list):
                nodes = inner["nodes"]
            elif isinstance(inner.get("steps"), list):
                nodes = inner["steps"]

        if not isinstance(nodes, list) or not nodes:
            raise RuntimeError("Planner produced no nodes/steps")

    except Exception as e:
        msg = f"Planning logic failed: {e}"
        logger.exception(msg)
        yield {"type": "error", "message": msg, "run_id": run_id}
        return

    logger.info(f"Planner produced a valid DAG with {len(nodes)} node(s).")

    # Emit plan created event for CLI/UI to capture
    yield {"type": "plan_created", "plan": plan, "run_id": run_id}

    # 3) Parallel Execution Setup -------------------------------------------
    trace: List[Optional[Dict[str, Any]]] = [None] * len(nodes)
    completed: Set[int] = set()
    submitted: Set[int] = set()
    futures: Dict[concurrent.futures.Future, tuple] = {}
    cache_hits: List[int] = []  # step indices that were served from cache

    # Rate limiter logic (simple local instance)
    limiter = RateLimiter()

    # Run context manager: accumulates step outputs for RAG synthesis
    run_ctx = RunContextManager(run_id)
    try:
        run_ctx.cleanup()  # Remove stale run files (keep last 20)
    except Exception:
        pass

    # 4) Main Parallel Loop ------------------------------------------------
    # 4) Main Parallel Loop ------------------------------------------------
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=config.max_workers
    ) as executor:
        # 1. Map Node IDs to List Indices
        id_to_idx = {}
        for idx, node in enumerate(nodes):
            nid = node.get("id")
            if nid is not None:
                id_to_idx[nid] = idx

        # 2. Validate and Normalize Dependencies
        for idx, node in enumerate(nodes):
            original_deps = node.get("depends_on", [])

            # If no dependencies, auto-chain (fallback)
            if original_deps is None:
                node["depends_on"] = [idx - 1] if idx > 0 else []
                continue

            normalized_deps = []
            for d in original_deps:
                # If d is an ID, map it to index
                if d in id_to_idx:
                    mapped_idx = id_to_idx[d]
                    if mapped_idx < idx:  # Ensure DAG (dependency must come before)
                        normalized_deps.append(mapped_idx)
                    else:
                        logger.warning(
                            f"Ignored cycle/forward dependency: Node {node.get('id')} depends on {d} (Index {mapped_idx})"
                        )
                elif isinstance(d, int) and 0 <= d < idx:
                    # Fallback: Assume it's already an index if it's valid
                    normalized_deps.append(d)
                else:
                    logger.warning(
                        f"Ignored invalid dependency: Node {node.get('id')} depends on {d}"
                    )

            node["_normalized_deps"] = normalized_deps

        while len(completed) < len(nodes):
            # --- A. Submit Available Nodes ---
            # We iterate through all nodes to find those whose dependencies are met
            # and haven't been submitted yet.
            for idx, node in enumerate(nodes):
                if idx in submitted:
                    continue

                # Use normalized dependencies (indices) for execution logic
                deps = node.get("_normalized_deps", [])
                if not all(d in completed for d in deps):
                    continue

                # Check if any upstream dependency failed
                failed_deps = [
                    d for d in deps
                    if trace[d] and trace[d].get("status") != "success"
                ]

                # Determine if any failed dep has on_fail: "halt"
                # If so, this node must be skipped. If ALL failed deps
                # have on_fail: "continue", this node can still run.
                has_halt_failure = False
                for d in failed_deps:
                    dep_node = nodes[d]
                    if dep_node.get("on_fail", "halt") == "halt":
                        has_halt_failure = True
                        break

                tool_name = node.get("tool")
                fn_name = node.get("function")
                step_id = f"{run_id}-step-{idx}"

                # Use metadata from registry
                meta = tool_registry.get(tool_name)
                if not meta:
                    logger.error(f"Tool {tool_name} removed from registry during run.")
                    # Mark as failed in trace
                    trace[idx] = {
                        "status": "error",
                        "error": "Tool missing",
                        "step_index": idx,
                    }
                    completed.add(idx)
                    submitted.add(idx)
                    continue

                if has_halt_failure:
                    # Skip execution — a critical upstream dep failed with halt policy
                    halt_deps = [
                        d for d in failed_deps
                        if nodes[d].get("on_fail", "halt") == "halt"
                    ]
                    logger.warning(
                        f"Skipping Step {idx} ({tool_name}) — upstream node(s) "
                        f"{halt_deps} failed with on_fail='halt'."
                    )
                    trace[idx] = {
                        "status": "skipped",
                        "error": f"Upstream dependency failed (halt policy on nodes {halt_deps})",
                        "step_index": idx,
                    }
                    completed.add(idx)
                    submitted.add(idx)
                    continue

                # If we reach here with failed_deps, they all have on_fail: "continue"
                is_partial = len(failed_deps) > 0
                if is_partial:
                    logger.info(
                        f"Step {idx} ({tool_name}) running with partial upstream — "
                        f"nodes {failed_deps} failed but had on_fail='continue'."
                    )

                # --- Authorization (Blocking Check) ---
                # Check dangerous flag on the main thread to allow synchronous user interaction
                if require_approval and meta.get("dangerous", False):
                    yield {
                        "type": "approval_required",
                        "tool": tool_name,
                        "function": fn_name,
                        "run_id": run_id,
                        "step_id": step_id,
                        "message": f"Security: Tool '{tool_name}' requires approval.",
                    }
                    # Currently, CLI handles the yield and returns control.
                    # If this was async, we'd need a wait.
                    # Assume positive for now or strict halt?
                    # In this synchronous generator, the UI must have 'authorized' logic implicitly
                    # or restart the generator.
                    # For CLI, we prompt. If CLI continues, it means "Authorized".
                    # Real systems might use a callback or event.

                yield {
                    "type": "step_start",
                    "tool": tool_name,
                    "function": fn_name,
                    "thought": node.get("thought", "Executing tool..."),
                    "step_index": idx,
                    "run_id": run_id,
                    "step_id": step_id,
                    "message": f"Step {idx + 1}: {tool_name}",
                }

                # Prepare Inputs
                raw_args = node.get("inputs") or node.get("args") or {}
                safe_args = dict(raw_args)

                # --- FIX P1/P2/P6: Use template engine for llm_caller prompts ---
                # Resolving placeholders must be done HERE (main thread) because `trace` is consistent here
                if tool_name == "llm_caller":
                    p = safe_args.get("prompt", "")
                    if isinstance(p, str):
                        # Use new template engine: labeled headers, null fallback, budget truncation
                        safe_args["prompt"] = resolve_llm_prompt(p, trace, nodes)

                # General resolver: replace {{STEPS.N}} references with raw objects for ALL tools
                for key, value in list(safe_args.items()):
                    if isinstance(value, str):
                        # Case 1: entire value is a bare {{STEPS.N}} — resolve to raw object
                        m = STEP_REF_RE.match(value.strip())
                        if m:
                            # --- FIX P2: Use template engine's resolver with null handling ---
                            resolved = resolve_step_reference(value, trace)

                            # --- CODE UNWRAPPING: when 'code' key gets a code_assistant result dict,
                            # extract the actual code string rather than passing the raw dict ---
                            if key == "code" and isinstance(resolved, dict):
                                # code_assistant returns {status, response, primary_code, code_blocks, ...}
                                if "primary_code" in resolved:
                                    resolved = resolved["primary_code"]
                                elif "response" in resolved:
                                    # Strip surrounding markdown fences if needed
                                    import re as _re
                                    code_match = _re.search(r"```\w*\n?(.*?)```", resolved["response"], _re.DOTALL)
                                    resolved = code_match.group(1).strip() if code_match else resolved["response"]

                            safe_args[key] = resolved
                        else:
                            # Case 2: value contains {{STEPS.N.path.subpath}} dotted references
                            # These need to be resolved inline (e.g. Gmail subject/body)
                            def _resolve_dotted(match):
                                idx = int(match.group(1))
                                path = match.group(2).strip()
                                if idx < 0 or idx >= len(trace) or trace[idx] is None:
                                    logger.warning(f"Null substitution for STEPS.{idx}.{path}")
                                    return ""
                                entry = trace[idx]
                                if entry.get("status") not in ("success",):
                                    return f"[Step {idx} unavailable]"
                                data = entry.get("result")
                                # Walk the dotted path
                                for part in path.split("."):
                                    if isinstance(data, dict):
                                        data = data.get(part)
                                    elif isinstance(data, (list, tuple)):
                                        try:
                                            data = data[int(part)]
                                        except (ValueError, IndexError):
                                            data = None
                                    else:
                                        data = None
                                    if data is None:
                                        break
                                if data is None:
                                    return ""
                                if isinstance(data, (dict, list)):
                                    return json.dumps(data, default=str)
                                return str(data)

                            resolved_str = PLACEHOLDER_RE.sub(_resolve_dotted, value)
                            if resolved_str != value:
                                safe_args[key] = resolved_str

                # --- FIX P3: Validate upstream input shapes before execution ---
                input_validation = validate_inputs(tool_name, safe_args)
                if not input_validation.get("valid", True):
                    reason = input_validation.get("reason", "invalid_input")
                    logger.warning(
                        f"Input validation failed for Step {idx} ({tool_name}): {reason}"
                    )
                    on_fail_policy = node.get("on_fail", "halt")
                    trace[idx] = {
                        "status": "error",
                        "error": reason,
                        "step_index": idx,
                        "tool": tool_name,
                        "duration": 0.0,
                    }
                    completed.add(idx)
                    submitted.add(idx)
                    yield {
                        "type": "step_complete",
                        "step_index": idx,
                        "tool": tool_name,
                        "function": fn_name,
                        "status": "error",
                        "payload": {"status": "error", "error": reason},
                        "run_id": run_id,
                        "step_id": step_id,
                        "duration": 0.0,
                    }
                    continue

                yield {
                    "type": "debug_args",
                    "args": safe_args,
                    "run_id": run_id,
                    "step_id": step_id,
                }

                # Apply Rate Limit (Blocking sleep if needed)
                limiter.wait_if_needed(tool_name)

                # Prepare Task Logic with Resource Locking
                def _run_node_logic(
                    _fn: Callable,
                    _args: Dict,
                    _meta: Dict,
                    _timeout: float,
                    _retries: int,
                    _tool_name: str,
                    _agent_id: str,
                ) -> Dict[str, Any]:
                    # Skip locking for sub_agent (spawns own orchestrator)
                    needs_lock = _tool_name != "sub_agent"
                    lock_mgr = None

                    if needs_lock:
                        lock_mgr = get_lock_manager()
                        lock_timeout = config.tool_lock_timeout
                        lock_acquired = lock_mgr.acquire_tool_lock(
                            _tool_name, _agent_id, timeout=lock_timeout
                        )
                        if not lock_acquired:
                            return {
                                "status": "error",
                                "error": (
                                    f"Could not acquire lock for {_tool_name} (timeout after {lock_timeout}s)"
                                ),
                            }

                    try:
                        _out = {"status": "error", "error": "Not run"}
                        for attempt in range(_retries + 1):
                            _out = execute_with_timeout(_fn, _args, _timeout)
                            if _out.get("status") == "success":
                                break
                            if attempt < _retries:
                                time.sleep(1)
                        return _out
                    finally:
                        if needs_lock and lock_mgr:
                            lock_mgr.release_tool_lock(_tool_name, _agent_id)

                # Load function
                try:
                    fn_obj = tool_loader.load_tool_function(meta["module"], fn_name)
                except Exception as e:
                    logger.error(f"Loader error: {e}")
                    trace[idx] = {"status": "error", "error": str(e), "step_index": idx}
                    completed.add(idx)
                    submitted.add(idx)
                    continue

                # Config parameters
                n_retry = int(node.get("retry", config.max_retries))
                n_timeout = float(node.get("timeout", config.default_timeout))

                # Sub-agents need much longer timeout (they run full orchestrator)
                if tool_name == "sub_agent":
                    n_timeout = max(n_timeout, 120.0)
                    n_retry = 0  # Don't retry sub-agents

                # code_agent runs an internal LLM loop (search + generate + critique × N)
                # It needs a long timeout and must NOT be retried — each retry burns the rate limit
                if tool_name == "code_agent":
                    n_timeout = max(n_timeout, 180.0)
                    n_retry = 0  # Never retry code_agent

                # Get current agent ID (or use run_id as fallback)
                agent_id = getattr(config, "_current_agent_id", run_id)

                # --- I5: Check run cache before submitting to thread pool ---
                cache_key = None
                if cache_manager is not None and config.cache_enabled:
                    cache_key = CacheManager.make_key(tool_name, safe_args)
                    cached_result = cache_manager.get(cache_key)
                    if cached_result is not None:
                        logger.info(f"Cache HIT for Step {idx} ({tool_name})")
                        trace_entry = {
                            "step_index": idx,
                            "tool": tool_name,
                            "function": fn_name,
                            "status": cached_result.get("status", "success"),
                            "quality": "cache_hit",
                            "violations": None,
                            "result": cached_result,
                            "duration": 0.0,
                            "cache_hit": True,
                        }
                        trace[idx] = trace_entry
                        completed.add(idx)
                        submitted.add(idx)
                        cache_hits.append(idx)
                        yield {
                            "type": "step_complete",
                            "step_index": idx,
                            "tool": tool_name,
                            "function": fn_name,
                            "status": cached_result.get("status", "success"),
                            "payload": cached_result,
                            "run_id": run_id,
                            "step_id": step_id,
                            "duration": 0.0,
                            "cache_hit": True,
                        }
                        continue

                # --- FIX P5: Record start_time for real duration tracking ---
                node_start_time = time.perf_counter()

                # Submit to ThreadPool with resource locking
                fut = executor.submit(
                    _run_node_logic,
                    fn_obj,
                    safe_args,
                    meta,
                    n_timeout,
                    n_retry,
                    tool_name,
                    agent_id,
                )
                futures[fut] = (idx, meta, safe_args, node_start_time)
                submitted.add(idx)

            # --- B. Wait for Next Completion ---
            if not futures:
                if len(completed) < len(nodes):
                    # Deadlock detected (cycle, or missed dep)
                    msg = "Deadlock: Remaining nodes have unmet dependencies but no tasks running."
                    logger.error(msg)
                    yield {"type": "error", "message": msg, "run_id": run_id}
                    return
                else:
                    break  # All done

            # Wait for at least one future
            done, _ = concurrent.futures.wait(
                futures.keys(), return_when=concurrent.futures.FIRST_COMPLETED
            )

            for fut in done:
                f_idx, f_meta, f_args, f_start_time = futures.pop(fut)
                f_node = nodes[f_idx]
                f_tool = f_node.get("tool")

                # --- FIX P5: Calculate real duration ---
                f_end_time = time.perf_counter()
                duration_seconds = round(f_end_time - f_start_time, 3)

                try:
                    result_payload = fut.result()
                except Exception as exc:
                    logger.exception(f"Optimizer worker crash for step {f_idx}")
                    result_payload = {
                        "status": "error",
                        "error": f"Worker Exception: {exc}",
                    }

                # Validate tool authority
                validation_result = validate_tool_authority(
                    f_meta, f_args, result_payload
                )
                quality = validation_result.get("quality", "unknown")
                violations = validation_result.get("violations", [])

                # Log violations
                if violations:
                    for violation in violations:
                        logger.warning(f"Authority violation detected: {violation}")

                # Update Trace with quality score and real duration
                trace_entry = {
                    "step_index": f_idx,
                    "tool": f_node.get("tool"),
                    "function": f_node.get("function"),
                    "status": result_payload.get("status"),
                    "quality": quality,  # Authority quality score
                    "violations": violations if violations else None,
                    "result": result_payload,
                    "duration": duration_seconds,  # FIX P5: Real wall-clock duration
                    "cache_hit": False,
                }
                trace[f_idx] = trace_entry
                completed.add(f_idx)

                # --- I5: Persist successful results to cache ---
                if (
                    cache_manager is not None
                    and config.cache_enabled
                    and result_payload.get("status") == "success"
                ):
                    _cache_key = CacheManager.make_key(f_tool, f_args)
                    cache_manager.set(_cache_key, result_payload, tool_name=f_tool)

                # Emit Event
                is_success = result_payload.get("status") == "success"
                yield {
                    "type": "step_complete",
                    "step_index": f_idx,  # Add step index for CLI display
                    "tool": f_tool,
                    "function": f_node.get("function"),
                    "status": "success" if is_success else "error",
                    "payload": result_payload,
                    "run_id": run_id,
                    "step_id": f"{run_id}-step-{f_idx}",
                    "duration": duration_seconds,  # FIX P5: Real wall-clock duration
                }

                # ── Append to run context file (feeds RAG synthesis) ────────
                if result_payload.get("status") == "success" and run_ctx is not None:
                    _resp = ""
                    _r = result_payload
                    if isinstance(_r, dict):
                        for _k in ("response", "content", "summary", "text"):
                            _v = _r.get(_k)
                            if _v and isinstance(_v, str) and len(_v) > 20:
                                _resp = _v
                                break
                        if not _resp:
                            _resp = json.dumps(_r, default=str)[:4000]
                    else:
                        _resp = str(_r)[:4000]
                    if _resp:
                        run_ctx.append_step(
                            step_idx=f_idx,
                            tool=f_tool,
                            thought=f_node.get("thought", ""),
                            response_text=_resp,
                        )

    # 4) Final synthesis from trace ----------------------------------------
    yield {"type": "status", "message": "Drafting final answer...", "run_id": run_id}

    try:
        compact_trace = [
            {
                "step_index": t.get("step_index"),
                "tool": t.get("tool", "unknown"),
                "function": t.get("function", "unknown"),
                "status": t.get("status", "unknown"),
                "duration": t.get("duration", 0.0),
                "input": t.get("input"),
                "result": t.get("result"),
            }
            for t in trace
            if t  # Skip None entries
        ]
        ctx = {"run_id": run_id, "trace_version": TRACE_VERSION, "steps": compact_trace}
        ctx_str = safe_serialize(ctx)
        if len(ctx_str) > config.trace_limit_chars:
            ctx_str = ctx_str[: config.trace_limit_chars] + "...[TRUNCATED]"

        # Build partial-failure context for the final synthesizer
        succeeded = [t for t in compact_trace if t.get("status") == "success"]
        failed    = [t for t in compact_trace if t.get("status") == "error"]
        skipped   = [t for t in compact_trace if t.get("status") == "skipped"]

        failure_ctx = ""
        if failed or skipped:
            failure_ctx = "\nExecution Notes:\n"
            if failed:
                failed_tools = [f"{t.get('tool')} (step {t.get('step_index')})" for t in failed]
                failure_ctx += f"- {len(failed)} step(s) FAILED: {failed_tools}\n"
            if skipped:
                failure_ctx += f"- {len(skipped)} step(s) SKIPPED due to upstream failures\n"
            if succeeded:
                failure_ctx += f"- {len(succeeded)} step(s) SUCCEEDED — use their data to answer\n"
            else:
                failure_ctx += "- NO steps succeeded. Explain what went wrong.\n"

        # --- I4: Graceful Capability Acknowledgment ---
        # Collect tools that are unavailable (error or skipped) for synthesis prompt context
        unavailable_tools = [
            {"tool": t.get("tool"), "step": t.get("step_index"), "reason": t.get("result", {}).get("error", "unavailable") if isinstance(t.get("result"), dict) else "unavailable"}
            for t in compact_trace
            if t.get("status") in ("error", "skipped")
        ]
        unavailable_ctx = ""
        if unavailable_tools:
            unavailable_ctx = "\nUnavailable Sources (inform the user honestly):\n"
            for u in unavailable_tools:
                unavailable_ctx += f"  - {u['tool']} (step {u['step']}): {u['reason']}\n"
            unavailable_ctx += "If a user asks about these sources, tell them they were unavailable during this run.\n"

        # ── CODE PASSTHROUGH: skip synthesis for code tool output ────────────
        # code_assistant and code_agent both return a response that IS the final answer.
        # Running through the synthesizer would destroy syntax and structure.
        _CODE_TOOLS = {"code_assistant", "code_agent"}
        code_steps = [
            t for t in compact_trace
            if t.get("tool") in _CODE_TOOLS and t.get("status") == "success"
        ]
        if code_steps:
            combined_parts = []
            for cs in code_steps:
                result = cs.get("result", {})
                if isinstance(result, dict):
                    response = result.get("response", "")
                    operation = result.get("operation", "")
                else:
                    response = str(result)
                    operation = ""

                # Skip empty / placeholder responses (e.g. "No code provided for review")
                if not response or "no code" in response.lower()[:50]:
                    continue

                combined_parts.append(response)

            if combined_parts:
                combined_response = "\n\n---\n\n".join(combined_parts)
                logger.info(
                    f"CodePassthrough: combined {len(combined_parts)} code_assistant result(s) directly (skipping synthesis LLM)"
                )
                yield {
                    "type": "final_answer",
                    "payload": {
                        "response": combined_response,
                        "model": "code_assistant (passthrough)",
                        "cache_hits": cache_hits,
                        "fabrication_report": {"total_numbers": 0, "verified": 0, "redacted": 0, "redacted_details": []},
                        "confidence": "high",
                        "audit_trail": [],
                    },
                }
                return

        # ── SYNTHESIS via engine (format detect + critic + RAG) ─────────────
        final = run_synthesis(
            user_msg=user_msg,
            trace=trace,
            nodes=nodes,
            run_ctx=run_ctx,
            failure_ctx=failure_ctx,
            unavailable_ctx=unavailable_ctx,
            console=None,
        )

        # --- FIX P4: Fabrication guard enforcement ---
        # Build ground truth registry from data tool results
        gt_registry = GroundTruthRegistry()
        gt_registry.register_from_trace(trace)

        # Check and redact fabrications in the final response
        if final.get("status") == "success" and final.get("response"):
            guard_result = check_and_redact(
                final["response"], gt_registry, include_audit=verify_finance
            )
            final["response"] = guard_result["redacted_text"]
            final["fabrication_report"] = guard_result["fabrication_report"]
            if verify_finance and "audit_trail" in guard_result:
                final["audit_trail"] = guard_result["audit_trail"]
            if guard_result["confidence"] == "low_confidence":
                final["confidence"] = "low_confidence"
                final["confidence_warning"] = (
                    "⚠️ More than 30% of numeric claims could not be verified "
                    "against upstream tool results. Please verify manually."
                )
                logger.warning("Final output marked as low_confidence due to fabrication rate")

        # Attach cache hit info to final payload
        final["cache_hits"] = cache_hits
        final["cache_hit_count"] = len(cache_hits)

        yield {"type": "final_answer", "payload": final, "run_id": run_id}

    except Exception as e:
        msg = f"Finalization failed: {e}"
        logger.exception(msg)
        yield {"type": "error", "message": msg, "run_id": run_id}


# ============================================================================ #
# RICH CLI & INTERACTIVE MODE                                                 #
# ============================================================================ #

if __name__ == "__main__":
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.table import Table
        from rich.text import Text
        from rich.prompt import Prompt, Confirm
    except ImportError:
        pass

    console = Console()

    SMITH_BANNER = r"""
   _____  __  __  _____  _______  _    _
  / ____||  \/  ||_   _||__   __|| |  | |
 | (___  | \  / |  | |     | |   | |__| |
  \___ \ | |\/| |  | |     | |   |  __  |
  ____) || |  | | _| |_    | |   | |  | |
 |_____/ |_|  |_||_____|   |_|   |_|  |_|
"""

    def print_banner():
        """Prints the stylish ASCII banner."""
        text = Text(SMITH_BANNER, style="bold cyan")
        panel = Panel(
            text,
            title="[bold magenta]Orchestrator v4.0[/bold magenta]",
            subtitle="[italic white]Type /help for commands[/italic white]",
            border_style="blue",
            expand=False,
        )
        console.print(panel)


def command_help():
    table = Table(title="Available Commands", border_style="blue")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    table.add_row("/help", "Show this help message")
    table.add_row("/diff", "Show details of the last execution trace")
    table.add_row("/export", "Export the last conversation to markdown")
    table.add_row("/clear", "Clear the screen")
    table.add_row("/quit", "Exit the orchestrator")

    console.print(table)


def command_diff(last_trace):
    if not last_trace:
        console.print("[yellow]No execution trace available yet.[/yellow]")
        return

    table = Table(title="Last Execution Trace", show_lines=True)
    table.add_column("Step", style="dim")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Result/Error", style="white")

    for step in last_trace:
        status_style = "green" if step.get("status") == "success" else "red"

        # Format result for display
        res = step.get("result", {})
        if isinstance(res, dict):
            # Try to show a concise summary
            if "error" in res:
                content = f"[red]{res['error']}[/red]"
            elif "result" in res:
                content = str(res["result"])[:100] + "..."
            else:
                content = str(res)[:100] + "..."
        else:
            content = str(res)[:100] + "..."

        table.add_row(
            str(step.get("step_index")),
            step.get("tool"),
            f"[{status_style}]{step.get('status')}[/{status_style}]",
            content,
        )

    console.print(table)


def command_export(history):
    if not history:
        console.print("[yellow]Nothing to export.[/yellow]")
        return

    filename = f"smith_export_{int(time.time())}.md"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# Smith Session Export\n\n")
            for item in history:
                f.write(f"**User**: {item['user']}\n\n")
                f.write(f"**Smith**: {item['smith']}\n\n")
                f.write("---\n\n")

        console.print(f"[green]Exported to {filename}[/green]")
    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")


def main():
    """Interactive CLI for Smith Orchestrator"""
    # Clear screen first
    console.clear()
    print_banner()

    history = []
    last_trace = []

    while True:
        try:
            # Styled Input
            user_input = Prompt.ask(
                "\n[bold green]Smith[/bold green] [bold white]>[/bold white]"
            ).strip()

            if not user_input:
                continue

            # Slash Commands
            if user_input.startswith("/"):
                cmd = user_input.lower()
                if cmd in ["/quit", "/exit", "/q"]:
                    console.print("[bold blue]Goodbye![/bold blue]")
                    break
                elif cmd == "/help":
                    command_help()
                elif cmd == "/clear":
                    console.clear()
                    print_banner()
                elif cmd == "/diff":
                    command_diff(last_trace)
                elif cmd == "/export":
                    command_export(history)
                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                continue

            # Processing
            console.print(
                Panel("[dim]Processing request...[/dim]", style="blue", expand=False)
            )

            current_trace = []
            final_response = ""

            # Live Status Update
            with Live(refresh_per_second=4) as live:
                status_table = Table.grid()
                status_table.add_column()

                live.update(
                    Panel(
                        status_table,
                        title="[yellow]Thinking...[/yellow]",
                        border_style="yellow",
                    )
                )

                for event in smith_orchestrator(user_input):
                    event_type = event.get("type")

                    if event_type == "status":
                        msg = event.get("message")
                        status_table.add_row(f"[dim]{msg}[/dim]")
                        live.update(
                            Panel(
                                status_table,
                                title="[yellow]Working...[/yellow]",
                                border_style="yellow",
                            )
                        )

                    elif event_type == "step_start":
                        tool = event.get("tool")
                        idx = event.get("step_index", 0)
                        status_table.add_row(
                            f"[blue]Step {idx}:[/blue] Running [cyan]{tool}[/cyan]..."
                        )
                        live.update(
                            Panel(
                                status_table,
                                title=f"[blue]Executing Step {idx}[/blue]",
                                border_style="blue",
                            )
                        )

                    elif event_type == "step_complete":
                        tool = event.get("tool")
                        status = event.get("status")
                        idx = int(
                            event.get("step_id", "0").split("-")[-1]
                        )  # hacky extraction

                        sym = "✓" if status == "success" else "✗"
                        color = "green" if status == "success" else "red"
                        status_table.add_row(f"[{color}]{sym} {tool}[/{color}]")

                        # Record for diff
                        current_trace.append(
                            {
                                "step_index": idx,
                                "tool": tool,
                                "status": status,
                                "result": event.get("payload"),
                            }
                        )

                    elif event_type == "final_answer":
                        payload = event.get("payload", {})
                        if payload.get("status") == "success":
                            final_response = payload.get("response", "")
                        else:
                            final_response = f"Error: {payload.get('error')}"

                    elif event_type == "error":
                        console.print(
                            f"[bold red]Error: {event.get('message')}[/bold red]"
                        )

                    elif event_type == "approval_required":
                        # Break out of Live to ask for input
                        live.stop()
                        tool = event.get("tool")
                        if Confirm.ask(
                            f"[bold red]Security Alert![/bold red] Allow tool [cyan]{tool}[/cyan]?"
                        ):
                            console.print("[green]Authorized.[/green]")
                        else:
                            console.print("[red]Denied.[/red]")
                            break
                        live.start()

            # Final Output
            if final_response:
                console.print(
                    Panel(
                        Markdown(final_response),
                        title="[bold green]Smith's Answer[/bold green]",
                        border_style="green",
                    )
                )
                # Save to history
                history.append({"user": user_input, "smith": final_response})
                last_trace = current_trace

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except EOFError:
            break
        except Exception as e:
            console.print(f"\n[bold red]Crash: {e}[/bold red]")
            if config.debug_mode:
                console.print_exception()


if __name__ == "__main__":
    main()
