"""
Code Assistant Tool
-------------------
LLM-powered coding assistant for generating, explaining, fixing, and reviewing code.
Specialized system prompt for code tasks. Returns structured output with language detection.
"""

import re
from smith.tools.LLM_CALLER import call_llm
from smith.core.logging import get_smith_logger

logger = get_smith_logger("smith.tools.code_assistant")

# ── Language aliases ──────────────────────────────────────────────────────────
LANG_ALIASES = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "rb": "ruby", "sh": "bash", "rs": "rust", "go": "go",
    "cpp": "cpp", "c": "c", "cs": "csharp", "java": "java",
    "html": "html", "css": "css", "sql": "sql", "json": "json",
    "yaml": "yaml", "toml": "toml",
}

def _normalize_lang(language: str) -> str:
    lang = (language or "").lower().strip()
    return LANG_ALIASES.get(lang, lang) or "text"

def _detect_language_from_fence(text: str) -> str:
    """Pull language hint from the first ``` fence."""
    m = re.search(r"```(\w+)", text)
    if m:
        return _normalize_lang(m.group(1))
    return "text"

def _extract_code_blocks(text: str):
    """Return list of (language, code) tuples from markdown fences."""
    blocks = []
    pattern = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        lang = _normalize_lang(m.group(1)) if m.group(1) else "text"
        code = m.group(2).strip()
        if code:
            blocks.append({"language": lang, "code": code})
    return blocks


# ── Operation prompts ─────────────────────────────────────────────────────────

_SYSTEM_BASE = """You are a world-class software engineer producing PRODUCTION-READY code.

MANDATORY RULES — violating any of these is a failure:
1. Follow the user's task description EXACTLY. If they say httpx, use httpx. If they say async, write async. Never substitute.
2. Write COMPLETE, RUNNABLE code. Never write placeholders like "# TODO" or "# add your logic here".
3. Include ALL requested features in a single implementation — do NOT omit for brevity.
4. Always include: type hints, docstrings, proper error handling, and logging where appropriate.
5. Wrap ALL code in a fenced block with the language tag (e.g., ```python).
6. After the code block, write ONE concise paragraph describing key design decisions. No fluff.
7. If a specific library is required, use it. NEVER fall back to a different library."""

_OP_PROMPTS = {
    "generate": (
        "{system}\n\n"
        "TASK: {task}\n"
        "LANGUAGE: {language}\n\n"
        "Produce a complete, production-ready implementation satisfying every requirement in TASK. "
        "No shortcuts. Full implementation only."
    ),
    "explain": (
        "{system}\n\n"
        "Explain this {language} code. Cover: what it does, how it works, key patterns, edge cases, and any gotchas.\n\n"
        "```{language}\n{code}\n```"
    ),
    "fix": (
        "{system}\n\n"
        "Fix ALL bugs in this {language} code. Issue: {task}\n\n"
        "```{language}\n{code}\n```\n\n"
        "Return the FULL corrected file. Then list each bug fixed with a one-line explanation."
    ),
    "review": (
        "{system}\n\n"
        "Do a thorough production code review. Rate and give concrete improvements for:\n"
        "  - Correctness & edge cases\n"
        "  - Type safety & error handling\n"
        "  - Performance bottlenecks\n"
        "  - Security vulnerabilities\n"
        "  - Code style & maintainability\n\n"
        "```{language}\n{code}\n```"
    ),
}


# ── Main entry ────────────────────────────────────────────────────────────────

def run_code_assistant(
    operation: str = "generate",
    task: str = "",
    language: str = "python",
    code: str = "",
    model: str = None,
) -> dict:
    """
    Multi-mode code assistant using the configured LLM.
    """
    operation = (operation or "generate").lower()
    if operation not in _OP_PROMPTS:
        return {"status": "error", "error": f"Unknown operation '{operation}'. Use: generate, explain, fix, review"}

    language = _normalize_lang(language)

    # Validate required fields per operation
    if operation == "generate" and not task:
        return {"status": "error", "error": "Field 'task' is required for generate operation"}
    if operation in ("explain", "review") and not code:
        return {"status": "error", "error": f"Field 'code' is required for {operation} operation"}
    if operation == "fix" and not code:
        return {"status": "error", "error": "Field 'code' is required for fix operation"}

    prompt = _OP_PROMPTS[operation].format(
        system=_SYSTEM_BASE,
        task=task or "",
        language=language,
        code=code or "",
    )

    try:
        from smith.config import config
        target_model = model or config.primary_model
        result = call_llm(prompt, model=target_model)
    except TypeError:
        result = call_llm(prompt)

    if result.get("status") != "success":
        return {"status": "error", "error": result.get("error", "LLM call failed")}

    raw_response = result.get("response", "")
    code_blocks = _extract_code_blocks(raw_response)

    # Detect language from fence if not explicit
    if not code_blocks:
        detected_lang = language
    else:
        detected_lang = code_blocks[0]["language"] if code_blocks else language

    return {
        "status": "success",
        "operation": operation,
        "language": detected_lang,
        "response": raw_response,        # Full markdown response for the renderer
        "code_blocks": code_blocks,      # Parsed blocks for direct use
        "primary_code": code_blocks[0]["code"] if code_blocks else "",
    }


METADATA = {
    "name": "code_assistant",
    "description": (
        "LLM-powered coding assistant. Use operation='generate' to write new code, "
        "'explain' to understand existing code, 'fix' to repair bugs, "
        "'review' to get a code review. Always wraps output in syntax-highlighted blocks."
    ),
    "function": "run_code_assistant",
    "dangerous": False,
    "domain": "reasoning",
    "output_type": "code",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["generate", "explain", "fix", "review"],
                "description": "What to do: generate new code, explain existing code, fix bugs, or do a code review."
            },
            "task": {
                "type": "string",
                "description": "Description of what the code should do (required for generate/fix)."
            },
            "language": {
                "type": "string",
                "default": "python",
                "description": "Programming language (e.g. python, javascript, rust, sql)."
            },
            "code": {
                "type": "string",
                "description": "Existing code (required for explain, fix, review)."
            },
        },
        "required": ["operation"],
    },
}
