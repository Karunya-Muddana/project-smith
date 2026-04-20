"""
LLM CALLER — OpenRouter Edition
---------------------------------
Uses OpenRouter API for LLM inference.
Supports free NVIDIA Nemotron model via OpenRouter.
"""

import os
import time
import logging
import threading
import json
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

# OpenRouter API key
API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "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",
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

VALID_MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
]

PRIMARY_MODEL = VALID_MODELS[0]

client = None
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


# --- Initialize OpenAI-compatible client for OpenRouter ---
try:
    from openai import OpenAI

    if API_KEY:
        client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=API_KEY,
        )
    else:
        init_error = "Missing OPENROUTER_API_KEY environment variable."

except ImportError:
    # Fallback: use requests directly
    client = None
    logger.warning("openai module not found — will use requests fallback.")

    try:
        import requests as _requests
    except ImportError:
        init_error = "Neither 'openai' nor 'requests' module found. Install one."


# ------------------------------
# Helper Functions
# ------------------------------


def extract_text(response) -> str:
    """Extract text from OpenAI-compatible response."""
    try:
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content
        return "[EMPTY RESPONSE]"
    except Exception as e:
        return f"[PARSE ERROR] {str(e)}"


def _fallback_generate(prompt: str, model: str) -> dict:
    """Use raw requests as fallback when openai SDK is not available."""
    import requests

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 8192,
        "top_p": 0.95,
    }
    resp = requests.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return {"status": "success", "response": content}


def safe_generate(prompt: str, model: str, max_retries: int = 3, base_delay: int = 2):
    """Call OpenRouter API with retry logic."""
    if client is None and init_error and "requests" not in str(init_error).lower():
        raise RuntimeError(f"Client not initialized: {init_error}")

    current_model = model

    for attempt in range(max_retries + 1):
        try:
            _global_rate_limit()

            if client is not None:
                # Use OpenAI SDK
                response = client.chat.completions.create(
                    model=current_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=8192,
                    top_p=0.95,
                )
                return response
            else:
                # Fallback to requests
                result = _fallback_generate(prompt, current_model)
                # Wrap in a simple object for compatibility
                class _FakeResponse:
                    class _Choice:
                        class _Message:
                            def __init__(self, content):
                                self.content = content
                        def __init__(self, content):
                            self.message = self._Message(content)
                    def __init__(self, content):
                        self.choices = [self._Choice(content)]
                return _FakeResponse(result["response"])

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
    Call LLM via OpenRouter with the given prompt.

    Args:
        prompt: Text prompt for the LLM
        model: Model name (uses PRIMARY_MODEL if not specified)

    Returns:
        dict: {"status": "success"|"error", "response"|"error": str}
    """
    target_model = model or PRIMARY_MODEL

    # Ignore old Groq model names — always use our OpenRouter model
    if "llama" in target_model.lower() or "mixtral" in target_model.lower():
        target_model = PRIMARY_MODEL

    if client is None and init_error and "requests" not in str(init_error).lower():
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
    "description": (
        "Access a Large Language Model (NVIDIA Nemotron 30B via OpenRouter) to summarize text, answer questions, or write code."
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
