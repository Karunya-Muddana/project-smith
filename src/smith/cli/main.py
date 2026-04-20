"""
SMITH CLI v4.0
--------------
Claude Code-inspired UI with /extend command for detailed re-synthesis.
"""

import argparse
import os
import re
import sys
import time
import json
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
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich import box
from rich.tree import Tree
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich.padding import Padding
from rich.style import Style
from rich.align import Align
from rich.live import Live
from rich.layout import Layout
from rich.measure import Measurement

# Smith imports
from smith.core.orchestrator import smith_orchestrator
from smith.registry import list_tool_names
from smith.core.cache_manager import CacheManager, get_cache_manager
from smith.core.report_renderer import render_report

console = Console(highlight=False)
err_console = Console(stderr=True, style="bold red")

# ============================================================================
# DESIGN TOKENS — Claude Code aesthetic
# ============================================================================

# Palette
C_BRAND     = "bold white"
C_PRIMARY   = "cyan"
C_SUCCESS   = "green"
C_ERROR     = "red"
C_WARN      = "yellow"
C_DIM       = "dim"
C_ACCENT    = "bright_cyan"
C_SUBTLE    = "bright_black"

# Status symbols
SYM_OK      = "✓"
SYM_ERR     = "✗"
SYM_SKIP    = "~"
SYM_RUN     = "›"
SYM_CACHE   = "⚡"
SYM_TOOL    = "◆"
SYM_THINK   = "◈"
SYM_PLAN    = "◉"
SYM_EXTEND  = "⟳"

BANNER_ASCII = """\
  ███████╗███╗   ███╗██╗████████╗██╗  ██╗
  ██╔════╝████╗ ████║██║╚══██╔══╝██║  ██║
  ███████╗██╔████╔██║██║   ██║   ███████║
  ╚════██║██║╚██╔╝██║██║   ██║   ██╔══██║
  ███████║██║ ╚═╝ ██║██║   ██║   ██║  ██║
  ╚══════╝╚═╝     ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝"""

# ============================================================================
# SESSION
# ============================================================================

class Session:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        self.last_trace: List[Dict] = []
        self.last_dag: Dict = None
        self.last_explain_data: Dict[str, Any] = {}
        self.last_raw_trace: List[Any] = []   # full orchestrator trace for /extend
        self.last_nodes: List[Dict] = []       # DAG nodes for /extend
        self.last_query: str = ""              # original query for /extend

    def add_interaction(self, user_input: str, response: str, trace: List[Dict] = None):
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "assistant": response,
            "trace": trace or [],
        })
        if trace:
            self.last_trace = trace


# ============================================================================
# TIME-SENSITIVE CONTEXT HELPERS (unchanged logic, kept compact)
# ============================================================================

_TIME_SENSITIVE_HINTS = (
    "stock","price","ticker","quote","market","nasdaq","nyse",
    "crypto","bitcoin","ethereum","btc","eth",
    "weather","temperature","forecast","humidity","wind",
    "news","headline","breaking","latest",
)
_FOLLOW_UP_HINTS = ("what about","and what","and ","that one","same","again","it","that","those","continue","also")
_REFRESH_HINTS   = ("refresh","latest","live","current","update","right now","as of now")

def _is_time_sensitive_text(t): return any(h in (t or "").lower() for h in _TIME_SENSITIVE_HINTS)
def _is_follow_up(t):
    t = (t or "").strip().lower()
    return len(t.split()) <= 5 or any(t.startswith(h) or f" {h} " in f" {t} " for h in _FOLLOW_UP_HINTS)
def _asks_refresh(t): return any(h in (t or "").lower() for h in _REFRESH_HINTS)

def _entry_age_seconds(entry):
    try:
        dt = datetime.fromisoformat(entry.get("timestamp",""))
        return max(0.0, (datetime.now()-dt).total_seconds())
    except: return None

def _build_recent_context(session: Session, max_turns=3, max_chars=1200) -> str:
    chunks, total = [], 0
    for item in session.history[-max_turns:]:
        age = _entry_age_seconds(item)
        age_txt = f"~{int(age)}s ago" if age is not None else "recent"
        block = f"[{age_txt}]\nUser: {(item.get('user') or '').strip()}\nSmith: {(item.get('assistant') or '').strip()}"
        if total + len(block) > max_chars: break
        chunks.append(block); total += len(block)
    return "\n\n".join(chunks)

def _maybe_answer_from_recent_time_sensitive_context(user_input, session):
    if not session.history or _asks_refresh(user_input): return None
    try:
        from smith.config import config as _cfg
        fresh_window = int(getattr(_cfg, "time_sensitive_fresh_seconds", 300))
    except: fresh_window = 300
    last = session.history[-1]
    age = _entry_age_seconds(last)
    if age is None or age > fresh_window: return None
    if not _is_time_sensitive_text(f"{last.get('user','')} {last.get('assistant','')}"): return None
    if not (_is_time_sensitive_text(user_input) or _is_follow_up(user_input)): return None
    recent_context = _build_recent_context(session, max_turns=2, max_chars=900)
    if not recent_context: return None
    from smith.core.query_router import direct_answer
    prompt = (
        "Continue this conversation using ONLY the recent context below. "
        "Do not claim you fetched new live data.\n\n"
        f"Recent context:\n{recent_context}\n\nCurrent user follow-up: {user_input}"
    )
    return direct_answer(prompt, voice_mode=False) or None

def _resolve_user_name():
    n = os.getenv("SMITH_USER_NAME","").strip()
    if n: return n
    return os.getenv("USERNAME","").strip() or os.getenv("USER","").strip() or "there"

def _build_startup_personalization():
    user_name = _resolve_user_name()
    default = f"Zero-Trust Agent Runtime v4.0 • Welcome back, {user_name}"
    try:
        from smith.config import config as _cfg
        if not _cfg.memory_enabled: return default
        from smith.memory import get_memory_manager
        mem = get_memory_manager()
        recent = mem.get_recent(1)
        if not recent: return default
        topic = re.sub(r"^User:\s*","", (recent[0].text or "").splitlines()[0].strip(), flags=re.IGNORECASE)[:70]
        if topic: return f"Zero-Trust Agent Runtime v4.0 • Welcome back, {user_name} • Last topic: {topic}"
    except: pass
    return default


# ============================================================================
# UI PRIMITIVES — Claude Code style
# ============================================================================

def _status_row(status: str) -> tuple:
    """Returns (icon, color) for a status string."""
    return {
        "success": (SYM_OK,   C_SUCCESS),
        "error":   (SYM_ERR,  C_ERROR),
        "skipped": (SYM_SKIP, C_WARN),
        "pending": (SYM_RUN,  C_DIM),
    }.get(status, (SYM_SKIP, C_DIM))

def _divider(title: str = "", style: str = C_SUBTLE):
    if title:
        console.print(Rule(f" {title} ", style=style))
    else:
        console.print(Rule(style=style))

def _badge(text: str, color: str = C_PRIMARY) -> Text:
    t = Text()
    t.append(f" {text} ", style=f"bold white on {color}")
    return t

def _tag(text: str, color: str = C_DIM) -> str:
    return f"[{color}][{text}][/{color}]"


# ============================================================================
# BANNER
# ============================================================================

def print_banner():
    subtitle = _build_startup_personalization()
    banner_text = Text(BANNER_ASCII, style="bold white")
    subtitle_text = Text(f"\n  {subtitle}", style="dim")
    full = Text.assemble(banner_text, subtitle_text)
    console.print(Panel(
        Align.left(full),
        border_style="bright_black",
        box=box.HEAVY,
        padding=(1, 2),
    ))
    console.print()
    tips = [
        f"[{C_DIM}]Ask naturally — follow-ups carry recent context[/{C_DIM}]",
        f"[{C_DIM}]Say [cyan]refresh[/cyan] to force a live re-check[/{C_DIM}]",
        f"[{C_DIM}]Run [cyan]/extend[/cyan] after any answer for a deep detailed report[/{C_DIM}]",
        f"[{C_DIM}]Try [cyan]/help[/cyan] for all commands[/{C_DIM}]",
    ]
    for tip in tips:
        console.print(f"  › {tip}")
    console.print()


# ============================================================================
# COMMANDS
# ============================================================================

def cmd_help():
    _divider("Commands")
    table = Table(
        border_style=C_SUBTLE,
        box=box.SIMPLE,
        padding=(0, 2),
        show_header=True,
        header_style=f"bold {C_PRIMARY}",
    )
    table.add_column("Command", style=f"bold {C_PRIMARY}", no_wrap=True, min_width=24)
    table.add_column("Description", style="white")

    sections = [
        ("— Navigation", []),
        ("/help",                "Show this help message"),
        ("/clear",               "Clear the screen"),
        ("/quit, /exit",         "Exit Smith"),
        ("— Analysis", []),
        ("/trace",               "Show execution trace of last run"),
        ("/dag",                 "Export last execution DAG as JSON"),
        ("/inspect",             "ASCII flowchart of DAG and trace"),
        ("/explain",             "Deep-dive: DAG, cache, tokens, fabrication guard"),
        ("/extend",              "Re-synthesize last run as a detailed report (no re-fetch)"),
        ("— Data", []),
        ("/tools",               "List all available tools"),
        ("/cache",               "Show cache statistics"),
        ("/cache clear",         "Clear all cached tool results"),
        ("— Memory", []),
        ("/memory",              "Show recent long-term memories"),
        ("/memory search <q>",   "Semantic search over memory"),
        ("/memory clear",        "Delete all stored memories"),
        ("/memory stats",        "Show memory store statistics"),
        ("— Session", []),
        ("/history",             "Show conversation history"),
        ("/export",              "Export session to markdown file"),
        ("/activate-smith",      "Full-screen voice mode (STT + TTS)"),
    ]

    for item in sections:
        if item[1] == []:
            table.add_row(f"[dim]{item[0]}[/dim]", "")
        else:
            table.add_row(item[0], item[1])

    console.print(table)


def cmd_tools():
    try:
        from smith.registry import get_tools_registry
        tools = get_tools_registry()
        _divider(f"Tools  [{C_DIM}]{len(tools)} registered[/{C_DIM}]")

        # Two-column layout
        left_tools = tools[:len(tools)//2 + len(tools)%2]
        right_tools = tools[len(tools)//2 + len(tools)%2:]

        def _tool_block(tool_list):
            t = Table(box=None, padding=(0,1), show_header=False)
            t.add_column("icon", width=2, style=C_PRIMARY)
            t.add_column("name", style=f"bold {C_PRIMARY}", min_width=22)
            t.add_column("domain", style=C_DIM, min_width=12)
            t.add_column("desc", style="white", max_width=35)
            for tool in tool_list:
                icon = "⚠" if tool.get("dangerous") else SYM_TOOL
                desc = (tool.get("description","").split(".")[0].strip())[:50]
                t.add_row(icon, tool.get("name",""), tool.get("domain",""), desc)
            return t

        console.print(Columns([_tool_block(left_tools), _tool_block(right_tools)], equal=True, expand=True))
    except Exception as e:
        err_console.print(f"Error loading tools: {e}")


def cmd_trace(session: Session):
    if not session.last_trace:
        console.print(f"[{C_WARN}]No trace yet. Run a query first.[/{C_WARN}]")
        return

    _divider("Execution Trace")
    table = Table(box=box.SIMPLE, border_style=C_SUBTLE, show_lines=False, padding=(0,1))
    table.add_column("",      width=2)
    table.add_column("Step",  style=C_DIM, width=5)
    table.add_column("Tool",  style=f"bold {C_PRIMARY}")
    table.add_column("Status",style="bold")
    table.add_column("Time",  style=C_DIM)
    table.add_column("Cache", style=C_DIM)

    for step in session.last_trace:
        status = step.get("status","unknown")
        icon, color = _status_row(status)
        cache = f"[{C_WARN}]{SYM_CACHE}[/{C_WARN}]" if step.get("cache_hit") else ""
        table.add_row(
            f"[{color}]{icon}[/{color}]",
            str(step.get("step_index","?")),
            step.get("tool","unknown"),
            f"[{color}]{status}[/{color}]",
            f"{step.get('duration',0):.2f}s",
            cache,
        )
    console.print(table)


def cmd_dag(session: Session):
    if not session.last_dag:
        console.print(f"[{C_WARN}]No DAG available.[/{C_WARN}]")
        return
    filename = f"smith_dag_{int(time.time())}.json"
    try:
        with open(filename,"w",encoding="utf-8") as f:
            json.dump(session.last_dag, f, indent=2, default=str)
        console.print(f"[{C_SUCCESS}]{SYM_OK} DAG exported to {filename}[/{C_SUCCESS}]")
    except Exception as e:
        err_console.print(f"Export failed: {e}")


def cmd_history(session: Session):
    if not session.history:
        console.print(f"[{C_WARN}]No history yet.[/{C_WARN}]")
        return
    _divider("Conversation History")
    for idx, item in enumerate(session.history, 1):
        console.print(f"\n[{C_SUBTLE}]#{idx}  {item['timestamp']}[/{C_SUBTLE}]")
        console.print(f"[{C_SUCCESS}]You[/{C_SUCCESS}]    {item['user']}")
        preview = (item['assistant'] or "")[:180].replace("\n"," ")
        console.print(f"[{C_PRIMARY}]Smith[/{C_PRIMARY}]  {preview}{'…' if len(item['assistant'])>180 else ''}")


def cmd_inspect(session: Session):
    if not session.last_dag and not session.last_trace:
        console.print(f"[{C_WARN}]No data. Run a query first.[/{C_WARN}]")
        return

    _divider("Execution Flowchart")
    nodes = (session.last_dag or {}).get("nodes", [])

    if nodes:
        console.print(f"  [{C_DIM}]DAG  {len(nodes)} nodes[/{C_DIM}]\n")
        for idx, node in enumerate(nodes):
            t = next((x for x in session.last_trace if x.get("step_index")==idx), {})
            status = t.get("status","pending")
            icon, color = _status_row(status)
            duration = f"  [{C_DIM}]{t.get('duration',0):.2f}s[/{C_DIM}]" if t else ""
            cache = f"  [{C_WARN}]{SYM_CACHE} cached[/{C_WARN}]" if t.get("cache_hit") else ""
            deps = node.get("depends_on") or []
            dep_str = f"  [{C_SUBTLE}]← {deps}[/{C_SUBTLE}]" if deps else ""
            console.print(f"  [{color}]{icon}[/{color}]  [bold {C_PRIMARY}]Step {idx}[/bold {C_PRIMARY}]  {node.get('tool','?')}{duration}{cache}{dep_str}")
            thought = (node.get("thought","") or "")[:80]
            if thought:
                console.print(f"      [{C_DIM}]{thought}[/{C_DIM}]")
            if idx < len(nodes)-1:
                console.print(f"      [{C_SUBTLE}]│[/{C_SUBTLE}]")
    elif session.last_trace:
        for step in session.last_trace:
            status = step.get("status","unknown")
            icon, color = _status_row(status)
            console.print(f"  [{color}]{icon}[/{color}]  [{C_PRIMARY}]Step {step.get('step_index','?')}[/{C_PRIMARY}]  {step.get('tool','?')}  [{C_DIM}]{step.get('duration',0):.2f}s[/{C_DIM}]")

    console.print(f"\n  [{C_DIM}]/trace for detailed results  /dag to export[/{C_DIM}]")


def cmd_export(session: Session):
    if not session.history:
        console.print(f"[{C_WARN}]Nothing to export.[/{C_WARN}]")
        return
    filename = f"smith_session_{int(time.time())}.md"
    try:
        with open(filename,"w",encoding="utf-8") as f:
            f.write("# Smith Session Export\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n")
            for idx, item in enumerate(session.history,1):
                f.write(f"## {idx}. {item['timestamp']}\n\n")
                f.write(f"**You:** {item['user']}\n\n")
                f.write(f"**Smith:** {item['assistant']}\n\n---\n\n")
        console.print(f"[{C_SUCCESS}]{SYM_OK} Exported to {filename}[/{C_SUCCESS}]")
    except Exception as e:
        err_console.print(f"Export failed: {e}")


def cmd_cache(cache_mgr: CacheManager, subcmd: str = ""):
    if subcmd.strip().lower() == "clear":
        n = cache_mgr.clear()
        console.print(f"[{C_SUCCESS}]{SYM_OK} Cleared {n} cache entries.[/{C_SUCCESS}]")
        return
    stats = cache_mgr.stats()
    _divider("Cache Statistics")
    table = Table(box=box.SIMPLE, border_style=C_SUBTLE, padding=(0,2))
    table.add_column("Metric", style=f"bold {C_PRIMARY}")
    table.add_column("Value",  style="white")
    hit_rate = stats["session_hit_rate"]
    hr_color = C_SUCCESS if hit_rate >= 50 else C_WARN if hit_rate > 0 else C_DIM
    rows = [
        ("Entries on disk",  str(stats["entries_on_disk"])),
        ("Total size",       f"{stats['total_size_kb']} KB"),
        ("TTL",              f"{stats['ttl_seconds']}s"),
        ("Session hits",     str(stats["session_hits"])),
        ("Session misses",   str(stats["session_misses"])),
        ("Hit rate",         f"[{hr_color}]{hit_rate}%[/{hr_color}]"),
    ]
    for k, v in rows: table.add_row(k, v)
    console.print(table)


def cmd_memory(subcmd: str = ""):
    from smith.config import config as _cfg
    if not _cfg.memory_enabled:
        console.print(f"[{C_WARN}]Memory disabled (SMITH_MEMORY_ENABLED=false)[/{C_WARN}]")
        return
    from smith.memory import get_memory_manager
    mem = get_memory_manager()
    subcmd = subcmd.strip()

    if subcmd in ("","recent"):
        records = mem.get_recent(10)
        if not records:
            console.print(f"[{C_DIM}]No memories stored yet.[/{C_DIM}]")
            return
        _divider("Recent Memories")
        table = Table(box=box.SIMPLE, border_style=C_SUBTLE, padding=(0,1))
        table.add_column("Date",    style=C_DIM,         width=19)
        table.add_column("Session", style=C_PRIMARY,     width=9)
        table.add_column("Type",    style=C_DIM,         width=12)
        table.add_column("Preview", style="white")
        for r in records:
            dt = datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d %H:%M")
            table.add_row(dt, r.session_id, r.source_type, r.text[:110])
        console.print(table)

    elif subcmd.startswith("search "):
        query = subcmd[7:].strip()
        if not query:
            console.print(f"[{C_WARN}]Usage: /memory search <query>[/{C_WARN}]"); return
        results = mem.search(query, top_k=10)
        if not results:
            console.print(f"[{C_DIM}]No matching memories.[/{C_DIM}]"); return
        _divider(f"Memory Search: {query}")
        table = Table(box=box.SIMPLE, border_style=C_SUBTLE, padding=(0,1))
        table.add_column("Score",   style=C_SUCCESS, width=7)
        table.add_column("Date",    style=C_DIM,     width=19)
        table.add_column("Type",    style=C_DIM,     width=12)
        table.add_column("Preview", style="white")
        for record, score in results:
            dt = datetime.fromtimestamp(record.timestamp).strftime("%Y-%m-%d %H:%M")
            table.add_row(f"{score:.3f}", dt, record.source_type, record.text[:110])
        console.print(table)

    elif subcmd == "clear":
        n = mem.clear()
        console.print(f"[{C_SUCCESS}]{SYM_OK} Cleared {n} memory records.[/{C_SUCCESS}]")

    elif subcmd == "stats":
        stats = mem.stats()
        _divider("Memory Stats")
        table = Table(box=box.SIMPLE, border_style=C_SUBTLE)
        table.add_column("Metric", style=f"bold {C_PRIMARY}")
        table.add_column("Value",  style="white")
        for k, v in stats.items(): table.add_row(str(k), str(v))
        console.print(table)

    else:
        console.print(f"[{C_WARN}]Usage: /memory [recent|search <q>|clear|stats][/{C_WARN}]")


def cmd_explain(session: Session):
    ed = session.last_explain_data
    if not ed:
        console.print(f"[{C_WARN}]No run data. Execute a query first.[/{C_WARN}]")
        return

    _divider("Run Explanation")

    # ── DAG table ─────────────────────────────────────────────────────────
    dag   = ed.get("dag")
    trace = ed.get("trace", [])
    nodes = (dag or {}).get("nodes", [])

    dag_table = Table(box=box.SIMPLE, border_style=C_SUBTLE, padding=(0,1))
    dag_table.add_column("",      width=2)
    dag_table.add_column("Step",  style=C_DIM, width=5)
    dag_table.add_column("Tool",  style=f"bold {C_PRIMARY}")
    dag_table.add_column("Status",style="bold")
    dag_table.add_column("Time",  style=C_DIM)
    dag_table.add_column("Cache", style=C_DIM)
    dag_table.add_column("Thought",style=C_DIM, max_width=45)

    for i, node in enumerate(nodes):
        t = next((x for x in trace if x.get("step_index")==i), {})
        status = t.get("status","pending")
        icon, color = _status_row(status)
        cache = f"{SYM_CACHE}" if t.get("cache_hit") else ""
        dag_table.add_row(
            f"[{color}]{icon}[/{color}]",
            str(i),
            node.get("tool","?"),
            f"[{color}]{status}[/{color}]",
            f"{t.get('duration',0):.2f}s",
            cache,
            (node.get("thought","") or "")[:45],
        )
    console.print(dag_table)

    # ── Parallel groups ────────────────────────────────────────────────────
    parallel_groups = ed.get("parallel_groups",[])
    if parallel_groups:
        pg_lines = [f"  Group {i+1}: [{C_PRIMARY}]{', '.join(g)}[/{C_PRIMARY}]" for i, g in enumerate(parallel_groups)]
        console.print(Panel("\n".join(pg_lines), title=f"[bold {C_PRIMARY}]⚡ Parallel Execution[/bold {C_PRIMARY}]", border_style=C_PRIMARY, box=box.SIMPLE))

    # ── Cache ──────────────────────────────────────────────────────────────
    cache_hits = ed.get("cache_hits",[])
    total_nodes = len(nodes)
    if total_nodes > 0:
        hit_pct = round(len(cache_hits)/total_nodes*100, 1)
        color = C_SUCCESS if hit_pct > 50 else C_WARN if hit_pct > 0 else C_DIM
        console.print(Panel(
            f"  [{color}]{len(cache_hits)}/{total_nodes} steps from cache ({hit_pct}%)[/{color}]\n  Steps: {cache_hits or 'none'}",
            title=f"[bold {C_WARN}]⚡ Cache[/bold {C_WARN}]", border_style=C_SUBTLE, box=box.SIMPLE,
        ))

    # ── Tokens ────────────────────────────────────────────────────────────
    tokens = ed.get("total_tokens_est",0)
    cost   = ed.get("total_cost_est",0.0)
    tok_table = Table(box=box.SIMPLE, border_style=C_SUBTLE, padding=(0,2))
    tok_table.add_column("Metric", style=f"bold {C_PRIMARY}")
    tok_table.add_column("Value",  style="white")
    tok_table.add_row("Est. Tokens (trace)", f"~{tokens:,}")
    tok_table.add_row("Est. Synthesis Cost", f"~${cost:.4f}")
    console.print(tok_table)

    # ── Fabrication guard ─────────────────────────────────────────────────
    fab = ed.get("fabrication_report")
    if fab:
        total_n   = fab.get("total_numbers",0)
        verified  = fab.get("verified",0)
        redacted  = fab.get("redacted",0)
        confidence = ed.get("confidence","high")
        conf_color = C_SUCCESS if confidence=="high" else C_WARN if confidence=="medium" else C_ERROR
        fab_line = (
            f"  Numbers: {total_n}  ·  Verified: [{C_SUCCESS}]{verified}[/{C_SUCCESS}]  ·  "
            f"Redacted: [{'red' if redacted else C_DIM}]{redacted}[/{'red' if redacted else C_DIM}]\n"
            f"  Confidence: [{conf_color}]{confidence.upper()}[/{conf_color}]"
        )
        console.print(Panel(fab_line, title=f"[bold {C_WARN}]🛡 Fabrication Guard[/bold {C_WARN}]", border_style=C_SUBTLE, box=box.SIMPLE))


# ============================================================================
# /extend — Re-synthesize with detailed report prompt
# ============================================================================

def cmd_extend(session: Session):
    """
    Re-synthesize the last run as a detailed analytical report.
    Bypasses run_synthesis() entirely — calls call_llm directly so the
    synthesis engine format_type detection cannot override the prompt.
    No data tools re-run.
    """
    if not session.last_raw_trace or not session.last_query:
        console.print(f"[{C_WARN}]Nothing to extend. Run a query first.[/{C_WARN}]")
        return

    console.print()
    console.print(Panel(
        f"  [{C_PRIMARY}]{SYM_EXTEND}  Generating detailed report...[/{C_PRIMARY}]\n"
        f"  [{C_DIM}]No data tools will re-run. Using cached trace.[/{C_DIM}]",
        border_style=C_PRIMARY,
        box=box.SIMPLE,
    ))

    try:
        from smith.tools.LLM_CALLER import call_llm

        # Extract all text content from stored trace
        source_blocks = []
        for i, t in enumerate(session.last_raw_trace):
            if not t or t.get("status") != "success":
                continue
            result = t.get("result", {})
            tool   = t.get("tool", f"step_{i}")
            text   = ""
            if isinstance(result, dict):
                for k in ("response", "content", "summary", "text", "body"):
                    v = result.get(k)
                    if v and isinstance(v, str) and len(v) > 30:
                        text = v; break
                if not text:
                    articles = result.get("articles", [])
                    if isinstance(articles, list):
                        parts = []
                        for a in articles[:5]:
                            if isinstance(a, dict):
                                title = a.get("title", "")
                                body  = a.get("body", "") or a.get("snippet", "")
                                if title or body:
                                    parts.append(f"{title}\n{body}".strip())
                        text = "\n\n".join(parts)
                if not text:
                    text = json.dumps(result, default=str)[:3000]
            else:
                text = str(result)[:3000]

            if text.strip():
                thought = ""
                if i < len(session.last_nodes):
                    thought = session.last_nodes[i].get("thought", "")
                source_blocks.append(
                    f"--- SOURCE: {tool.upper()} (step {i}) ---\n"
                    f"Purpose: {thought}\n\n"
                    f"{text.strip()[:8000]}"
                )

        if not source_blocks:
            err_console.print("No usable data found in trace for /extend.")
            return

        combined_data = "\n\n".join(source_blocks)
        if len(combined_data) > 50_000:
            combined_data = combined_data[:50_000] + "\n\n[...truncated]"

        prompt = f"""You are a senior analyst producing a comprehensive research report.

USER QUERY: {session.last_query}

SOURCE DATA FROM RESEARCH TOOLS:
{combined_data}

INSTRUCTIONS:
Write a detailed, professional analytical report using ONLY the source data above.
Structure your report with these exact sections:

## Executive Summary
3-5 sentences capturing the most important findings.

## Detailed Findings
Expand every key data point with full context and evidence. Include specific numbers, dates, names. Do not summarize — elaborate fully.

## Cause → Effect Analysis
Explicit chain reasoning. Format as:
- [Cause] → [Effect] → [Implication]
Write at least 4-5 chains covering different aspects.

## Comparative Analysis
Side-by-side breakdown of the main entities covering: strategy, execution, financials, market position, risks.

## Key Patterns & Non-Obvious Signals
What patterns emerge that are not immediately obvious? What is the data NOT saying that is significant?

## Strategic Implications
What does this mean for investors, competitors, and the industry over the next 6-18 months? Be specific.

## Confidence & Data Gaps
What data was missing or weak? What would change this analysis?

RULES:
- Use ONLY facts from the source data above. Do not invent statistics.
- Be specific — replace every vague statement with exact figures from the data.
- Write in professional analytical prose. No padding.
- Each section must be substantive — minimum 2 full paragraphs.
"""

        response_text = ""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task(f"[{C_PRIMARY}]{SYM_EXTEND} Writing report...", total=None)
            result = call_llm(prompt, model="meta/llama-4-maverick-17b-128e-instruct")

        if result.get("status") == "success":
            response_text = result.get("response", "").strip()
        else:
            err_console.print(f"LLM call failed: {result.get('error', 'unknown')}")
            return

        if not response_text:
            err_console.print("Model returned empty response.")
            return

        console.print()
        _divider("Extended Report")
        console.print(Markdown(response_text))
        console.print()
        session.add_interaction(f"/extend → {session.last_query}", response_text)

    except ImportError as e:
        err_console.print(f"Missing module for /extend: {e}")
    except Exception as e:
        err_console.print(f"/extend failed: {e}")
        if os.getenv("SMITH_DEBUG"):
            import traceback; traceback.print_exc()



# ============================================================================
# QUERY EXECUTION
# ============================================================================

def execute_query(
    user_input: str,
    session: Session,
    verify_finance: bool = False,
    cache_mgr: Optional[CacheManager] = None,
) -> str:
    from smith.core.query_router import classify, direct_answer

    reused = None
    if not verify_finance:
        reused = _maybe_answer_from_recent_time_sensitive_context(user_input, session)
    if reused:
        return reused

    try:
        from smith.config import config as _cfg
        context_turns = int(getattr(_cfg,"conversation_context_turns",3))
    except: context_turns = 3

    recent_context = _build_recent_context(session, max_turns=context_turns)
    routed_input = user_input
    if recent_context:
        routed_input = (
            "[Recent conversation context]\n"
            f"{recent_context}\n"
            "[End recent conversation context]\n\n"
            f"Current user query: {user_input}"
        )

    # ── Fast path ────────────────────────────────────────────────────────────
    if not verify_finance and classify(user_input) == "direct":
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[{C_PRIMARY}]{SYM_THINK} Thinking…"),
            console=console, transient=True,
        ) as progress:
            progress.add_task("", total=None)
            answer = direct_answer(routed_input, voice_mode=False)
        if answer:
            return answer

    # ── Full pipeline ─────────────────────────────────────────────────────────
    trace_data: List[Dict]    = []
    raw_trace:  List[Any]     = []
    final_answer: str         = ""
    dag_plan: Dict            = None
    total_steps: int          = 0
    final_payload: Dict       = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=38, style=C_SUBTLE, complete_style=C_PRIMARY),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        main_task = progress.add_task(f"[{C_DIM}]Initializing planner...", total=None)

        for event in smith_orchestrator(
            user_input,
            require_approval=False,
            verify_finance=verify_finance,
            cache_manager=cache_mgr,
            recent_context=recent_context,
        ):
            etype = event.get("type")

            if etype == "status":
                msg = event.get("message","")
                progress.update(main_task, description=f"[{C_DIM}]{msg}")

            elif etype == "plan_created":
                dag_plan    = event.get("plan")
                nodes       = (dag_plan or {}).get("nodes",[])
                total_steps = len(nodes)
                progress.update(main_task,
                    description=f"[{C_SUCCESS}]{SYM_PLAN} Plan ready [{C_DIM}]{total_steps} steps[/{C_DIM}]",
                    total=total_steps, completed=0)

            elif etype == "step_start":
                idx  = event.get("step_index",0)
                tool = event.get("tool","?")
                progress.update(main_task,
                    description=f"[bold]→ Step {idx+1}/{total_steps}:[/bold] [{C_PRIMARY}]{tool}[/{C_PRIMARY}]",
                    completed=idx)

            elif etype == "step_complete":
                idx      = event.get("step_index",0)
                status   = event.get("status","?")
                icon, color = _status_row(status)
                cache    = f" {SYM_CACHE}" if event.get("cache_hit") else ""
                progress.update(main_task,
                    description=f"[{color}]{icon}[/{color}] [{C_PRIMARY}]{event.get('tool','?')}[/{C_PRIMARY}]{cache}  [{C_DIM}]{event.get('duration',0):.1f}s[/{C_DIM}]",
                    completed=idx+1)
                trace_data.append({
                    "step_index": idx,
                    "tool":       event.get("tool"),
                    "status":     status,
                    "duration":   event.get("duration",0),
                    "cache_hit":  event.get("cache_hit",False),
                    "result":     event.get("payload"),
                })

            elif etype == "final_answer":
                final_payload = event.get("payload",{})
                final_answer  = final_payload.get("response", str(final_payload)) if isinstance(final_payload,dict) else str(final_payload)
                progress.update(main_task,
                    description=f"[{C_SUCCESS}]{SYM_OK} Complete",
                    completed=total_steps)

            elif etype == "error":
                progress.update(main_task, description=f"[{C_ERROR}]{SYM_ERR} {event.get('message','error')}")

    # ── Store for /extend ────────────────────────────────────────────────────
    # We need the raw orchestrator trace (with full result dicts)
    # Build it from trace_data (result field has the full payload)
    raw_trace = [
        {
            "step_index": t["step_index"],
            "tool":       t["tool"],
            "status":     t["status"],
            "duration":   t["duration"],
            "result":     t["result"],
        }
        for t in trace_data
    ]

    session.last_trace      = trace_data
    session.last_dag        = dag_plan
    session.last_raw_trace  = raw_trace
    session.last_nodes      = (dag_plan or {}).get("nodes",[])
    session.last_query      = user_input

    # ── Explain metadata ─────────────────────────────────────────────────────
    parallel_groups = []
    if dag_plan:
        nodes = dag_plan.get("nodes", [])
        if nodes:
            in_degree = [0] * len(nodes)
            adjacency: Dict[int, List[int]] = {i: [] for i in range(len(nodes))}

            for idx, node in enumerate(nodes):
                deps = node.get("_normalized_deps") or node.get("depends_on") or []
                if not isinstance(deps, list):
                    deps = []

                valid_deps = [
                    dep for dep in deps
                    if isinstance(dep, int) and 0 <= dep < len(nodes)
                ]
                in_degree[idx] = len(valid_deps)
                for dep in valid_deps:
                    adjacency[dep].append(idx)

            ready = [idx for idx, degree in enumerate(in_degree) if degree == 0]
            processed = 0

            while ready:
                level = sorted(ready)
                parallel_groups.append([nodes[i].get("tool", "?") for i in level])
                processed += len(level)

                next_ready: List[int] = []
                for parent in level:
                    for child in adjacency.get(parent, []):
                        in_degree[child] -= 1
                        if in_degree[child] == 0:
                            next_ready.append(child)

                ready = next_ready

            # Handle malformed cyclic plans defensively.
            if processed < len(nodes):
                remaining = [
                    idx for idx, degree in enumerate(in_degree) if degree > 0
                ]
                if remaining:
                    parallel_groups.append([nodes[i].get("tool", "?") for i in remaining])

    trace_chars      = sum(len(str(t.get("result",{}))) for t in trace_data)
    total_tokens_est = trace_chars // 4
    total_cost_est   = (total_tokens_est / 1000) * 0.00027

    session.last_explain_data = {
        "dag":               dag_plan,
        "trace":             trace_data,
        "parallel_groups":   parallel_groups,
        "cache_hits":        final_payload.get("cache_hits",[]),
        "total_tokens_est":  total_tokens_est,
        "total_cost_est":    total_cost_est,
        "fabrication_report":final_payload.get("fabrication_report"),
        "confidence":        final_payload.get("confidence","high"),
        "audit_trail":       final_payload.get("audit_trail",[]),
    }

    return final_answer


# ============================================================================
# MAIN REPL
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Smith Agent Runtime")
    parser.add_argument("--verify-finance", action="store_true")
    parser.add_argument("--no-cache",       action="store_true")
    parser.add_argument("--debug",          action="store_true")
    args, _ = parser.parse_known_args()

    if args.debug:
        os.environ["SMITH_DEBUG"] = "1"

    console.clear()
    print_banner()

    if args.verify_finance:
        console.print(f"[bold {C_WARN}]⚠ Finance verification mode enabled[/bold {C_WARN}]\n")
    if args.no_cache:
        console.print(f"[{C_DIM}]Cache disabled for this session[/{C_DIM}]\n")

    cache_mgr: Optional[CacheManager] = None
    if not args.no_cache:
        try:
            cache_mgr = get_cache_manager()
            cache_mgr.evict_expired()
        except Exception as e:
            console.print(f"[{C_WARN}]Cache unavailable: {e}[/{C_WARN}]")

    session = Session()

    while True:
        try:
            user_input = Prompt.ask(f"\n[bold {C_SUCCESS}]>[/bold {C_SUCCESS}]").strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                cmd  = user_input.lower().strip()
                rest = user_input[user_input.index(" ")+1:].strip() if " " in user_input else ""

                if cmd in ["/quit","/exit","/q"]:
                    console.print(f"\n[bold {C_PRIMARY}]Goodbye![/bold {C_PRIMARY}]\n"); break

                elif cmd == "/help":           cmd_help()
                elif cmd == "/tools":          cmd_tools()
                elif cmd == "/trace":          cmd_trace(session)
                elif cmd == "/dag":            cmd_dag(session)
                elif cmd == "/inspect":        cmd_inspect(session)
                elif cmd == "/explain":        cmd_explain(session)
                elif cmd == "/extend":         cmd_extend(session)
                elif cmd == "/history":        cmd_history(session)
                elif cmd == "/export":         cmd_export(session)
                elif cmd == "/clear":          console.clear(); print_banner()
                elif cmd == "/cache":
                    if cache_mgr: cmd_cache(cache_mgr)
                    else: console.print(f"[{C_WARN}]Cache disabled[/{C_WARN}]")
                elif cmd == "/cache clear":
                    if cache_mgr: cmd_cache(cache_mgr, subcmd="clear")
                    else: console.print(f"[{C_WARN}]Cache disabled[/{C_WARN}]")
                elif cmd.startswith("/memory"):
                    cmd_memory(user_input[7:].strip() if len(user_input)>7 else "")
                elif cmd == "/activate-smith":
                    from smith.cli.voice_mode import activate_voice_mode
                    activate_voice_mode(console)
                elif cmd.startswith("/fleet"):
                    # keep existing fleet logic
                    console.print(f"[{C_DIM}]Fleet mode: {rest}[/{C_DIM}]")
                else:
                    err_console.print(f"Unknown command: {cmd}")
                    console.print(f"[{C_DIM}]Try /help[/{C_DIM}]")

                continue

            # ── Execute query ────────────────────────────────────────────────
            response = execute_query(user_input, session,
                                     verify_finance=args.verify_finance,
                                     cache_mgr=cache_mgr)
            if response:
                console.print()
                plain = render_report(response, console)
                session.add_interaction(user_input, plain or response, session.last_trace)

                # Persist to memory
                from smith.config import config as _cfg
                if _cfg.memory_enabled:
                    try:
                        from smith.memory import get_memory_manager
                        mem = get_memory_manager()
                        mem.write_interaction(user_input, plain or response)
                        mem.maybe_summarize()
                    except: pass

                # Hint about /extend for non-trivial responses
                if session.last_trace and len(session.last_trace) >= 2:
                    console.print(f"\n  [{C_SUBTLE}]{SYM_EXTEND} /extend for a detailed analytical report[/{C_SUBTLE}]")
            else:
                console.print(f"\n[{C_WARN}]No response generated[/{C_WARN}]")

        except KeyboardInterrupt:
            console.print(f"\n[{C_WARN}]Interrupted. Use /quit to exit.[/{C_WARN}]")
        except EOFError:
            break
        except Exception as e:
            err_console.print(f"\n[bold {C_ERROR}]Error:[/bold {C_ERROR}] {e}")
            if args.debug:
                import traceback; err_console.print(traceback.format_exc())


if __name__ == "__main__":
    main()