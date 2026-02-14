"""
LLM CALLER — Groq Edition
--------------------------
Uses Groq API for fast LLM inference.
Supports Llama and Mixtral models with automatic fallback.
"""

import os
import time
import logging
import threading
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] llm_caller: %(message)s"
)
logger = logging.getLogger("llm_caller")

load_dotenv()

# ------------------------------
# Configuration
# ------------------------------

API_KEY = os.getenv("GROQ_API_KEY")

VALID_MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "llama3-8b-8192",
]

PRIMARY_MODEL = VALID_MODELS[0]

client = None
init_error = None

# Global rate limiter — ensures minimum delay between ALL LLM calls
# This is shared across all orchestrator instances (parent + sub-agents)
_global_lock = threading.Lock()
_last_call_time = 0.0
_MIN_CALL_INTERVAL = 3.0  # seconds between API calls (strict: 1 call per 3s)


def _global_rate_limit():
    """Enforce global rate limiting across all threads/orchestrators."""
    global _last_call_time
    with _global_lock:
        now = time.time()
        elapsed = now - _last_call_time
        if elapsed < _MIN_CALL_INTERVAL:
            sleep_time = _MIN_CALL_INTERVAL - elapsed
            time.sleep(sleep_time)
        _last_call_time = time.time()

try:
    from groq import Groq

    if API_KEY:
        client = Groq(api_key=API_KEY)
    else:
        init_error = "Missing GROQ_API_KEY environment variable."
except ImportError:
    init_error = "Module 'groq' not found. Install with `pip install groq`."
except Exception as e:
    init_error = str(e)

# ------------------------------
# Helper Functions
# ------------------------------


def extract_text(response) -> str:
    """Extract text from Groq response."""
    try:
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content
        return "[EMPTY RESPONSE]"
    except Exception as e:
        return f"[PARSE ERROR] {str(e)}"


def safe_generate(prompt: str, model: str, max_retries: int = 3, base_delay: int = 2):
    """Call Groq API with retry logic."""
    if not client:
        raise RuntimeError(f"Client not initialized: {init_error}")

    current_model = model

    for attempt in range(max_retries + 1):
        try:
            # Global rate limit — prevents 429 across all orchestrators
            _global_rate_limit()

            response = client.chat.completions.create(
                model=current_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=8192,
                top_p=0.95,
            )
            return response

        except Exception as e:
            msg = str(e).lower()

            # Handle rate limiting
            if "429" in msg or "rate_limit" in msg or "quota" in msg:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Rate limit hit ({current_model}). Retrying in {delay}s..."
                )
                time.sleep(delay)
                continue

            # Handle invalid model - try fallback
            if "404" in msg or "not found" in msg or "invalid" in msg:
                if current_model in VALID_MODELS:
                    try:
                        current_idx = VALID_MODELS.index(current_model)
                        if current_idx + 1 < len(VALID_MODELS):
                            fallback = VALID_MODELS[current_idx + 1]
                            logger.warning(
                                f"Model '{current_model}' unavailable. Switching to: {fallback}"
                            )
                            current_model = fallback
                            continue
                    except ValueError:
                        pass

            # Re-raise on final attempt or non-retryable errors
            if attempt == max_retries:
                raise e

            # Generic retry with backoff
            delay = base_delay * (2**attempt)
            logger.warning(f"Error: {e}. Retrying in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(f"LLM failed after {max_retries} retries.")


# ------------------------------
# Core Function
# ------------------------------


def call_llm(prompt: str, model: str = None):
    """
    Call Groq LLM with the given prompt.

    Args:
        prompt: Text prompt for the LLM
        model: Model name (uses PRIMARY_MODEL if not specified)

    Returns:
        dict: {"status": "success"|"error", "response"|"error": str}
    """
    target_model = model or PRIMARY_MODEL

    if client is None:
        return {"status": "error", "error": init_error}

    try:
        raw_response = safe_generate(prompt, target_model)
        text_output = extract_text(raw_response)

        if text_output.startswith("["):
            return {"status": "error", "error": text_output}

        return {"status": "success", "response": text_output}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================


def run_llm_tool(prompt: str, model: str = "default"):
    """
    Smith tool interface for LLM calls.
    """
    if model == "default":
        model = PRIMARY_MODEL
    return call_llm(prompt, model)


# --- CRITICAL ALIAS FIX ---
llm_caller = run_llm_tool
# --------------------------

METADATA = {
    "name": "llm_caller",
    "description": "Access a Large Language Model (Llama 3.3 70B via Groq) to summarize text, answer questions, or write code.",
    "function": "run_llm_tool",
    "dangerous": False,
    "domain": "reasoning",
    "output_type": "synthesis",
    "prohibited_outputs": ["numeric_data", "factual_claims", "real_time_data"],
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "default"},
        },
        "required": ["prompt"],
    },
}
