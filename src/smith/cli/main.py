"""
SMITH CLI - Professional Implementation
----------------------------------------
Rebuilt using Rich best practices for reliable progress tracking.
"""

import argparse
import sys
import time
import json
import uvicorn
from typing import Dict, Any, List, Optional
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich import box
from rich.tree import Tree
from rich.text import Text

# Smith imports
from smith.core.orchestrator import smith_orchestrator
from smith.registry import list_tool_names
from smith.core.cache_manager import CacheManager, get_cache_manager
from smith.core.report_renderer import render_report

# Separate consoles for output and errors
console = Console()
err_console = Console(stderr=True, style="red")

# ============================================================================
# BANNER
# ============================================================================

SMITH_BANNER = """
[bold white]
  ███████╗███╗   ███╗██╗████████╗██╗  ██╗
  ██╔════╝████╗ ████║██║╚══██╔══╝██║  ██║
  ███████╗██╔████╔██║██║   ██║   ███████║
  ╚════██║██║╚██╔╝██║██║   ██║   ██╔══██║
  ███████║██║ ╚═╝ ██║██║   ██║   ██║  ██║
  ╚══════╝╚═╝     ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝
[/bold white]
[dim]Zero-Trust Agent Runtime[/dim]
"""

# ============================================================================
# SESSION
# ============================================================================


class Session:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        self.last_trace: List[Dict] = []
        self.last_dag: Dict = None
        # Explain metadata
        self.last_explain_data: Dict[str, Any] = {}

    def add_interaction(self, user_input: str, response: str, trace: List[Dict] = None):
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "user": user_input,
                "assistant": response,
                "trace": trace or [],
            }
        )
        if trace:
            self.last_trace = trace


# ============================================================================
# COMMANDS
# ============================================================================


def cmd_help():
    table = Table(title="Available Commands", border_style="cyan", box=box.ROUNDED)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="white")

    table.add_row("/help", "Show this help message")
    table.add_row("/tools", "List all available tools")
    table.add_row("/trace", "Show execution trace of last run")
    table.add_row("/dag", "Export last execution DAG as JSON")
    table.add_row("/inspect", "Show ASCII flowchart of DAG and trace")
    table.add_row("/explain", "Deep-dive analysis of last run (DAG, cache, tokens, cost)")
    table.add_row("/history", "Show conversation history")
    table.add_row("/export", "Export session to markdown file")
    table.add_row("/cache", "Show cache statistics")
    table.add_row("/cache clear", "Clear all cached tool results")
    table.add_row("/serve", "Start the Smith Web UI Server")
    table.add_row("/clear", "Clear the screen")
    table.add_row("/quit, /exit", "Exit Smith")

    console.print(table)


def cmd_tools():
    try:
        tools = list_tool_names()
        table = Table(title="Available Tools", border_style="green", box=box.ROUNDED)
        table.add_column("#", style="dim", width=4)
        table.add_column("Tool Name", style="bold cyan")

        for idx, tool in enumerate(tools, 1):
            table.add_row(str(idx), tool)

        console.print(table)
        console.print(f"\n[dim]Total: {len(tools)} tools[/dim]")
    except Exception as e:
        err_console.print(f"Error loading tools: {e}")


def cmd_trace(session: Session):
    if not session.last_trace:
        console.print("[yellow]No execution trace available yet.[/yellow]")
        return

    table = Table(title="Last Execution Trace", show_lines=True, box=box.ROUNDED)
    table.add_column("Step", style="dim", width=6)
    table.add_column("Tool", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Duration", style="dim")
    table.add_column("Cache", style="dim")

    for step in session.last_trace:
        status = step.get("status", "unknown")
        status_icon = "✓" if status == "success" else "✗" if status == "error" else "~"
        status_color = (
            "green" if status == "success" else "red" if status == "error" else "yellow"
        )
        cache_icon = "⚡ HIT" if step.get("cache_hit") else "-"

        table.add_row(
            str(step.get("step_index", "?")),
            step.get("tool", "unknown"),
            f"[{status_color}]{status_icon} {status}[/{status_color}]",
            f"{step.get('duration', 0):.2f}s",
            cache_icon,
        )

    console.print(table)


def cmd_dag(session: Session):
    if not session.last_dag:
        console.print("[yellow]No DAG available. Run a query first.[/yellow]")
        return

    filename = f"smith_dag_{int(time.time())}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session.last_dag, f, indent=2, default=str)
        console.print(f"[green]✓ DAG exported to {filename}[/green]")
    except Exception as e:
        err_console.print(f"Export failed: {e}")


def cmd_history(session: Session):
    if not session.history:
        console.print("[yellow]No history yet.[/yellow]")
        return

    for idx, item in enumerate(session.history, 1):
        console.print(f"\n[bold cyan]#{idx}[/bold cyan] [dim]{item['timestamp']}[/dim]")
        console.print(f"[green]You:[/green] {item['user']}")
        console.print(f"[blue]Smith:[/blue] {item['assistant'][:200]}...")


def cmd_inspect(session: Session):
    """Display ASCII flowchart of DAG and trace"""
    if not session.last_dag and not session.last_trace:
        console.print("[yellow]No DAG or trace available. Run a query first.[/yellow]")
        return

    console.print("\n[bold cyan]═══ EXECUTION FLOWCHART ═══[/bold cyan]\n")

    # Show DAG structure if available
    if session.last_dag:
        nodes = session.last_dag.get("nodes", [])
        edges = session.last_dag.get("edges", [])

        console.print("[bold]DAG Structure:[/bold]")
        console.print(f"  Nodes: {len(nodes)} | Edges: {len(edges)}\n")

        # Build dependency map
        dependencies = {}
        for edge in edges:
            target = edge.get("to")
            source = edge.get("from")
            if target not in dependencies:
                dependencies[target] = []
            dependencies[target].append(source)

        # Create ASCII flowchart
        for idx, node in enumerate(nodes):
            node_id = node.get("id")
            tool = node.get("tool", "unknown")

            # Show dependencies
            if node_id in dependencies:
                deps = dependencies[node_id]
                for dep in deps:
                    dep_node = next((n for n in nodes if n.get("id") == dep), None)
                    if dep_node:
                        dep_tool = dep_node.get("tool", "unknown")
                        console.print("       │")
                        console.print(f"       ↓ [dim](from {dep_tool})[/dim]")

            # Find status from trace
            status_icon = "○"
            status_color = "white"
            duration = ""
            error_msg = ""

            if session.last_trace:
                trace_entry = next(
                    (t for t in session.last_trace if t.get("step_index") == idx), None
                )
                if trace_entry:
                    status = trace_entry.get("status", "unknown")
                    if status == "success":
                        status_icon = "✓"
                        status_color = "green"
                    elif status == "error":
                        status_icon = "✗"
                        status_color = "red"
                        result = trace_entry.get("result", {})
                        if isinstance(result, dict):
                            error_msg = f" - {result.get('error', 'Unknown error')}"
                    else:
                        status_icon = "~"
                        status_color = "yellow"
                    duration = f" ({trace_entry.get('duration', 0):.2f}s)"
                    if trace_entry.get("cache_hit"):
                        duration += " [⚡cache]"

            console.print(
                f"  [{status_color}]{status_icon}[/{status_color}]  [bold cyan]Step {idx}:[/bold cyan] {tool}{duration}{error_msg}"
            )

    elif session.last_trace:
        console.print("[bold]Execution Trace:[/bold]\n")
        for step in session.last_trace:
            status = step.get("status", "unknown")
            status_icon = (
                "✓" if status == "success" else "✗" if status == "error" else "~"
            )
            status_color = (
                "green"
                if status == "success"
                else "red" if status == "error" else "yellow"
            )

            tool = step.get("tool", "unknown")
            duration = step.get("duration", 0)

            console.print(
                f"  [{status_color}]{status_icon}[/{status_color}]  [bold]Step {step.get('step_index', '?')}:[/bold] {tool} ([dim]{duration:.2f}s[/dim])"
            )

    console.print("\n[dim]Use /trace for detailed results, /dag to export JSON[/dim]\n")


def cmd_export(session: Session):
    if not session.history:
        console.print("[yellow]Nothing to export.[/yellow]")
        return

    filename = f"smith_session_{int(time.time())}.md"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# Smith Session Export\n\n")
            f.write(
                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n\\n"
            )
            f.write("---\n\n")

            for idx, item in enumerate(session.history, 1):
                f.write(f"## Interaction {idx}\n\n")
                f.write(f"**Timestamp:** {item['timestamp']}\\n\\n")
                f.write(f"**User:** {item['user']}\\n\\n")
                f.write(f"**Smith:** {item['assistant']}\\n\\n")
                f.write("---\n\n")

        console.print(f"[green]✓ Session exported to {filename}[/green]")
    except Exception as e:
        err_console.print(f"Export failed: {e}")


def cmd_cache(cache_mgr: CacheManager, subcmd: str = ""):
    """Show cache statistics or clear cache."""
    subcmd = subcmd.strip().lower()

    if subcmd == "clear":
        n = cache_mgr.clear()
        console.print(f"[green]✓ Cleared {n} cache entries.[/green]")
        return

    # Default: show stats
    stats = cache_mgr.stats()

    table = Table(title="Run Cache Statistics", border_style="cyan", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Entries on Disk", str(stats["entries_on_disk"]))
    table.add_row("Total Size", f"{stats['total_size_kb']} KB")
    table.add_row("TTL", f"{stats['ttl_seconds']}s ({stats['ttl_seconds']//60} min)")
    table.add_row("Cache Directory", stats["cache_dir"])
    table.add_row("─── Session ───", "")
    table.add_row("Hits", str(stats["session_hits"]))
    table.add_row("Misses", str(stats["session_misses"]))
    table.add_row("Stored", str(stats["session_sets"]))
    hit_rate = stats["session_hit_rate"]
    hr_color = "green" if hit_rate >= 50 else "yellow" if hit_rate > 0 else "dim"
    table.add_row("Hit Rate", f"[{hr_color}]{hit_rate}%[/{hr_color}]")

    console.print(table)


def cmd_explain(session: Session):
    """Deep-dive analysis of the last run."""
    ed = session.last_explain_data
    if not ed:
        console.print("[yellow]No run data available. Execute a query first.[/yellow]")
        return

    console.print("\n[bold cyan]═══ RUN EXPLANATION ═══[/bold cyan]\n")

    # ── DAG Overview ─────────────────────────────────────────────────────────
    dag = ed.get("dag")
    trace = ed.get("trace", [])
    nodes = dag.get("nodes", []) if dag else []

    dag_table = Table(title="DAG Overview", box=box.ROUNDED, border_style="blue")
    dag_table.add_column("Step", style="dim", width=5)
    dag_table.add_column("Tool", style="cyan")
    dag_table.add_column("Status", style="bold")
    dag_table.add_column("Duration", style="dim")
    dag_table.add_column("Cache", style="dim")
    dag_table.add_column("Thought", style="dim", max_width=40)

    for i, node in enumerate(nodes):
        t = next((x for x in trace if x.get("step_index") == i), {})
        status = t.get("status", "pending")
        sc = "green" if status == "success" else "red" if status == "error" else "yellow"
        si = "✓" if status == "success" else "✗" if status == "error" else "~"
        duration = f"{t.get('duration', 0):.2f}s"
        cache_icon = "⚡ HIT" if t.get("cache_hit") else "-"
        thought = (node.get("thought") or "")[:50]
        dag_table.add_row(str(i), node.get("tool", "?"), f"[{sc}]{si} {status}[/{sc}]", duration, cache_icon, thought)

    console.print(dag_table)

    # ── Parallel Groups ───────────────────────────────────────────────────────
    parallel_groups = ed.get("parallel_groups", [])
    if parallel_groups:
        pg_text = Text()
        for i, group in enumerate(parallel_groups):
            pg_text.append(f"  Group {i+1}: ", style="bold cyan")
            pg_text.append(", ".join(group) + "\n")
        console.print(Panel(pg_text, title="[bold cyan]⚡ Parallel Execution Groups[/bold cyan]", border_style="cyan"))

    # ── Cache Hits ───────────────────────────────────────────────────────────
    cache_hits = ed.get("cache_hits", [])
    hit_count = len(cache_hits)
    total_nodes = len(nodes)
    if total_nodes > 0:
        hit_pct = round(hit_count / total_nodes * 100, 1)
        color = "green" if hit_pct > 50 else "yellow" if hit_pct > 0 else "dim"
        console.print(Panel(
            Text(f"  {hit_count}/{total_nodes} steps served from cache ({hit_pct}%)\n  Steps: {cache_hits if cache_hits else 'none'}", justify="left"),
            title=f"[bold {color}]⚡ Cache Performance[/bold {color}]",
            border_style=color,
        ))

    # ── Token Budget ─────────────────────────────────────────────────────────
    total_tokens_est = ed.get("total_tokens_est", 0)
    total_cost_est = ed.get("total_cost_est", 0.0)
    tok_table = Table(title="Token & Cost Estimate", box=box.SIMPLE, border_style="magenta")
    tok_table.add_column("Metric", style="magenta")
    tok_table.add_column("Value", style="white")
    tok_table.add_row("Est. Tokens (trace)", f"~{total_tokens_est:,}")
    tok_table.add_row("Est. Synthesis Cost", f"~${total_cost_est:.4f}")
    console.print(tok_table)

    # ── Fabrication Guard ────────────────────────────────────────────────────
    fab_report = ed.get("fabrication_report")
    if fab_report:
        total_n = fab_report.get("total_numbers", 0)
        verified_n = fab_report.get("verified", 0)
        redacted_n = fab_report.get("redacted", 0)
        confidence = ed.get("confidence", "high")
        conf_color = "green" if confidence == "high" else "yellow" if confidence == "medium" else "red"
        fab_text = Text()
        fab_text.append(f"  Numbers found: {total_n}  |  Verified: ", style="white")
        fab_text.append(str(verified_n), style="green")
        fab_text.append("  |  Redacted: ", style="white")
        fab_text.append(str(redacted_n), style="red" if redacted_n > 0 else "dim")
        fab_text.append(f"\n  Confidence: ", style="white")
        fab_text.append(confidence.upper(), style=f"bold {conf_color}")
        console.print(Panel(fab_text, title="[bold yellow]🛡 Fabrication Guard[/bold yellow]", border_style="yellow"))

    # ── Audit Trail ──────────────────────────────────────────────────────────
    audit_trail = ed.get("audit_trail", [])
    if audit_trail:
        at_table = Table(title="Finance Audit Trail", box=box.SIMPLE, border_style="green")
        at_table.add_column("Symbol", style="cyan")
        at_table.add_column("Verified Price", style="white")
        at_table.add_column("Currency", style="dim")
        for entry in audit_trail:
            at_table.add_row(entry.get("symbol", "?"), str(entry.get("verified_price", "?")), entry.get("currency", "USD"))
        console.print(at_table)

    console.print()


# ============================================================================
# QUERY EXECUTION
# ============================================================================


def execute_query(
    user_input: str,
    session: Session,
    verify_finance: bool = False,
    cache_mgr: Optional[CacheManager] = None,
) -> str:
    """Execute query with proper progress tracking"""

    trace_data = []
    final_answer = ""
    dag_plan = None
    total_steps = 0
    final_payload: Dict[str, Any] = {}

    # Create progress tracker
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        # Main task
        main_task = progress.add_task("[cyan]Processing...", total=None)

        # Execute orchestrator
        for event in smith_orchestrator(
            user_input,
            require_approval=False,
            verify_finance=verify_finance,
            cache_manager=cache_mgr,
        ):
            event_type = event.get("type")

            if event_type == "status":
                msg = event.get("message", "")
                progress.update(main_task, description=f"[cyan]{msg}")

            elif event_type == "plan_created":
                dag_plan = event.get("plan")
                nodes = dag_plan.get("nodes", []) if dag_plan else []
                total_steps = len(nodes)
                progress.update(
                    main_task,
                    description=f"[green]✓ Plan created ({total_steps} steps)",
                    total=total_steps,
                    completed=0,
                )

            elif event_type == "step_start":
                step_idx = event.get("step_index", 0)
                tool = event.get("tool", "unknown")
                progress.update(
                    main_task,
                    description=f"[bold]→ Step {step_idx + 1}/{total_steps}:[/bold] [cyan]{tool}[/cyan]",
                    completed=step_idx,
                )

            elif event_type == "step_complete":
                step_idx = event.get("step_index", 0)
                tool = event.get("tool")
                status = event.get("status")
                duration = event.get("duration", 0)
                cache_hit = event.get("cache_hit", False)

                # Update progress
                progress.update(main_task, completed=step_idx + 1)

                # Track trace
                trace_data.append(
                    {
                        "step_index": step_idx,
                        "tool": tool,
                        "status": status,
                        "duration": duration,
                        "cache_hit": cache_hit,
                        "result": event.get("payload"),
                    }
                )

            elif event_type == "final_answer":
                final_payload = event.get("payload", {})
                if isinstance(final_payload, dict):
                    final_answer = final_payload.get("response", str(final_payload))
                else:
                    final_answer = str(final_payload)
                progress.update(
                    main_task, description="[green]✓ Complete", completed=total_steps
                )

            elif event_type == "error":
                error_msg = event.get("message", "Unknown error")
                progress.update(
                    main_task, description=f"[red]✗ Error:[/red] {error_msg}"
                )

    # Save to session
    session.last_trace = trace_data
    session.last_dag = dag_plan

    # ── Build explain metadata ────────────────────────────────────────────────
    # Detect parallel groups (nodes that share no dependencies)
    parallel_groups: List[List[str]] = []
    if dag_plan:
        nodes_list = dag_plan.get("nodes", [])
        _seen: set = set()
        for node in nodes_list:
            deps = node.get("_normalized_deps") or node.get("depends_on") or []
            if not deps and node.get("id") not in _seen:
                # Root node — could be parallel if multiple roots exist
                # Simplified: group by same dep set
                parallel_groups.append([node.get("tool", "?")])
                _seen.add(node.get("id"))

    # Estimate tokens in trace
    trace_chars = sum(len(str(t.get("result", {}))) for t in trace_data)
    total_tokens_est = trace_chars // 4

    # Rough cost estimate (Groq is ~$0.00027 / 1k tokens for 70b, free-tier proxy)
    total_cost_est = (total_tokens_est / 1000) * 0.00027

    session.last_explain_data = {
        "dag": dag_plan,
        "trace": trace_data,
        "parallel_groups": parallel_groups,
        "cache_hits": final_payload.get("cache_hits", []),
        "total_tokens_est": total_tokens_est,
        "total_cost_est": total_cost_est,
        "fabrication_report": final_payload.get("fabrication_report"),
        "confidence": final_payload.get("confidence", "high"),
        "audit_trail": final_payload.get("audit_trail", []),
    }

    return final_answer


def cmd_fleet(user_input: str, session: Session):
    """Handle /fleet command to activate fleet mode"""
    from smith.core.fleet_coordinator import get_fleet_coordinator
    from smith.config import config
    from rich.prompt import IntPrompt

    # Check if fleet mode is enabled
    if not config.enable_fleet_mode:
        console.print("[yellow]⚠ Fleet mode is disabled in configuration[/yellow]")
        return

    # Extract goal from command
    parts = user_input.split(maxsplit=1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /fleet <goal>[/yellow]")
        console.print("[dim]Example: /fleet Analyze the top 5 tech stocks[/dim]")
        return

    goal = parts[1].strip()

    # Ask for number of agents
    try:
        num_agents = IntPrompt.ask(
            f"[cyan]How many agents?[/cyan] (1-{config.max_fleet_size})", default=3
        )

        if num_agents < 1 or num_agents > config.max_fleet_size:
            console.print(
                f"[red]Number of agents must be between 1 and {config.max_fleet_size}[/red]"
            )
            return
    except KeyboardInterrupt:
        console.print("\n[yellow]Fleet mode cancelled[/yellow]")
        return

    # Run fleet
    console.print(
        f"\n[bold cyan]🚀 Launching fleet of {num_agents} agents...[/bold cyan]\n"
    )

    coordinator = get_fleet_coordinator()
    result = coordinator.run_fleet(goal, num_agents)

    # Display results
    if result.get("status") == "success":
        console.print("\n[bold green]✓ Fleet completed successfully![/bold green]\n")

        # Show sub-tasks
        console.print("[bold]Sub-tasks assigned:[/bold]")
        for i, task in enumerate(result.get("sub_tasks", [])):
            console.print(f"  {i + 1}. {task}")

        # Show final result
        console.print("\n[bold]Final Result:[/bold]")
        final_result = result.get("final_result", "No result")
        console.print(Panel(Markdown(final_result), border_style="green"))

        # Add to session
        session.add_interaction(user_input, final_result)
    else:
        error = result.get("error", "Unknown error")
        console.print(f"\n[red]✗ Fleet failed: {error}[/red]")


def cmd_subagents():
    """Show active sub-agents hierarchy"""
    from smith.core.agent_state import get_state_manager

    state_mgr = get_state_manager()
    stats = state_mgr.get_stats()

    # Show statistics
    console.print("\n[bold]Agent Statistics:[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total Agents", str(stats.get("total_agents", 0)))
    table.add_row("Active Agents", str(stats.get("active_agents", 0)))
    table.add_row("Root Agents", str(stats.get("root_agents", 0)))

    console.print(table)

    # Show agent tree
    root_agents = state_mgr.get_root_agents()

    if not root_agents:
        console.print("\n[dim]No active agents[/dim]")
        return

    console.print("\n[bold]Agent Hierarchy:[/bold]\n")

    for root in root_agents:
        tree = Tree(f"[bold cyan]{root.agent_id}[/bold cyan] - {root.task[:50]}...")
        _build_agent_tree(tree, root, state_mgr)
        console.print(tree)


def _build_agent_tree(tree, agent, state_mgr):
    """Recursively build agent tree for display"""
    children = state_mgr.get_children(agent.agent_id)

    for child in children:
        status_icon = {
            "initializing": "⏳",
            "running": "▶",
            "completed": "✓",
            "failed": "✗",
            "cancelled": "⊘",
        }.get(child.status.value, "?")

        status_color = {
            "initializing": "yellow",
            "running": "cyan",
            "completed": "green",
            "failed": "red",
            "cancelled": "dim",
        }.get(child.status.value, "white")

        branch = tree.add(
            f"[{status_color}]{status_icon}[/{status_color}] "
            f"[bold]{child.agent_id}[/bold] - {child.task[:40]}..."
        )

        # Recursively add children
        _build_agent_tree(branch, child, state_mgr)


# ============================================================================
# MAIN REPL
# ============================================================================


def print_banner():
    console.print(
        Panel(
            SMITH_BANNER + "\n" + "[dim]Zero-Trust Agent Runtime v3.0[/dim]",
            border_style="blue",
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )

    console.print("\n[bold white]Tips for getting started:[/bold white]")
    console.print("  1. Ask questions, run analysis, or fetch data")
    console.print("  2. Be specific for the best results")
    console.print("  3. Try [cyan]/help[/cyan] for more information\n")


def main():
    """Main CLI loop"""
    # Parse args
    parser = argparse.ArgumentParser(description="Smith Agent Runtime")
    parser.add_argument("--verify-finance", action="store_true", help="Enable finance audit trail in responses")
    parser.add_argument("--no-cache", action="store_true", help="Disable the run cache for this session")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args, _ = parser.parse_known_args()

    verify_finance = args.verify_finance
    use_cache = not args.no_cache

    console.clear()
    print_banner()

    if verify_finance:
        console.print("[bold yellow]⚠ Finance verification mode enabled — audit trails will be shown[/bold yellow]\n")
    if not use_cache:
        console.print("[dim]Cache disabled for this session[/dim]\n")

    # Initialise cache
    cache_mgr: Optional[CacheManager] = None
    if use_cache:
        try:
            cache_mgr = get_cache_manager()
            cache_mgr.evict_expired()
        except Exception as e:
            console.print(f"[yellow]Cache unavailable: {e}[/yellow]")

    session = Session()

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]>[/bold green]").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input.lower().strip()

                if cmd in ["/quit", "/exit", "/q"]:
                    console.print("\n[bold cyan]👋 Goodbye![/bold cyan]\n")
                    break

                elif cmd == "/help":
                    cmd_help()

                elif cmd == "/tools":
                    cmd_tools()

                elif cmd == "/trace":
                    cmd_trace(session)

                elif cmd == "/dag":
                    cmd_dag(session)

                elif cmd == "/inspect":
                    cmd_inspect(session)

                elif cmd == "/explain":
                    cmd_explain(session)

                elif cmd == "/history":
                    cmd_history(session)

                elif cmd == "/export":
                    cmd_export(session)

                elif cmd == "/cache":
                    if cache_mgr:
                        cmd_cache(cache_mgr)
                    else:
                        console.print("[yellow]Cache is disabled (run without --no-cache to enable)[/yellow]")

                elif cmd == "/cache clear":
                    if cache_mgr:
                        cmd_cache(cache_mgr, subcmd="clear")
                    else:
                        console.print("[yellow]Cache is disabled[/yellow]")

                elif cmd == "/clear":
                    console.clear()
                    print_banner()

                elif cmd.startswith("/fleet"):
                    cmd_fleet(user_input, session)

                elif cmd == "/subagents":
                    cmd_subagents()

                elif cmd == "/serve":
                    console.print("[bold green]Starting Smith Web Interface...[/bold green]")
                    console.print("[dim]Backend API running on http://127.0.0.0:8000[/dim]")
                    try:
                        uvicorn.run("smith.server.app:app", host="0.0.0.0", port=8000, reload=True)
                    except Exception as e:
                        err_console.print(f"Failed to start server: {e}")
                    # Re-print banner after server exits
                    console.clear()
                    print_banner()

                else:
                    err_console.print(f"Unknown command: {cmd}")
                    console.print("[dim]Try /help for available commands[/dim]")

                continue

            # Execute query
            response = execute_query(
                user_input,
                session,
                verify_finance=verify_finance,
                cache_mgr=cache_mgr,
            )

            # Display final answer via report renderer
            if response:
                plain = render_report(response, console)
                # render_report already printed rich panels; store plain text
                session.add_interaction(user_input, plain or response, session.last_trace)
            else:
                console.print("\n[yellow]No response generated[/yellow]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Use /quit to exit.[/yellow]")
            continue

        except Exception as e:
            err_console.print(f"\n[bold red]Error:[/bold red] {e}")
            if args.debug:
                import traceback
                err_console.print(traceback.format_exc())


if __name__ == "__main__":
    main()
