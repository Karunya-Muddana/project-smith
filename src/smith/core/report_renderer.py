"""
Report Renderer
---------------
Parses the structured JSON output from the synthesizer and renders it as a
rich CLI report. Falls back to plain Markdown if the LLM returns free-form text.

Expected JSON schema from LLM:
{
  "summary":       "One-paragraph executive summary",
  "key_findings":  ["Finding 1", "Finding 2", ...],
  "caveats":       ["Caveat / limitation 1", ...],   // optional
  "sources":       ["Source name / URL", ...]         // optional
}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.report_renderer")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE
)
_JSON_BARE_RE = re.compile(r"\{[\s\S]*\}", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)

# Language display names for panel titles
_LANG_DISPLAY = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "rust": "Rust", "go": "Go", "java": "Java", "cpp": "C++", "c": "C",
    "csharp": "C#", "bash": "Shell", "sh": "Shell", "sql": "SQL",
    "html": "HTML", "css": "CSS", "json": "JSON", "yaml": "YAML",
    "toml": "TOML", "ruby": "Ruby", "text": "Code",
}


def render_code_blocks(text: str, console) -> str:
    """
    Find all ``` fenced code blocks in `text`, render each one as a
    Rich Syntax panel (syntax-highlighted, line-numbered), then return
    the text with fence markers stripped for the plain-text copy.

    If `console` is None (no Rich), just strips fences and returns plain text.
    """
    if not text:
        return text

    try:
        from rich.syntax import Syntax
        from rich.panel import Panel
        from rich import box
        has_rich = True
    except ImportError:
        has_rich = False

    blocks = _CODE_FENCE_RE.findall(text)  # list of (lang, code) tuples
    if not blocks:
        return text  # nothing to render

    plain_output_parts = []
    last_end = 0

    for m in _CODE_FENCE_RE.finditer(text):
        # Prose before this block
        prose = text[last_end:m.start()].strip()
        if prose:
            plain_output_parts.append(prose)
            if console and has_rich:
                from rich.markdown import Markdown
                console.print(Markdown(prose))

        lang = (m.group(1) or "text").lower()
        code = m.group(2).strip()
        display_lang = _LANG_DISPLAY.get(lang, lang.capitalize() or "Code")

        plain_output_parts.append(f"```{lang}\n{code}\n```")

        if console and has_rich:
            try:
                syntax = Syntax(
                    code,
                    lexer=lang or "text",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                )
                console.print(
                    Panel(
                        syntax,
                        title=f"[bold green]󰌠 {display_lang}[/bold green]",
                        border_style="green",
                        padding=(0, 1),
                        box=box.ROUNDED,
                    )
                )
            except Exception:
                # Fallback: print raw if Syntax fails (unknown lexer)
                console.print(f"[dim]```{lang}[/dim]")
                console.print(code)
                console.print("[dim]```[/dim]")

        last_end = m.end()

    # Trailing prose after last block
    tail = text[last_end:].strip()
    if tail:
        plain_output_parts.append(tail)
        if console and has_rich:
            from rich.markdown import Markdown
            console.print(Markdown(tail))

    return "\n\n".join(plain_output_parts)




def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to extract and parse a JSON object from the response text.
    Handles:
      1. Fenced code block: ```json { ... } ```
      2. Bare JSON object anywhere in text
      3. Raw JSON string
    """
    # 1. Try fenced block
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try bare JSON object
    m = _JSON_BARE_RE.search(text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # 3. Try raw text
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    return None


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_report(raw_response: str, console=None) -> str:
    """
    Parse the LLM synthesis response and render a Rich-formatted report.

    Args:
        raw_response: Raw string from LLM (JSON or plain text).
        console: Rich Console instance. If None, just returns plain text.

    Returns:
        Plain-text version of the report (used for session history / export).
    """
    _has_rich = True
    try:
        from rich import box as _box  # lightweight probe; box is always needed below
        del _box
    except ImportError:
        _has_rich = False

    structured = _try_parse_json(raw_response)

    if structured and isinstance(structured, dict) and "summary" in structured:
        return _render_structured(structured, console, _has_rich)
    else:
        return _render_fallback(raw_response, console, _has_rich)


def _render_structured(data: Dict[str, Any], console, has_rich: bool) -> str:
    """Render a structured JSON report using Rich panels."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.markdown import Markdown
    from rich import box

    summary  = data.get("summary", "")
    body     = data.get("body") or data.get("content") or data.get("report") or ""
    findings = data.get("key_findings", [])
    caveats  = data.get("caveats", [])
    sources  = data.get("sources", [])

    plain_parts: List[str] = []

    if console and has_rich:
        console.print()

        # ── Full body / long-form content ─────────────────────────────────
        # If the LLM returned a rich body field, render it fully first
        if body and len(body) > 200:
            plain_parts.append(body)
            if _CODE_FENCE_RE.search(body):
                render_code_blocks(body, console)
            else:
                console.print(Markdown(body))
            console.print()

        # ── Summary panel ─────────────────────────────────────────────────
        # Only show summary panel when there's no long-form body
        if summary and not body:
            plain_parts += ["## Summary", summary, ""]
            console.print(
                Panel(
                    Markdown(summary),
                    title="[bold white]Summary[/bold white]",
                    border_style="bright_black",
                    padding=(1, 2),
                )
            )
        elif summary and body:
            # Show summary as a compact footer note, not a full panel
            plain_parts += ["", "---", f"**TL;DR:** {summary}", ""]
            console.print(f"\n[dim]TL;DR: {summary[:200]}{'...' if len(summary)>200 else ''}[/dim]\n")

        # ── Key Findings ──────────────────────────────────────────────────
        if findings:
            plain_parts += ["## Key Findings", ""]
            plain_parts += [f"  {i}. {f}" for i, f in enumerate(findings, 1)]
            plain_parts.append("")
            findings_text = Text()
            for i, finding in enumerate(findings, 1):
                findings_text.append(f"  {i}. ", style="bold cyan")
                findings_text.append(f"{finding}\n")
            console.print(
                Panel(
                    findings_text,
                    title="[bold white]Key Findings[/bold white]",
                    border_style="bright_black",
                    padding=(0, 2),
                )
            )

        # ── Caveats ───────────────────────────────────────────────────────
        if caveats:
            plain_parts += ["## Caveats", ""]
            plain_parts += [f"  ⚠ {c}" for c in caveats]
            plain_parts.append("")
            caveats_text = Text()
            for caveat in caveats:
                caveats_text.append("  ⚠  ", style="bold yellow")
                caveats_text.append(f"{caveat}\n")
            console.print(
                Panel(
                    caveats_text,
                    title="[bold yellow]⚠  Warnings[/bold yellow]",
                    border_style="yellow",
                    padding=(0, 2),
                )
            )

        # ── Sources ───────────────────────────────────────────────────────
        if sources:
            plain_parts += ["## Sources", ""]
            plain_parts += [f"  [{i}] {s}" for i, s in enumerate(sources, 1)]
            plain_parts.append("")
            src_table = Table(
                show_header=True,
                header_style="bold magenta",
                box=box.SIMPLE,
                padding=(0, 1),
            )
            src_table.add_column("#", style="dim", width=4)
            src_table.add_column("Source", style="white")
            for i, src in enumerate(sources, 1):
                src_table.add_row(str(i), src)
            console.print(
                Panel(
                    src_table,
                    title="[bold white]Sources[/bold white]",
                    border_style="bright_black",
                    padding=(0, 1),
                )
            )

    return "\n".join(plain_parts)





def _render_fallback(text: str, console, has_rich: bool) -> str:
    """
    Fall back to rendered output when JSON parse fails.
    - If the text contains code fences (``` ... ```) → render each block
      as a syntax-highlighted panel via render_code_blocks().
    - Otherwise → wrap in a plain Markdown panel.
    """
    logger.debug("ReportRenderer: falling back to Markdown/code rendering")

    if console and has_rich:
        console.print()

        # Check if there are any code fences
        if _CODE_FENCE_RE.search(text):
            # render_code_blocks handles everything: prose + highlighted blocks
            return render_code_blocks(text, console)
        else:
            from rich.panel import Panel
            from rich.markdown import Markdown
            console.print(
                Panel(
                    Markdown(text),
                    title="[bold white]Response[/bold white]",
                    border_style="bright_black",
                    padding=(1, 2),
                )
            )

    return text

