"""
LLM CALLER — NVIDIA Inference Edition
------------------------------------
Calls NVIDIA's chat completion endpoint for LLM inference.
Configuration:
    - NVIDIA_BASE_URL
    - NVIDIA_LLM_API_KEY
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

# NVIDIA Inference API key
API_KEY = os.getenv("NVIDIA_LLM_API_KEY", "")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

VALID_MODELS = [
    os.getenv(
        "SMITH_LLM_MODEL",
        "meta/llama-4-maverick-17b-128e-instruct",
    ),
]

PRIMARY_MODEL = VALID_MODELS[0]

init_error = None

# Minimal rate limiter — just to avoid hammering the API
_global_lock = threading.Lock()
_last_call_time = 0.0
_MIN_CALL_INTERVAL = 0.3  # seconds between API calls


def _global_rate_limit():
    """Enforce minimal delay between API calls."""
    global _last_call_time
    with _global_lock:
        now = time.time()
        elapsed = now - _last_call_time
        if elapsed < _MIN_CALL_INTERVAL:
            sleep_time = _MIN_CALL_INTERVAL - elapsed
            time.sleep(sleep_time)
        _last_call_time = time.time()


try:
    import requests as _requests
except ImportError:
    init_error = "requests module not found. Run: pip install requests"
else:
    if not API_KEY:
        init_error = "Missing NVIDIA_LLM_API_KEY environment variable."


# ------------------------------
# Helper Functions
# ------------------------------


def _generate(prompt: str, model: str) -> str:
    """Call the NVIDIA inference API and return message text."""
    import requests

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 8192,
        "top_p": 0.95,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
        "stream": False,
    }
    resp = requests.post(
        NVIDIA_BASE_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Malformed NVIDIA response: expected JSON object, got {type(data).__name__}: {data!r}"
        )

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(
            f"Malformed NVIDIA response: missing or empty 'choices'. Raw response: {data!r}"
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError(
            f"Malformed NVIDIA response: first choice is not an object. Raw response: {data!r}"
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(
            f"Malformed NVIDIA response: missing 'message' object. Raw response: {data!r}"
        )

    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError(
            f"Malformed NVIDIA response: missing string 'content'. Raw response: {data!r}"
        )

    return content


def safe_generate(prompt: str, model: str, max_retries: int = 3, base_delay: int = 2):
    """Call NVIDIA Inference API with retry logic."""
    if init_error:
        raise RuntimeError(f"Client not initialized: {init_error}")

    current_model = model

    for attempt in range(max_retries + 1):
        try:
            _global_rate_limit()

            return _generate(prompt, current_model)

        except Exception as e:
            msg = str(e).lower()

            # Handle rate limiting
            if "429" in msg or "rate_limit" in msg or "rate limit" in msg:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Rate limit hit ({current_model}). Sleeping {delay}s..."
                )
                time.sleep(delay)
                continue

            # Re-raise on final attempt
            if attempt == max_retries:
                raise e

            # Generic retry with backoff
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Error: {e}. Retrying in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(f"LLM failed after {max_retries} retries.")


# ------------------------------
# Core Function
# ------------------------------


def call_llm(prompt: str, model: str = None):
    """
    Unified LLM caller with multi-backend routing.
    """

    target_model = model or PRIMARY_MODEL

    if init_error:
        raise RuntimeError(f"Client not initialized: {init_error}")

    try:
        # ── NVIDIA / DeepSeek routing ────────────────────────
        if "deepseek" in target_model:
            return {
                "status": "success",
                "response": safe_generate(prompt, target_model)
            }

        # ── Default (Groq / others) ──────────────────────────
        return {
            "status": "success",
            "response": safe_generate(prompt, target_model)
        }

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
    "description": (
        "Access a Large Language Model via NVIDIA Inference to summarize text, answer questions, or write code."
    ),
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
