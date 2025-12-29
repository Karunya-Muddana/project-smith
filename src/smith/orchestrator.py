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
from typing import Any, Callable, Dict, List, Generator

# Third-party imports
try:
    from smith.config import config
    from smith.tools import LLM_CALLER
    from smith import planner
    from smith.tools import DB_TOOLS
    from smith import tool_loader
except ImportError as e:
    # Fail fast if the package structure is invalid
    sys.stderr.write(
        f"CRITICAL: Failed to import core modules. Ensure 'smith' is installed.\nError: {e}\n"
    )
    sys.exit(1)

# Initialize Structured Logger
logging.basicConfig(
    level=logging.DEBUG if config.debug_mode else logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smith.orchestrator")

TRACE_VERSION = "3.0"
PLACEHOLDER_RE = re.compile(r"\{\{\s*STEPS\.(\d+)\.([^}]+)\}\}", re.IGNORECASE)

# Global Service Instances (Lazy Loaded)
_db_service = None


def get_db_service():
    """Singleton accessor for DB Service."""
    global _db_service
    if _db_service is None:
        try:
            _db_service = DB_TOOLS.DBTools()
            # Lightweight connectivity check
            res = _db_service.read_many("tools", {})
            if res.get("status") == "error":
                logger.warning(f"DB Check Failed: {res.get('error')}")
        except Exception as e:
            logger.critical(f"Database unavailable: {e}")
            raise RuntimeError("Core services unavailable. Check configuration.") from e
    return _db_service


def reset_services():
    """Reset global services. Used for testing."""
    global _db_service
    _db_service = None


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


def resolve_prompt_placeholders(prompt: str, trace: List[Dict[str, Any]]) -> str:
    """
    Only used for llm_caller.prompt.
    It replaces {{STEPS.i.path}} with data from the trace.
    """

    def repl(m: re.Match) -> str:
        try:
            idx = int(m.group(1))
        except ValueError:
            return ""
        path = m.group(2)
        if idx < 0 or idx >= len(trace):
            return ""
        data = trace[idx].get("result")
        value = _deep_get(data, path)
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return safe_serialize(value)
        return str(value)

    return PLACEHOLDER_RE.sub(repl, prompt)


# ============================================================================ #
# ORCHESTRATOR (DAG-AWARE)                                                    #
# ============================================================================ #


def smith_orchestrator(
    user_msg: str,
    require_approval: bool = config.require_approval,
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

    # 1) Read tool registry -------------------------------------------------
    try:
        service = get_db_service()
        tools_resp = service.read_many("tools", {})
        if tools_resp.get("status") != "success":
            raise RuntimeError(tools_resp.get("error", "Unknown DB error"))
        tools_list = tools_resp.get("data", []) or []
        registry = {t["name"]: t for t in tools_list}
    except Exception as e:
        msg = f"Database read failed: {e}"
        logger.error(msg)
        yield {"type": "error", "message": msg, "run_id": run_id}
        return

    # 2) Call planner -------------------------------------------------------
    try:
        plan = planner.plan_task(user_msg, tools_list)
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

    # Normalize depends_on for each node: default = previous index (sequential)
    for idx, node in enumerate(nodes):
        if "depends_on" not in node or node["depends_on"] is None:
            node["depends_on"] = [idx - 1] if idx > 0 else []

    trace: List[Dict[str, Any]] = []

    # 3) Execute nodes in index order (dependencies enforced logically) -----
    for idx, node in enumerate(nodes):
        tool_name = node.get("tool")
        fn_name = node.get("function")
        step_id = f"{run_id}-step-{idx}"

        deps = node.get("depends_on") or []
        # dependency validation
        for d in deps:
            if not isinstance(d, int) or d < 0 or d >= len(trace):
                msg = f"Step {idx} depends on invalid step index {d}. Planner bug."
                logger.error(msg)
                yield {
                    "type": "error",
                    "message": msg,
                    "run_id": run_id,
                    "step_id": step_id,
                }
                return
            if trace[d].get("status") != "success":
                msg = f"Step {idx} blocked: dependency step {d} did not succeed."
                logger.error(msg)
                yield {
                    "type": "error",
                    "message": msg,
                    "run_id": run_id,
                    "step_id": step_id,
                }
                return

        yield {
            "type": "step_start",
            "tool": tool_name,
            "function": fn_name,
            "step_index": idx,
            "run_id": run_id,
            "step_id": step_id,
            "message": f"Step {idx + 1}: {tool_name}",
        }

        # Lookup tool metadata in registry
        meta = registry.get(tool_name)
        if not meta:
            msg = f"Tool '{tool_name}' not registered in DB."
            logger.error(msg)
            yield {
                "type": "error",
                "message": msg,
                "run_id": run_id,
                "step_id": step_id,
            }
            return

        if require_approval and meta.get("dangerous", False):
            yield {
                "type": "approval_required",
                "tool": tool_name,
                "function": fn_name,
                "run_id": run_id,
                "step_id": step_id,
                "message": f"Security: Tool '{tool_name}' requires approval.",
            }

        # Load tool function
        try:
            fn = tool_loader.load_tool_function(meta["module"], fn_name)
            if not callable(fn):
                raise RuntimeError("Loaded object is not callable")
        except Exception as e:
            msg = f"Failed to load tool '{tool_name}': {e}"
            logger.exception(msg)
            yield {
                "type": "error",
                "message": msg,
                "run_id": run_id,
                "step_id": step_id,
            }
            return

        # Inputs: support both "inputs" (new) and "args" (legacy)
        raw_args = node.get("inputs") or node.get("args") or {}

        # Only llm_caller gets placeholder resolution in prompt
        safe_args = dict(raw_args)
        if tool_name == "llm_caller":
            prompt = safe_args.get("prompt", "")
            if isinstance(prompt, str):
                safe_args["prompt"] = resolve_prompt_placeholders(prompt, trace)

        yield {
            "type": "debug_args",
            "args": safe_args,
            "run_id": run_id,
            "step_id": step_id,
        }

        # Per-node retry/timeout (fall back to global defaults)
        node_retries = node.get("retry", config.max_retries)
        node_timeout = node.get("timeout", config.default_timeout)
        try:
            node_retries = int(node_retries)
        except Exception:
            node_retries = config.max_retries
        try:
            node_timeout = float(node_timeout)
        except Exception:
            node_timeout = config.default_timeout

        trace_entry: Dict[str, Any] = {
            "run_id": run_id,
            "step_id": step_id,
            "step_index": idx,
            "tool": tool_name,
            "function": fn_name,
            "depends_on": deps,
            "input": safe_args,
            "meta": {
                "module": meta.get("module"),
                "dangerous": bool(meta.get("dangerous")),
                "retry": node_retries,
                "timeout": node_timeout,
                "on_fail": node.get("on_fail", "halt"),
            },
            "timestamp_start": time.time(),
        }

        # Execute with retry logic
        start_ts = time.time()
        out: Dict[str, Any] = {"status": "error", "error": "Not run"}
        for attempt in range(node_retries + 1):
            out = execute_with_timeout(fn, safe_args, node_timeout)
            if out.get("status") == "success":
                break
            if attempt < node_retries:
                msg = f"Retry {attempt + 1}/{node_retries} for {tool_name}..."
                logger.warning(msg)
                yield {
                    "type": "status",
                    "message": msg,
                    "run_id": run_id,
                    "step_id": step_id,
                }
                time.sleep(1)

        duration = round(time.time() - start_ts, 3)

        trace_entry.update(
            {
                "result": out,
                "status": out.get("status"),
                "duration": duration,
                "timestamp_end": time.time(),
            }
        )
        trace.append(trace_entry)

        payload_str = safe_serialize(out)
        if len(payload_str) > 200:
            payload_str = payload_str[:200] + "..."

        if out.get("status") == "success":
            yield {
                "type": "step_complete",
                "tool": tool_name,
                "function": fn_name,
                "status": "success",
                "duration": duration,
                "payload": out,
                "run_id": run_id,
                "step_id": step_id,
            }
            logger.info(f"Step {idx + 1} ({tool_name}) completed in {duration}s")
        else:
            # on_fail currently treated as hard stop (simpler & safe)
            yield {
                "type": "step_complete",
                "tool": tool_name,
                "function": fn_name,
                "status": "error",
                "duration": duration,
                "payload": out,
                "run_id": run_id,
                "step_id": step_id,
            }
            logger.error(
                f"Step {idx + 1} ({tool_name}) failed in {duration}s: {payload_str}"
            )
            return

    # 4) Final synthesis from trace ----------------------------------------
    yield {"type": "status", "message": "Drafting final answer...", "run_id": run_id}

    try:
        compact_trace = [
            {
                "step_index": t["step_index"],
                "tool": t["tool"],
                "function": t["function"],
                "status": t["status"],
                "duration": t["duration"],
                "input": t.get("input"),
                "result": t.get("result"),
            }
            for t in trace
        ]
        ctx = {"run_id": run_id, "trace_version": TRACE_VERSION, "steps": compact_trace}
        ctx_str = safe_serialize(ctx)
        if len(ctx_str) > config.trace_limit_chars:
            ctx_str = ctx_str[: config.trace_limit_chars] + "...[TRUNCATED]"

        final_prompt = (
            f"User Request: {user_msg}\n\n"
            f"Execution Trace (machine readable JSON):\n{ctx_str}\n\n"
            "INSTRUCTIONS:\n"
            "1. Answer ONLY using information present in the trace.\n"
            "2. If something is missing or a tool failed, say that explicitly.\n"
            "3. Do not invent URLs, numbers, or tools that are not present.\n"
        )

        model = config.primary_model
        final = LLM_CALLER.call_llm(final_prompt, model=model)
        yield {"type": "final_answer", "payload": final, "run_id": run_id}

    except Exception as e:
        msg = f"Finalization failed: {e}"
        logger.exception(msg)
        yield {"type": "error", "message": msg, "run_id": run_id}


# ============================================================================ #
# CLI                                                                         #
# ============================================================================ #

if __name__ == "__main__":
    print(f"\n[SYSTEM] SMITH ENGINE v{TRACE_VERSION}")
    print(f"[SYSTEM] Log Level: {'DEBUG' if config.debug_mode else 'INFO'}")

    try:
        while True:
            # Simple CLI REPL
            q = input("\n> Command (or 'exit'): ").strip()
            if q.lower() in {"exit", "quit"}:
                break
            if not q:
                continue

            for evt in smith_orchestrator(q):
                etype = evt["type"]
                msg = evt.get("message", "")

                if etype == "status":
                    print(f"[INFO] {msg}")
                elif etype == "step_start":
                    print(f"[EXEC] Step {evt['step_index'] + 1}: {evt['tool']}...")
                elif etype == "debug_args":
                    if config.debug_mode:
                        args_str = safe_serialize(evt.get("args", {}))
                        if len(args_str) > 200:
                            args_str = args_str[:200] + "..."
                        print(f"   ↳ [INPUT] {args_str}")
                elif etype == "approval_required":
                    print(f"[SECURITY] {msg}")
                    auth = input(">>> Authorize? (y/N): ").strip().lower()
                    if auth != "y":
                        print("[ABORT] Denied by user.")
                        break
                    print("[INFO] Authorized.")
                elif etype == "step_complete":
                    payload = safe_serialize(evt.get("payload", {}))
                    if len(payload) > 200:
                        payload = payload[:200] + "..."
                    if evt.get("status") == "success":
                        print(f"   ↳ [OUTPUT] {payload}")
                        print(f"[DONE] {evt['tool']} ({evt['duration']}s)")
                    else:
                        print(f"   ↳ [ERROR] {payload}")
                        print(f"[FAIL] {evt['tool']}")
                elif etype == "final_answer":
                    res = evt.get("payload", {})
                    text = (
                        res.get("response", res) if isinstance(res, dict) else str(res)
                    )
                    print(f"\n>>> FINAL ANSWER: {text}")
                elif etype == "error":
                    print(f"[ERROR] {msg}")

    except KeyboardInterrupt:
        print("\n[SYSTEM] Terminated by user.")
        sys.exit(0)
