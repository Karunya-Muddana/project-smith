"""
Code Agent — Full Agentic Coding Pipeline v3
=============================================
Pipeline:
  1. RESEARCH   — DuckDuckGo search for docs, pitfalls, best practices
  2. GENERATE   — deepseek-r1 writes code with full context + negative constraints
  3. STATIC     — ruff (F401/F821) + regex bad-pattern detector
  4. EXECUTION  — py_compile + mypy --strict + import probe
  5. CRITIQUE   — llama-3.1-8b-instant produces JSON verdict + score
  6. FIX        — deepseek-r1 fixes all issues with full critique text
  7. OUTPUT     — Polished code with phase-by-phase progress bar in CLI

Progress bar renders on stderr using a separate Rich console so it doesn't
conflict with the orchestrator's main Progress spinner on stdout.
"""

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Optional

logger = logging.getLogger("smith.tools.code_agent")

MAX_ITERATIONS = 2      # critique → fix rounds after initial generate
SEARCH_RESULTS = 5      # DDG results per query

# ── Model selection ───────────────────────────────────────────────────────────
# deepseek-r1 is code-specialized with internal chain-of-thought reasoning
_HEAVY_MODEL = "deepseek-r1-distill-llama-70b"
_FAST_MODEL  = "llama-3.1-8b-instant"   # critique only — outputs ~50 token JSON

# ── Language display names ────────────────────────────────────────────────────
_LANG_DISPLAY = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "rust": "Rust", "go": "Go", "java": "Java", "cpp": "C++", "c": "C",
    "csharp": "C#", "bash": "Shell", "sql": "SQL", "html": "HTML",
    "css": "CSS", "ruby": "Ruby",
}

# ── Known-bad patterns (deterministic, checked every round) ──────────────────
_BAD_PATTERNS = {
    "python": [
        (r"\bproxies\s*=\s*\{", "httpx: use proxy= (singular str) on AsyncClient, not proxies={} dict"),
        (r"from typing import.*\b(List|Dict|Tuple|Optional|Set)\b",
         "Python 3.11+: use built-in list[], dict[], tuple[], str|None — not typing shims"),
        (r"raise\s+Exception\s*\(", "Never raise bare Exception — use a typed custom exception class"),
        (r"logging\.basicConfig\s*\(", "Library code must not call logging.basicConfig — only app entrypoints"),
        (r"return await self\.\w+\(", "Recursion in except block — use a for-loop with a retry counter instead"),
    ],
}


# ── Rich progress bar (stderr, doesn't fight orchestrator's stdout spinner) ───

def _make_progress():
    """Create a Rich Progress that renders to stderr."""
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
        from rich.console import Console
        err = Console(stderr=True, highlight=False)
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            TimeElapsedColumn(),
            console=err,
            transient=True,
        )
    except Exception:
        return None


class _PhaseProgress:
    """Context manager: shows a Rich phase progress bar on stderr."""

    # Phase weights (out of 100)
    PHASES = [
        ("🔍 Searching docs",         8),
        ("⚙️  Generating code",        25),
        ("🔬 Static analysis",        5),
        ("🔌 Execution gate (mypy)",  12),
        ("🧐 LLM critique",           15),
        ("🔧 Fixing issues",          25),
        ("✅ Finalising",              10),
    ]

    def __init__(self):
        self._progress = _make_progress()
        self._task = None
        self._phase_idx = 0
        self._completed = 0

    def __enter__(self):
        if self._progress:
            self._progress.start()
            self._task = self._progress.add_task(
                "Code Agent — starting…", total=100
            )
        return self

    def advance(self, phase_name: str = None):
        """Move to the next phase in the pipeline."""
        if not self._progress or self._task is None:
            return
        if self._phase_idx < len(self.PHASES):
            name, weight = self.PHASES[self._phase_idx]
            self._completed = min(self._completed + weight, 100)
            self._progress.update(
                self._task,
                description=phase_name or name,
                completed=self._completed,
            )
            self._phase_idx += 1

    def set_phase(self, description: str, pct: int = None):
        if not self._progress or self._task is None:
            return
        kwargs = {"description": description}
        if pct is not None:
            kwargs["completed"] = min(pct, 100)
        self._progress.update(self._task, **kwargs)

    def __exit__(self, *args):
        if self._progress:
            if self._task is not None:
                self._progress.update(self._task, completed=100, description="✅ Done")
            self._progress.stop()


# ── Internal LLM call ─────────────────────────────────────────────────────────

def _call_llm(prompt: str, model: str = None) -> str:
    from smith.tools.LLM_CALLER import call_llm
    if model is None:
        model = _HEAVY_MODEL
    result = call_llm(prompt, model=model)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error", "LLM call failed"))
    return result["response"]


# ── Phase 1: Research ─────────────────────────────────────────────────────────

def _search_docs(task: str, language: str) -> str:
    try:
        from smith.tools.GOOGLE_SEARCHER import perform_search, optimize_query
        queries = [
            f"{language} {task} best practices production 2024 modern API",
            f"{language} {task} common bugs pitfalls deprecated stackoverflow github",
        ]
        snippets = []
        for q in queries[:2]:
            opt = optimize_query(q)
            result = perform_search(opt, num_results=SEARCH_RESULTS)
            if result.get("status") == "success":
                for item in result.get("result", [])[:3]:
                    title = item.get("title", "")
                    body  = (item.get("content", "") or "")[:350]
                    link  = item.get("link", "")
                    if title or body:
                        snippets.append(f"• [{title}]({link})\n  {body}")
            time.sleep(1.5)
        if snippets:
            logger.info(f"CodeAgent: fetched {len(snippets)} doc snippets")
            return "\n\n".join(snippets[:6])
    except Exception as e:
        logger.warning(f"CodeAgent: doc search failed ({e})")
    return ""


# ── Phase 2: Generate prompt ──────────────────────────────────────────────────

_PITFALLS_PYTHON = """\
- httpx: use proxy= (str) on AsyncClient(), NOT proxies={{'http': ..., 'https': ...}}
- httpx: TimeoutException is a subclass of HTTPError — catch it BEFORE HTTPError or it's dead code
- httpx: HTTPStatusError (not HTTPError) has .response — catch HTTPStatusError separately for status checks
- httpx: AsyncClient created ONCE and reused; use async context manager (__aenter__/__aexit__)
- Retries: use a for-loop with a counter (for attempt in range(max_retries)) — NEVER recursion in except
- Backoff: exponential with jitter — delay = base * (2 ** attempt) + random.uniform(0, 1)
- Retry only: 429, 5xx — never 404, 403, 401
- asyncio: import at module top — never after first use
- Python 3.11+: list[], dict[], str | None — never from typing import List, Optional
- Logging: never call logging.basicConfig in library/module code"""

_INTERFACE_SCRAPER = """\
class AsyncScraper:
    def __init__(self, *, base_url: str, concurrency: int = 5,
                 proxy: str | None = None, timeout: float = 10.0,
                 max_retries: int = 3) -> None: ...
    async def fetch(self, path: str) -> str: ...          # HTML, uses retry loop
    async def parse(self, html: str) -> BeautifulSoup: ... # CPU work → executor
    async def __aenter__(self) -> AsyncScraper: ...
    async def __aexit__(self, *args: object) -> None: ..."""

_INTERFACE_DEFAULT = "(No fixed interface — design the cleanest API for the task.)"


def _pick_interface(task: str) -> str:
    return _INTERFACE_SCRAPER if any(w in task.lower() for w in ("scraper", "scrape", "crawl")) \
        else _INTERFACE_DEFAULT


_GENERATE_PROMPT = """\
You are a world-class {language} engineer using Python 3.11+.
You have chain-of-thought reasoning — THINK THROUGH each design decision before writing code.

TASK:
{task}

INTERFACE CONTRACT (implement exactly):
{interface}

REFERENCE MATERIAL (live docs):
{context}

KNOWN PITFALLS — documented bugs to avoid:
{pitfalls}

━━━ MANDATORY RULES ━━━
✅ DO:
  • Built-in types: list[], dict[], str | None (NOT typing.List, Optional)
  • proxy= (str) on httpx.AsyncClient — NOT proxies={{}} dict
  • Retry loop: for attempt in range(max_retries) — NEVER recursive self-call in except
  • Exponential backoff: delay = 1.0 * (2 ** attempt) + random.uniform(0, 1)
  • Catch httpx.TimeoutException BEFORE httpx.HTTPStatusError BEFORE httpx.HTTPError
  • Check status codes on httpx.HTTPStatusError (has .response), not base HTTPError
  • asyncio.Semaphore for concurrency limiting
  • Modern user-agents: Chrome 120+ (2024)
  • Custom exception classes, structured logging, full type hints, docstrings
  • Module-level docstring; if __name__ == "__main__" guard

❌ DO NOT:
  • Import anything unused
  • Call logging.basicConfig in module/library code
  • Retry 404/403/401 — only 429 and 5xx
  • Use random() * N for jitter (use random.uniform)
  • Hardcode credentials or real URLs as defaults
  • Put executable code at module level

━━━ OUTPUT FORMAT ━━━
```{language}
<complete, runnable code>
```
Then 2-3 sentences on key design decisions.
"""


# ── Phase 3: Static analysis ──────────────────────────────────────────────────

def _run_static_checks(code: str, language: str) -> list[str]:
    """Fast deterministic checks — runs first every round."""
    issues: list[str] = []
    if language != "python":
        return issues

    # AST parse
    try:
        ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]

    # asyncio import-before-use
    lines = code.splitlines()
    first_asyncio_import = next(
        (i + 1 for i, l in enumerate(lines) if re.match(r"^import asyncio", l.strip())), None
    )
    first_asyncio_use = next(
        (i + 1 for i, l in enumerate(lines)
         if "asyncio." in l and "import" not in l), None
    )
    if first_asyncio_use and first_asyncio_import and first_asyncio_use < first_asyncio_import:
        issues.append(
            f"NameError: asyncio used (line {first_asyncio_use}) before import (line {first_asyncio_import})"
        )

    # Regex bad-patterns
    for pattern, message in _BAD_PATTERNS.get(language, []):
        if re.search(pattern, code, re.MULTILINE):
            issues.append(f"Pattern: {message}")

    return issues


# ── Phase 4: Execution gate ───────────────────────────────────────────────────

def _run_execution_gate(code: str, language: str) -> list[str]:
    """
    Compile + mypy + ruff — deterministic, catches type errors and unused imports.
    Returns list of issues (empty = all clear).
    """
    issues: list[str] = []
    if language != "python":
        return issues

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmpfile = f.name

    try:
        # 1. py_compile
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", tmpfile],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            issues.append(f"py_compile: {r.stderr.strip()}")
            return issues  # no point running mypy on broken code

        # 2. mypy --strict (catches type errors like e.response on base HTTPError)
        r = subprocess.run(
            [sys.executable, "-m", "mypy", tmpfile,
             "--strict", "--ignore-missing-imports",
             "--no-error-summary", "--no-pretty",
             "--hide-error-codes"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            for line in r.stdout.strip().splitlines()[:6]:
                clean = re.sub(r"^.*?\.py:", "line", line)
                if clean.strip() and "note:" not in clean:
                    issues.append(f"mypy: {clean.strip()}")

        # 3. ruff — unused imports (F401), undefined names (F821)
        r = subprocess.run(
            ["ruff", "check", "--select", "F401,F811,F821",
             "--output-format", "text", tmpfile],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines()[:5]:
                clean = re.sub(r"^.*?\.py:", "line", line)
                issues.append(f"ruff: {clean.strip()}")

    except FileNotFoundError as e:
        logger.debug(f"CodeAgent: execution gate tool missing — {e}")
    except Exception as e:
        logger.warning(f"CodeAgent: execution gate failed — {e}")
    finally:
        try:
            os.unlink(tmpfile)
        except Exception:
            pass

    return issues


# ── Phase 5: Critique prompt ──────────────────────────────────────────────────

_CRITIQUE_PROMPT = """\
You are a blocking senior code reviewer. Find EVERY defect stopping this PR from merging.

ORIGINAL TASK:
{task}

AUTOMATED TOOL FINDINGS (already detected — include in your reasoning):
{tool_issues}

CODE:
```{language}
{code}
```

Check:
- Recursion in retry logic (must be for-loop, not self-call)
- HTTPError vs HTTPStatusError confusion (.response access)
- Exception order (TimeoutException before HTTPStatusError before HTTPError)
- Missing retry counter / no exponential backoff
- Unused imports, top-level executable code, logging.basicConfig
- Modern user-agents (2024+, Chrome 120+)
- All task requirements present

Respond ONLY in JSON:
{{
  "has_issues": true|false,
  "critical_issues": ["issue with line ref"],
  "score": <1-10>,
  "verdict": "MERGE"|"FIX_REQUIRED",
  "reasoning": "one paragraph"
}}
"""


# ── Phase 6: Fix prompt ───────────────────────────────────────────────────────

_FIX_PROMPT = """\
You are a world-class {language} engineer with chain-of-thought reasoning.
Fix EVERY issue listed. Think through each fix before writing code.

ORIGINAL TASK:
{task}

FULL CRITIQUE (read the reasoning — it explains WHY each issue is wrong):
{full_critique}

ALL ISSUES TO FIX:
{issues}

BROKEN CODE:
```{language}
{code}
```

MANDATORY FIXES:
- Change any recursive retry to a for-loop with attempt counter
- Change .response on HTTPError to HTTPStatusError
- Catch TimeoutException BEFORE HTTPStatusError BEFORE HTTPError
- Remove any unused imports
- Remove logging.basicConfig from module level
- Use proxy= not proxies=

Return the COMPLETE fixed file in a ```{language} block.
After the block: one line per fix — "Fixed: <issue>"
"""


# ── Code extractor ────────────────────────────────────────────────────────────

def _extract_code(text: str) -> tuple[str, str]:
    m = re.search(r"```(\w*)\n?(.*?)```", text, re.DOTALL)
    if m:
        return (m.group(1).strip() or "text"), m.group(2).strip()
    return "text", text.strip()


# ── Main entry ────────────────────────────────────────────────────────────────

def run_code_agent(
    task: str,
    language: str = "python",
    skip_search: bool = False,
) -> dict:
    """
    Full agentic code generation: research → generate → static → execution → critique → fix.

    Args:
        task: Complete description of what to build. Include exact libraries,
              all constraints (async, typed, PR-ready, etc.), quality requirements.
        language: Target programming language (default: python).
        skip_search: Skip web research phase (faster, no doc context).

    Returns:
        dict with status, response (markdown), primary_code, score, iterations.
    """
    language = (language or "python").lower().strip()
    if not task:
        return {"status": "error", "error": "task is required"}

    lang_display = _LANG_DISPLAY.get(language, language.capitalize())
    logger.info(f"CodeAgent v3: task={task[:80]!r}, lang={language}")

    with _PhaseProgress() as bar:

        # ── Phase 1: Research ─────────────────────────────────────────────────
        context = ""
        if not skip_search:
            bar.advance("🔍 Searching docs & best practices…")
            context = _search_docs(task, language)
        else:
            bar.advance("🔍 Skipping doc search (skip_search=True)")

        context_section = context if context else "(No external context — use training knowledge.)"
        pitfalls = _PITFALLS_PYTHON if language == "python" else "(No pitfalls defined.)"
        interface = _pick_interface(task)

        # ── Phase 2: Generate ─────────────────────────────────────────────────
        bar.advance("⚙️  Generating initial implementation (deepseek-r1)…")
        gen_prompt = _GENERATE_PROMPT.format(
            language=language, task=task,
            interface=interface, context=context_section, pitfalls=pitfalls,
        )
        try:
            raw_gen = _call_llm(gen_prompt, model=_HEAVY_MODEL)
        except Exception as e:
            return {"status": "error", "error": f"Generation failed: {e}"}

        _, current_code = _extract_code(raw_gen)
        current_full = raw_gen
        iterations = 0
        final_score = 5
        last_critique_text = ""

        # ── Phase 3 → 6 loop ─────────────────────────────────────────────────
        for iteration in range(MAX_ITERATIONS):
            round_n = iteration + 1

            # Static gate
            bar.advance(f"🔬 Round {round_n}: static analysis…")
            static_issues = _run_static_checks(current_code, language)
            if static_issues:
                logger.info(f"CodeAgent: static caught {len(static_issues)}: {static_issues}")

            # Execution gate (mypy + ruff + py_compile)
            bar.advance(f"🔌 Round {round_n}: execution gate (mypy + ruff)…")
            exec_issues = _run_execution_gate(current_code, language)
            if exec_issues:
                logger.info(f"CodeAgent: exec gate caught {len(exec_issues)}: {exec_issues}")

            all_tool_issues = static_issues + [i for i in exec_issues if i not in static_issues]
            tool_summary = (
                "\n".join(f"  - {i}" for i in all_tool_issues)
                if all_tool_issues else "  None — all deterministic checks passed."
            )

            # LLM critique (fast model)
            bar.advance(f"🧐 Round {round_n}: LLM critique…")
            critique_prompt = _CRITIQUE_PROMPT.format(
                task=task, language=language,
                code=current_code, tool_issues=tool_summary,
            )
            try:
                critique_raw = _call_llm(critique_prompt, model=_FAST_MODEL)
                last_critique_text = critique_raw
            except Exception as e:
                logger.warning(f"CodeAgent: critique failed ({e})")
                break

            # Parse critique JSON
            try:
                json_text = re.sub(r"```(?:json)?|```", "", critique_raw).strip()
                m = re.search(r"\{.*\}", json_text, re.DOTALL)
                critique = json.loads(m.group() if m else json_text)
            except Exception:
                logger.warning("CodeAgent: could not parse critique JSON")
                break

            final_score    = critique.get("score", final_score)
            verdict        = critique.get("verdict", "MERGE")
            critical_issues = critique.get("critical_issues", [])
            all_issues     = all_tool_issues + [i for i in critical_issues if i not in all_tool_issues]

            logger.info(
                f"CodeAgent: round {round_n} — score={final_score}/10, verdict={verdict}, "
                f"tool={len(all_tool_issues)}, llm={len(critical_issues)}"
            )

            if verdict == "MERGE" and not all_tool_issues:
                logger.info("CodeAgent: ✓ approved — exiting loop")
                break

            # Fix
            bar.advance(f"🔧 Round {round_n}: fixing {len(all_issues)} issue(s)…")
            issues_text = "\n".join(f"  {i+1}. {iss}" for i, iss in enumerate(all_issues))
            fix_prompt = _FIX_PROMPT.format(
                language=language, task=task,
                full_critique=last_critique_text,
                issues=issues_text, code=current_code,
            )
            try:
                fixed_raw = _call_llm(fix_prompt, model=_HEAVY_MODEL)
                _, fixed_code = _extract_code(fixed_raw)
                if fixed_code and len(fixed_code) > 80:
                    current_code = fixed_code
                    current_full = fixed_raw
                    iterations += 1
                    logger.info(f"CodeAgent: fix applied — iteration {iterations}")
                else:
                    logger.warning("CodeAgent: fix returned empty code")
                    break
            except Exception as e:
                logger.warning(f"CodeAgent: fix failed ({e})")
                break

        bar.advance("✅ Assembling final output…")

    # ── Assemble output ───────────────────────────────────────────────────────
    # Run final static+exec check to get accurate Static indicator
    final_static  = _run_static_checks(current_code, language)
    final_exec    = _run_execution_gate(current_code, language)
    final_clean   = not final_static and not final_exec

    score_icon = "🟢" if final_score >= 8 else "🟡" if final_score >= 6 else "🔴"
    static_icon = "✓" if final_clean else f"⚠ {len(final_static + final_exec)} issue(s)"

    header = (
        f"**Code Agent v3** | {lang_display} | "
        f"Score: {score_icon} {final_score}/10 | "
        f"Rounds: {iterations + 1}/{MAX_ITERATIONS} | "
        f"Docs: {'✓' if context else '✗'} | "
        f"Gates: {static_icon}\n\n"
    )

    final_response = header + (
        current_full if "```" in current_full
        else f"```{language}\n{current_code}\n```"
    )

    logger.info(
        f"CodeAgent: done — score={final_score}/10, rounds={iterations+1}, "
        f"code_len={len(current_code)}, clean={final_clean}"
    )

    return {
        "status":       "success",
        "operation":    "code_agent",
        "language":     language,
        "response":     final_response,
        "primary_code": current_code,
        "code_blocks":  [{"language": language, "code": current_code}],
        "score":        final_score,
        "iterations":   iterations + 1,
        "docs_searched": bool(context),
        "gates_clean":  final_clean,
    }


METADATA = {
    "name":        "code_agent",
    "description": (
        "Full agentic code pipeline: searches docs, generates with deepseek-r1, "
        "runs static+mypy+ruff execution gate, LLM critiques, and iterates until "
        "the code is production-ready. Shows a per-phase progress bar in the CLI. "
        "Use for ALL real coding tasks."
    ),
    "function":  "run_code_agent",
    "dangerous": False,
    "domain":    "reasoning",
    "output_type": "code",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Full description of what to build. Include: exact libraries, "
                    "all constraints (async, typed, PR-ready, rate-limited, etc.). "
                    "The more detail, the better the output."
                ),
            },
            "language": {
                "type": "string",
                "default": "python",
                "description": "Target programming language.",
            },
            "skip_search": {
                "type": "boolean",
                "default": False,
                "description": "Skip web research (faster, no doc context).",
            },
        },
        "required": ["task"],
    },
}
