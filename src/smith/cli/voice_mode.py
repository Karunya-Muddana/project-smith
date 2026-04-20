"""
Smith Voice Mode
----------------
Full-screen terminal voice interface for the Smith agent runtime.
Activate with /activate-smith from the main REPL.

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │  ⚡ SMITH  ·  VOICE MODE                        [Ctrl+C]   │
  ├──────────────────────────────┬──────────────────────────────┤
  │  STATUS                      │  PIPELINE                    │
  │                              │                              │
  │  ◉ LISTENING                 │  ① google_search   ✓  0.8s  │
  │  ▁▂▅▇█▇▅▂▁▂▄▆█▆▄▂           │  ② llm_caller     ►          │
  │                              │  ③ news_fetcher    ○          │
  ├──────────────────────────────┴──────────────────────────────┤
  │  As of 2025, AI regulation has seen significant movement... │
  └─────────────────────────────────────────────────────────────┘

Voice requires: pip install faster-whisper melo-tts sounddevice soundfile
Falls back to typed input if audio hardware is unavailable.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich import box


logger = logging.getLogger("smith.cli.voice_mode")

_VOICE_HISTORY: List[Dict[str, Any]] = []


# ─────────────────────────────────────────────────────────────────────────────
# Shared State
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VoiceState:
    mode: str = "idle"          # idle | loading | listening | transcribing | planning | executing | speaking | error
    query: str = ""
    response: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    status_msg: str = "Initializing…"
    frame: int = 0
    error: str = ""
    done: bool = False
    text_fallback: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> "VoiceState":
        with self._lock:
            from copy import copy
            s = copy(self)
            s.steps = list(self.steps)
            return s


# ─────────────────────────────────────────────────────────────────────────────
# Animations
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKS = " ▁▂▃▄▅▆▇█"


def _sine_wave(frame: int, width: int = 26) -> str:
    bars = []
    for i in range(width):
        val = (math.sin((i + frame * 0.6) * 0.5) + 1) / 2
        peak = (math.sin((i + frame * 0.4) * 0.8) + 1) / 4 + 0.3
        combined = min(1.0, (val + peak) / 1.5)
        bars.append(_BLOCKS[int(combined * (len(_BLOCKS) - 1))])
    return "".join(bars)


def _pulse_bar(frame: int, width: int = 26) -> str:
    center = width // 2
    t = (frame % 20) / 20.0
    bars = []
    for i in range(width):
        dist = abs(i - center) / center
        val = max(0.0, (1.0 - dist) * math.sin(t * math.pi))
        bars.append(_BLOCKS[int(val * (len(_BLOCKS) - 1))])
    return "".join(bars)


_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _spin(frame: int) -> str:
    return _SPINNER[frame % len(_SPINNER)]


# ─────────────────────────────────────────────────────────────────────────────
# Per-mode config
# ─────────────────────────────────────────────────────────────────────────────

# (badge markup, border colour for status panel)
_MODE_CONFIG = {
    "idle":         ("[bold dim]STANDBY[/bold dim]",              "bright_black"),
    "loading":      ("[bold yellow]LOADING MODEL[/bold yellow]",  "yellow"),
    "listening":    ("[bold green]LISTENING[/bold green]",        "green"),
    "transcribing": ("[bold yellow]PROCESSING AUDIO[/bold yellow]", "yellow"),
    "planning":     ("[bold cyan]PLANNING[/bold cyan]",           "cyan"),
    "executing":    ("[bold blue]EXECUTING[/bold blue]",          "blue"),
    "speaking":     ("[bold magenta]SPEAKING[/bold magenta]",     "magenta"),
    "error":        ("[bold red]ERROR[/bold red]",                "red"),
}

_STEP_ICONS = {
    "pending":  ("○", "dim"),
    "running":  ("►", "cyan"),
    "success":  ("✓", "green"),
    "error":    ("✗", "red"),
    "skipped":  ("–", "dim"),
    "cached":   ("⚡", "yellow"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Render helpers
# NOTE: Never embed Rich markup tags inside Text().  Always use
#       Text.from_markup() or append with explicit style= argument.
# ─────────────────────────────────────────────────────────────────────────────

def _render_header(snap: VoiceState) -> Panel:
    badge, _ = _MODE_CONFIG.get(snap.mode, _MODE_CONFIG["idle"])
    hdr = Text(justify="center")
    hdr.append("  ⚡ SMITH  ·  VOICE MODE   ", style="bold white")
    hdr.append("  ")
    hdr.append_text(Text.from_markup(badge))
    hdr.append("     ", style="")
    hdr.append("[Ctrl+C to exit]", style="dim")
    return Panel(hdr, border_style="bright_black", box=box.HORIZONTALS, padding=(0, 1))


def _render_status(snap: VoiceState) -> Panel:
    _, border = _MODE_CONFIG.get(snap.mode, _MODE_CONFIG["idle"])
    t = Text(justify="center")

    if snap.mode == "idle":
        t.append("\n\n")
        t.append("◌  Standby\n\n", style="dim")
        msg = snap.status_msg or "Say something to begin"
        if snap.text_fallback:
            msg = "Type a query below and press Enter"
        t.append(f"\n{msg}\n", style="dim")

    elif snap.mode == "loading":
        t.append("\n\n")
        t.append(f"  {_spin(snap.frame)} ", style="yellow")
        t.append(f"{snap.status_msg}\n\n", style="yellow")
        t.append("(first run only)\n", style="dim")

    elif snap.mode == "listening":
        t.append("\n")
        t.append("◉  LISTENING\n\n", style="bold green")
        t.append(f"  {_sine_wave(snap.frame)}  \n\n", style="green")
        if snap.text_fallback:
            t.append("text mode\n", style="dim")

    elif snap.mode == "transcribing":
        t.append("\n\n")
        t.append(f"  {_spin(snap.frame)} ", style="yellow")
        t.append("Processing audio…\n\n", style="yellow")

    elif snap.mode == "planning":
        t.append("\n\n")
        t.append(f"  {_spin(snap.frame)} ", style="cyan")
        t.append("Planning steps…\n\n", style="cyan")

    elif snap.mode == "executing":
        total = len(snap.steps)
        done = sum(1 for s in snap.steps if s.get("status") in ("success", "error", "skipped", "cached"))
        pct = (done / total * 100) if total else 0
        bar_width = 22
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        t.append("\n")
        t.append(f"  ▶  {bar}  {pct:.0f}%\n\n", style="blue")
        t.append(f"  Step {done} / {total}\n\n", style="dim")

    elif snap.mode == "speaking":
        t.append("\n")
        t.append("◈  SPEAKING\n\n", style="bold magenta")
        t.append(f"  {_pulse_bar(snap.frame)}  \n\n", style="magenta")

    elif snap.mode == "error":
        t.append("\n\n")
        t.append("  ✗  Error\n\n", style="bold red")
        t.append(f"  {snap.error[:80]}\n", style="red")

    if snap.query:
        t.append("\n")
        t.append("  You:  ", style="dim")
        display = snap.query[:80] + ("…" if len(snap.query) > 80 else "")
        t.append(display, style="italic white")
        t.append("\n")

    return Panel(t, title="[bold]Status[/bold]", border_style=border, box=box.ROUNDED)


def _render_pipeline(snap: VoiceState) -> Panel:
    if not snap.steps:
        t = Text("\n\n  Waiting for plan…\n\n", justify="left", style="dim")
        return Panel(t, title="[bold]Pipeline[/bold]", border_style="bright_black", box=box.ROUNDED)

    t = Text()
    t.append("\n")
    for i, step in enumerate(snap.steps):
        status = step.get("status", "pending")
        tool   = step.get("tool", "unknown")
        dur    = step.get("duration")
        icon, color = _STEP_ICONS.get(status, ("○", "dim"))

        t.append(f"  {i + 1:>2}  ", style="dim")
        t.append(f"{icon}  ", style=f"bold {color}")
        t.append(tool, style=color if status in ("running", "success", "cached") else "dim")

        if status == "running":
            t.append(f"  {_spin(snap.frame + i * 3)}", style="cyan")
        elif status in ("success", "cached") and dur is not None:
            t.append(f"  {dur:.1f}s", style="dim")
        elif status == "error":
            err = step.get("error", "")[:30]
            t.append(f"  {err}", style="red")
        t.append("\n")

    t.append("\n")
    total = len(snap.steps)
    done  = sum(1 for s in snap.steps if s.get("status") in ("success", "error", "skipped", "cached"))
    if done == total and total > 0:
        t.append(f"  All {total} steps complete\n", style="dim")

    return Panel(t, title="[bold]Pipeline[/bold]", border_style="blue", box=box.ROUNDED)


def _render_response(snap: VoiceState) -> Panel:
    if not snap.response:
        t = Text("  Response will appear here…", justify="left", style="dim")
        return Panel(t, title="[bold]Response[/bold]", border_style="bright_black", box=box.ROUNDED)

    body = snap.response[:600] + ("…" if len(snap.response) > 600 else "")
    return Panel(
        Text(f"  {body}", overflow="fold"),
        title="[bold]Response[/bold]",
        border_style="bright_black",
        box=box.ROUNDED,
    )


def _build_layout(snap: VoiceState) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header",   size=3),
        Layout(name="body"),
        Layout(name="response", size=6),
    )
    root["body"].split_row(
        Layout(name="status",   ratio=3),
        Layout(name="pipeline", ratio=2),
    )
    root["header"].update(_render_header(snap))
    root["status"].update(_render_status(snap))
    root["pipeline"].update(_render_pipeline(snap))
    root["response"].update(_render_response(snap))
    return root


# ─────────────────────────────────────────────────────────────────────────────
# Voice I/O
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_user_name() -> str:
    configured = os.getenv("SMITH_USER_NAME", "").strip()
    if configured:
        return configured

    fallback = os.getenv("USERNAME", "").strip() or os.getenv("USER", "").strip()
    return fallback if fallback else "there"


_USER_NAME = _resolve_user_name()


def _startup_greeting() -> tuple[str, str]:
    """
    Return (spoken_text, status_text) for the startup greeting.
    Uses memory statistics when available to make the greeting feel contextual.
    """
    default_spoken = f"Hey {_USER_NAME}, Smith is online and ready. What should we tackle first?"
    default_status = f"Welcome back, {_USER_NAME}."

    try:
        from smith.config import config as _cfg
        if not _cfg.memory_enabled:
            return default_spoken, default_status

        from smith.memory import get_memory_manager

        mem = get_memory_manager()
        stats = mem.stats()
        records = int(stats.get("records", 0) or 0)
        if records <= 0:
            return default_spoken, default_status

        recent = mem.get_recent(1)
        if not recent:
            return (
                f"Welcome back, {_USER_NAME}. Memory is loaded from {records} past chats."
                " Ready when you are.",
                f"Welcome back, {_USER_NAME}. Memory ready.",
            )

        first_line = (recent[0].text or "").splitlines()[0].strip()
        topic = first_line.replace("User:", "").strip()[:70]
        if topic:
            spoken = (
                f"Welcome back, {_USER_NAME}. Last time we talked about {topic}."
                " Want to continue from there?"
            )
            status = f"Welcome back, {_USER_NAME}. Context recovered."
            return spoken, status

        return (
            f"Welcome back, {_USER_NAME}. I have memory from {records} past chats and I am ready.",
            f"Welcome back, {_USER_NAME}. Memory ready.",
        )
    except Exception as e:
        logger.debug("Voice startup personalization skipped: %s", e)
        return default_spoken, default_status


def _persist_interaction_to_memory(query: str, response: str) -> None:
    """Best-effort persistence so voice mode contributes to long-term memory."""
    if not query or not response:
        return

    try:
        from smith.config import config as _cfg
        if not _cfg.memory_enabled:
            return

        from smith.memory import get_memory_manager

        mem = get_memory_manager()
        mem.write_interaction(query, response)
        mem.maybe_summarize()
    except Exception as e:
        logger.debug("Voice memory persistence skipped: %s", e)


def _record_voice_turn(user: str, assistant: str) -> None:
    _VOICE_HISTORY.append(
        {
            "timestamp": datetime.now().isoformat(),
            "user": user,
            "assistant": assistant,
        }
    )
    # Keep only the most recent turns for short-term context.
    if len(_VOICE_HISTORY) > 8:
        del _VOICE_HISTORY[:-8]


def _build_voice_recent_context(max_turns: int = 3, max_chars: int = 1200) -> str:
    if not _VOICE_HISTORY:
        return ""

    lines: List[str] = []
    total = 0
    for item in _VOICE_HISTORY[-max_turns:]:
        line = (
            f"[recent]\nUser: {(item.get('user') or '').strip()}\n"
            f"Smith: {(item.get('assistant') or '').strip()}"
        )
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    return "\n\n".join(lines)


def _try_import_voice():
    try:
        from smith.core.agent_voice_module import AgentVoiceRecognitionModule, AgentTTSModule
        return AgentVoiceRecognitionModule(), AgentTTSModule()
    except Exception:
        return None, None


def _listen_once(stt, state: VoiceState) -> str:
    """Record using VAD — stops when user goes quiet, up to 15 s."""
    state.update(mode="listening", status_msg="Listening…")
    try:
        audio = stt.listen_vad(max_duration=15.0, post_speech_silence=1.4)
    except Exception as e:
        state.update(mode="error", error=f"Mic error: {e}")
        time.sleep(2)
        return ""
    if audio is None or len(audio) == 0:
        return ""
    state.update(mode="transcribing", status_msg="Transcribing…")
    text = stt.transcribe(audio)
    return text.strip()


def _speak(tts, text: str, state: VoiceState):
    """Speak text via TTS, showing errors in the UI instead of swallowing them."""
    if not text:
        return
    if tts is None:
        state.update(status_msg="TTS unavailable — response shown as text")
        return
    state.update(mode="speaking")
    try:
        tts.speak(text[:1000])
    except Exception as e:
        state.update(mode="idle", status_msg=f"TTS error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Query dispatch  (router → direct LLM  OR  full planner pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def _run_query(query: str, state: VoiceState):
    """
    Route the query:
      - "direct"  → single LLM call with a conversational voice prompt
      - "planner" → full orchestrator pipeline, then convert output to speech
    state.response always ends up as clean natural spoken text.
    """
    from smith.core.query_router import classify, direct_answer, to_speech_text

    state.update(query=query, steps=[], response="")
    route = classify(query)
    recent_context = _build_voice_recent_context()
    routed_query = query
    if recent_context:
        routed_query = (
            "[Recent conversation context]\n"
            f"{recent_context}\n"
            "[End recent conversation context]\n\n"
            f"Current user query: {query}"
        )

    # ── Direct path ───────────────────────────────────────────────────────────
    if route == "direct":
        state.update(mode="planning", status_msg="Thinking…")
        answer = direct_answer(routed_query, voice_mode=True, user_name=_USER_NAME)
        if not answer:
            state.update(mode="error", error="No response from LLM")
            time.sleep(2)
            return
        state.update(response=answer)
        _record_voice_turn(query, answer)
        return

    # ── Planner path ──────────────────────────────────────────────────────────
    from smith.core.orchestrator import smith_orchestrator

    state.update(mode="planning", status_msg="Planning steps…")
    raw_response = ""

    try:
        for event in smith_orchestrator(
            query,
            require_approval=False,
            recent_context=recent_context,
        ):
            etype = event.get("type")

            if etype == "status":
                state.update(status_msg=event.get("message", ""))

            elif etype == "plan_created":
                plan  = event.get("plan", {})
                nodes = plan.get("nodes") or plan.get("steps") or []
                state.update(
                    mode="executing",
                    steps=[{"tool": n.get("tool", "?"), "status": "pending"} for n in nodes],
                )

            elif etype == "step_start":
                idx = event.get("step_index", 0)
                with state._lock:
                    if idx < len(state.steps):
                        state.steps[idx]["status"] = "running"

            elif etype == "step_complete":
                idx      = event.get("step_index", 0)
                status   = event.get("status", "success")
                duration = event.get("duration", 0)
                final_st = "cached" if event.get("cache_hit") else status
                with state._lock:
                    if idx < len(state.steps):
                        state.steps[idx]["status"]   = final_st
                        state.steps[idx]["duration"] = duration
                        if status == "error":
                            r = event.get("payload", {})
                            state.steps[idx]["error"] = (r.get("error", "") if isinstance(r, dict) else "")[:40]

            elif etype == "final_answer":
                payload = event.get("payload", {})
                raw_response = (
                    payload.get("response", str(payload))
                    if isinstance(payload, dict) else str(payload)
                )

            elif etype == "error":
                state.update(mode="error", error=event.get("message", "Unknown error"))
                time.sleep(2)
                return

    except Exception as e:
        state.update(mode="error", error=str(e))
        time.sleep(2)
        return

    # Always convert → natural speech (handles JSON, markdown, REDACTED tokens)
    if raw_response:
        state.update(mode="planning", status_msg="Converting to speech…")
        spoken = to_speech_text(raw_response, user_name=_USER_NAME)
        state.update(response=spoken or raw_response)
        _record_voice_turn(query, spoken or raw_response)


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────────────────────

def _voice_worker(state: VoiceState):
    # ── 1. Import voice modules ───────────────────────────────────────────────
    stt, tts = _try_import_voice()
    if stt is None:
        state.update(text_fallback=True)

    # ── 2. Pre-warm STT + TTS models so first use is instant ─────────────────
    if stt is not None:
        state.update(mode="loading", status_msg="Loading speech recognition model…")
        try:
            from smith.core.agent_voice_module import _get_stt
            _get_stt()
        except Exception as e:
            state.update(status_msg=f"STT load failed: {e}")
            stt = None
            state.update(text_fallback=True)

    if tts is not None:
        state.update(mode="loading", status_msg="Loading text-to-speech model…")
        try:
            from smith.core.agent_voice_module import _get_tts
            _get_tts()
        except Exception as e:
            state.update(status_msg=f"TTS load failed — responses will be text only")
            tts = None

    time.sleep(0.4)

    # ── 3. Greet the user ─────────────────────────────────────────────────────
    greeting, greeting_status = _startup_greeting()
    state.update(mode="idle", status_msg=greeting_status)
    _speak(tts, greeting, state)
    time.sleep(0.3)

    ready_msg = "Say something to begin" if not state.text_fallback else "Type a query below and press Enter"
    state.update(mode="idle", status_msg=ready_msg)

    # ── 4. Main loop ──────────────────────────────────────────────────────────
    while not state.done:
        if state.text_fallback:
            state.update(mode="listening")
            query_holder: Dict[str, str] = {"q": ""}

            def _read():
                import sys
                sys.stderr.write(f"\n  {_USER_NAME}: ")
                sys.stderr.flush()
                try:
                    query_holder["q"] = sys.stdin.readline().strip()
                except Exception:
                    pass

            t = threading.Thread(target=_read, daemon=True)
            t.start()
            while t.is_alive() and not state.done:
                time.sleep(0.08)
            t.join(timeout=0.1)
            query = query_holder["q"]
        else:
            query = _listen_once(stt, state)   # VAD — no fixed duration

        if state.done:
            break

        if not query:
            state.update(mode="idle", status_msg="Nothing heard — ready")
            time.sleep(0.5)
            continue

        _run_query(query, state)

        if state.response:
            _persist_interaction_to_memory(query, state.response)

        if state.done:
            break

        _speak(tts, state.response, state)
        state.update(mode="idle", status_msg="Ready — listening…")
        time.sleep(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def activate_voice_mode(console: Optional[Console] = None):
    """
    Launch the full-screen voice mode UI.
    Blocks until the user presses Ctrl+C.
    Called from the main REPL on /activate-smith.
    """
    state = VoiceState()

    worker = threading.Thread(target=_voice_worker, args=(state,), daemon=True)
    worker.start()

    try:
        with Live(
            _build_layout(state.snapshot()),
            refresh_per_second=12,
            screen=True,
            transient=False,
        ) as live:
            while not state.done:
                state.update(frame=state.frame + 1)
                live.update(_build_layout(state.snapshot()))
                time.sleep(1 / 12)

    except KeyboardInterrupt:
        pass
    finally:
        state.update(done=True)
        worker.join(timeout=2)

    if console:
        console.print("\n[dim]Voice mode deactivated.[/dim]\n")
    else:
        print("\nVoice mode deactivated.\n")
