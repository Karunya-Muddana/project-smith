"""
Synthesis Engine — Critic + RAG Loop
---------------------------------------
Replaces the one-shot final synthesis in orchestrator.py with a
multi-phase pipeline:

  1. Format detection (summary / full_paper / default)
  2. Draft synthesis from condensed trace context
  3. Critic pass → identifies missing/weak sections (JSON)
  4. RAG retrieval from run_context file for each gap
  5. Final synthesis with gap-fills injected
  6. Fabrication guard + report rendering

The critic loop is short-circuited if:
  - Format is "summary" (no depth needed)
  - Draft is already complete per critic
  - Max iterations reached (default: 1 round of critique)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from smith.core.format_detector import detect_format, format_instructions, FormatType
from smith.core.run_context import RunContextManager
from smith.core.report_renderer import render_report
from smith.core.template_engine import resolve_llm_prompt
from smith.core.synthesis_router import select_synthesis_model
import smith.tools.LLM_CALLER as LLM_CALLER

logger = logging.getLogger("smith.synthesis_engine")

# Maximum critic iterations (1 = one draft + one fix pass)
MAX_CRITIC_ITERATIONS = 1

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_serialize(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _extract_response_text(result: Any) -> str:
    """Pull the human-readable text from a step result dict."""
    if isinstance(result, dict):
        for key in ("response", "content", "summary", "text"):
            val = result.get(key)
            if val and isinstance(val, str) and len(val) > 20:
                return val
        return _safe_serialize(result)
    return str(result) if result else ""


def _build_context_from_trace(
    trace: List[Optional[Dict[str, Any]]],
    nodes: List[Dict[str, Any]],
    format_type: FormatType,
    run_ctx: RunContextManager,
) -> str:
    """
    Build the synthesis context string.
    - For full_paper: use run_ctx.retrieve_all_text() which has all step texts
    - For summary/default: use condensed trace (template_engine style)
    """
    if format_type == "full_paper":
        # Use the accumulated run context file — richer and uncondensed
        all_text = run_ctx.retrieve_all_text(max_chars=24_000)
        if all_text.strip():
            return f"ACCUMULATED STEP OUTPUTS:\n{all_text}"

    # Fallback / summary mode: build labeled blocks from trace
    parts = []
    for i, entry in enumerate(trace):
        if entry is None:
            continue
        node = nodes[i] if i < len(nodes) else {}
        tool = entry.get("tool", node.get("tool", "unknown"))
        thought = node.get("thought", "Executing tool...")
        result = entry.get("result")
        status = entry.get("status", "unknown")

        if status not in ("success",):
            parts.append(f"[Step {i} — {tool}: UNAVAILABLE ({status})]")
            continue

        text = _extract_response_text(result)
        # Truncate large results to fit context
        if len(text) > 3000:
            text = text[:2400] + f"\n[... {len(text) - 2400} chars omitted ...]"

        parts.append(f"[Step {i} — {tool}: {thought[:80]}]\n{text}")

    return "\n\n".join(parts)


def _run_critic(
    draft: str,
    user_msg: str,
    format_type: FormatType,
    model: str,
) -> Tuple[bool, List[str]]:
    """
    Ask an LLM critic to evaluate the draft and identify missing sections.

    Returns:
        (is_complete: bool, missing_sections: List[str])
    """
    if format_type == "summary":
        # Summary format doesn't need a critic — it's intentionally brief
        return True, []

    critic_prompt = (
        f"You are a rigorous critic reviewing a draft response.\n\n"
        f"ORIGINAL USER REQUEST:\n{user_msg[:1000]}\n\n"
        f"DRAFT RESPONSE:\n{draft[:4000]}\n\n"
        f"TASK: Evaluate whether the draft fully addresses the user request.\n"
        f"Identify any sections that are:\n"
        f"  - Missing entirely\n"
        f"  - Mentioned but not explained\n"
        f"  - Superficial or vague (< 2 sentences)\n\n"
        f"Return ONLY a JSON object — no prose:\n"
        f'{{"is_complete": true/false, '
        f'"missing_sections": ["<section name or topic>", ...], '
        f'"verdict": "<one sentence assessment>"}}\n'
        f"If the draft is complete, return is_complete=true and missing_sections=[]."
    )

    result = LLM_CALLER.call_llm(critic_prompt, model=model)
    if result.get("status") != "success":
        logger.warning("Critic call failed — treating as complete")
        return True, []

    response = result.get("response", "")
    # Try to parse JSON from response
    try:
        m = re.search(r"\{[\s\S]*\}", response)
        if m:
            data = json.loads(m.group())
            is_complete = bool(data.get("is_complete", True))
            missing = data.get("missing_sections", [])
            verdict = data.get("verdict", "")
            logger.info(f"Critic verdict: {verdict} | Missing: {missing}")
            return is_complete, missing
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning("Critic returned non-JSON — treating draft as complete")
    return True, []


def _rag_fill_gaps(
    missing_sections: List[str],
    run_ctx: RunContextManager,
    top_k: int = 2,
) -> str:
    """
    Retrieve relevant step context for each missing section via BM25.
    Returns a formatted string of retrieved context to append to the synthesis prompt.
    """
    if not missing_sections:
        return ""

    gap_texts = []
    for section in missing_sections[:5]:  # Cap at 5 gaps
        hits = run_ctx.retrieve(section, top_k=top_k)
        if hits:
            gap_texts.append(
                f"RETRIEVED CONTEXT FOR '{section}':\n" + "\n---\n".join(hits)
            )
        else:
            gap_texts.append(
                f"NOTE: No retrieved context available for '{section}' — "
                f"use your training knowledge."
            )

    return "\n\n".join(gap_texts)
def _strip_template_placeholders(text: str) -> str:
    """Remove any raw {{STEPS.N...}} template placeholders that the LLM echoed back."""
    # Remove {{STEPS.N.path}}, {{STEPS.N}}, {{STEPS.N | default: "..."}}, etc.
    cleaned = re.sub(r"\{\{\s*STEPS\.\d+[^}]*\}\}", "", text)
    # Clean up any double-newlines or trailing whitespace left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_fallback_response(
    trace: List[Optional[Dict[str, Any]]],
    nodes: List[Dict[str, Any]],
    user_msg: str,
) -> str:
    """
    Build a usable response directly from trace data when the LLM synthesis fails.
    Concatenates successful step results into a structured answer.
    """
    parts = [f"**Research Results for:** {user_msg}\n"]

    for i, entry in enumerate(trace):
        if entry is None:
            continue
        if entry.get("status") != "success":
            continue

        tool = entry.get("tool", "unknown")
        result = entry.get("result", {})
        text = _extract_response_text(result)

        if not text or len(text.strip()) < 20:
            continue

        # Truncate very long results
        if len(text) > 4000:
            text = text[:4000] + "\n\n[... truncated ...]"

        node = nodes[i] if i < len(nodes) else {}
        thought = node.get("thought", "")
        header = f"### Step {i + 1}: {tool}"
        if thought:
            header += f" — {thought[:80]}"

        parts.append(f"{header}\n\n{text}")

    if len(parts) <= 1:
        return "No results were generated. Please try rephrasing your query."

    return "\n\n---\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main synthesis entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_synthesis(
    user_msg: str,
    trace: List[Optional[Dict[str, Any]]],
    nodes: List[Dict[str, Any]],
    run_ctx: RunContextManager,
    failure_ctx: str = "",
    unavailable_ctx: str = "",
    console: Any = None,
) -> Dict[str, Any]:
    """
    Run the full critic+RAG synthesis pipeline.

    Returns the final LLM result dict (same shape as LLM_CALLER.call_llm output).
    """
    # 1. Detect output format from user message
    format_type = detect_format(user_msg)
    fmt_instructions = format_instructions(format_type)
    logger.info(f"SynthesisEngine: format_type={format_type}")

    # 2. Select model
    model = select_synthesis_model(trace, nodes, user_msg)

    # 3. Build context from accumulated run file + trace
    context = _build_context_from_trace(trace, nodes, format_type, run_ctx)

    # 4. Draft synthesis
    draft_prompt = (
        f"User Request: {user_msg}\n\n"
        f"--- RESEARCH CONTEXT ---\n{context}\n"
        f"{failure_ctx}\n{unavailable_ctx}\n"
        f"--- INSTRUCTIONS ---\n"
        f"Answer the user's request using the research context above.\n"
        f"Draw on the context from all steps — it contains the research each step produced.\n"
        f"Do NOT say 'the trace is incomplete' — use whatever is available.\n"
        f"If context is missing for a section, use your training knowledge.\n"
        f"IMPORTANT: Do NOT output any template placeholders like {{{{STEPS.N}}}} — "
        f"use the actual data from the research context above.\n\n"
        f"{fmt_instructions}"
    )

    draft_result = LLM_CALLER.call_llm(draft_prompt, model=model)
    if draft_result.get("status") != "success":
        logger.warning("Draft synthesis failed — using fallback response")
        fallback = _build_fallback_response(trace, nodes, user_msg)
        return {"status": "success", "response": fallback, "model": "fallback"}

    draft_text = draft_result.get("response", "")
    # Strip any template placeholders the model echoed
    draft_text = _strip_template_placeholders(draft_text)

    # If after stripping the response is empty/too short, build from trace directly
    if len(draft_text.strip()) < 50:
        logger.warning(
            f"Synthesis produced empty/placeholder-only output "
            f"({len(draft_text)} chars after strip) — using fallback"
        )
        fallback = _build_fallback_response(trace, nodes, user_msg)
        return {"status": "success", "response": fallback, "model": "fallback"}

    draft_result["response"] = draft_text

    # 5. Skip critic loop for simple tasks
    # Critic adds 2+ extra LLM calls — only worth it for complex research queries
    skip_critic = (
        format_type == "summary"
        or len(user_msg) < 150       # Short queries don't need critique
        or len(draft_text) < 200     # Very short drafts are already fine
        or len(nodes) <= 3           # Simple plans (e.g. llm_caller + gmail) don't need critique
    )

    if not skip_critic:
        for iteration in range(MAX_CRITIC_ITERATIONS):
            is_complete, missing_sections = _run_critic(
                draft_text, user_msg, format_type, model
            )

            if is_complete or not missing_sections:
                logger.info(
                    f"SynthesisEngine: critic satisfied after {iteration} iteration(s)"
                )
                break

            logger.info(
                f"SynthesisEngine: critic found {len(missing_sections)} gaps — "
                f"running RAG retrieval: {missing_sections}"
            )

            # 6. RAG retrieve for missing sections
            gap_context = _rag_fill_gaps(missing_sections, run_ctx)

            # 7. Fix synthesis with gap-fills
            fix_prompt = (
                f"User Request: {user_msg}\n\n"
                f"ORIGINAL DRAFT:\n{draft_text}\n\n"
                f"CRITIC FEEDBACK — MISSING SECTIONS: {missing_sections}\n\n"
                f"RETRIEVED CONTEXT TO FILL GAPS:\n{gap_context}\n\n"
                f"TASK: Produce an improved, complete version of the draft.\n"
                f"Fill in every missing section using the retrieved context above.\n"
                f"Preserve everything good from the original draft.\n"
                f"IMPORTANT: Do NOT output any template placeholders like {{{{STEPS.N}}}} — "
                f"use the actual data provided.\n\n"
                f"{fmt_instructions}"
            )

            fix_result = LLM_CALLER.call_llm(fix_prompt, model=model)
            if fix_result.get("status") == "success":
                draft_result = fix_result
                draft_text = fix_result.get("response", draft_text)
                # Strip any template placeholders from the fix as well
                draft_text = _strip_template_placeholders(draft_text)
                draft_result["response"] = draft_text
            else:
                logger.warning("Fix iteration failed — keeping previous draft")
                break

    return draft_result

