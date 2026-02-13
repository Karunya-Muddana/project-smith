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

# No longer need DB service - using static registry


def reset_services():
    """Reset global services. Used for testing."""
    registry.reset_cache()


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
        "llm_caller": 1.0,  # Prevent rapid-fire LLM calls
        "google_search": 0.5,
        "news_fetcher": 0.5,
        "weather_fetcher": 0.2,
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

    # 1) Read tool registry (static JSON) ------------------------------------
    try:
        tools_list = registry.get_tools_registry()
        tool_registry = {t["name"]: t for t in tools_list}
    except Exception as e:
        msg = f"Failed to load tool registry: {e}"
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

    # Emit plan created event for CLI/UI to capture
    yield {"type": "plan_created", "plan": plan, "run_id": run_id}

    # 3) Parallel Execution Setup -------------------------------------------
    trace: List[Optional[Dict[str, Any]]] = [None] * len(nodes)
    completed: Set[int] = set()
    submitted: Set[int] = set()
    futures: Dict[concurrent.futures.Future, int] = {}

    # Rate limiter logic (simple local instance)
    limiter = RateLimiter()

    # Pre-calculate dependencies to fail fast on cycles/errors
    for idx, node in enumerate(nodes):
        # Default to sequential if undefined
        if "depends_on" not in node or node["depends_on"] is None:
            node["depends_on"] = [idx - 1] if idx > 0 else []
        elif not isinstance(node["depends_on"], list):
            node["depends_on"] = []

        # Validate dependencies exist
        for d in node["depends_on"]:
            if not isinstance(d, int) or d < 0 or d >= len(nodes):
                yield {
                    "type": "error",
                    "message": f"Step {idx} depends on invalid index {d}",
                    "run_id": run_id,
                }
                return

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
                upstream_error = any(
                    (trace[d] and trace[d].get("status") != "success") for d in deps
                )

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

                if upstream_error:
                    # Skip execution
                    logger.warning(
                        f"Skipping Step {idx} ({tool_name}) due to upstream failure."
                    )
                    trace[idx] = {
                        "status": "skipped",
                        "error": "Upstream dependency failed",
                        "step_index": idx,
                    }
                    completed.add(idx)
                    submitted.add(idx)
                    continue

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

                # Resolving placeholders must be done HERE (main thread) because `trace` is consistent here
                if tool_name == "llm_caller":
                    p = safe_args.get("prompt", "")
                    if isinstance(p, str):
                        safe_args["prompt"] = resolve_prompt_placeholders(p, trace)

                yield {
                    "type": "debug_args",
                    "args": safe_args,
                    "run_id": run_id,
                    "step_id": step_id,
                }

                # Apply Rate Limit (Blocking sleep if needed)
                limiter.wait_if_needed(tool_name)

                # Prepare Task Logic
                def _run_node_logic(
                    _fn: Callable,
                    _args: Dict,
                    _meta: Dict,
                    _timeout: float,
                    _retries: int,
                ) -> Dict[str, Any]:
                    _out = {"status": "error", "error": "Not run"}
                    for attempt in range(_retries + 1):
                        _out = execute_with_timeout(_fn, _args, _timeout)
                        if _out.get("status") == "success":
                            break
                        if attempt < _retries:
                            time.sleep(1)
                    return _out

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

                # Submit to ThreadPool
                fut = executor.submit(
                    _run_node_logic, fn_obj, safe_args, meta, n_timeout, n_retry
                )
                futures[fut] = idx
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
                f_idx = futures.pop(fut)
                f_node = nodes[f_idx]
                f_tool = f_node.get("tool")

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
                    meta, safe_args, result_payload
                )
                quality = validation_result.get("quality", "unknown")
                violations = validation_result.get("violations", [])

                # Log violations
                if violations:
                    for violation in violations:
                        logger.warning(f"Authority violation detected: {violation}")

                # Calculate duration (approximate, since we don't have start time in future easily without wrapper)
                # We'll omit duration in trace for now or add start_time to futures map.
                # Simplification: duration=0 or track locally.

                # Update Trace with quality score
                trace_entry = {
                    "step_index": f_idx,
                    "tool": f_node.get("tool"),
                    "function": f_node.get("function"),
                    "status": result_payload.get("status"),
                    "quality": quality,  # Authority quality score
                    "violations": violations if violations else None,
                    "result": result_payload,
                    "duration": 0.0,  # Placeholder
                }
                trace[f_idx] = trace_entry
                completed.add(f_idx)

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
                    "duration": 0.0,
                }

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

    SMITH_BANNER = """
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
            title="[bold magenta]Orchestrator v3.0[/bold magenta]",
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
