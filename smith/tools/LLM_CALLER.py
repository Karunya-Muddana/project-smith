"""
LLM CALLER — Stable Edition
---------------------------
Prioritizes Gemini 2.5 Flash. Falls back to 1.5 Flash if 2.5 is blocked.
"""

import os
import time
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] llm_caller: %(message)s")
logger = logging.getLogger("llm_caller")

load_dotenv()

# ------------------------------
# Configuration
# ------------------------------

API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

VALID_MODELS = [
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

PRIMARY_MODEL = VALID_MODELS[0]

client = None
init_error = None

try:
    from google import genai
    from google.genai import types
    if API_KEY:
        client = genai.Client(api_key=API_KEY)
    else:
        init_error = "Missing GOOGLE_API_KEY environment variable."
except ImportError:
    init_error = "Module 'google.genai' not found."
except Exception as e:
    init_error = str(e)

# ------------------------------
# Helper Functions
# ------------------------------

def extract_text(response) -> str:
    try:
        if hasattr(response, "text") and response.text:
            return response.text
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason") and str(candidate.finish_reason) != "STOP":
                return f"[BLOCKED] Response stopped due to: {candidate.finish_reason}"
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                return "".join([p.text for p in candidate.content.parts if hasattr(p, "text")])
        return "[EMPTY RESPONSE]"
    except Exception as e:
        return f"[PARSE ERROR] {str(e)}"

def safe_generate(prompt: str, model: str, max_retries: int = 3, base_delay: int = 2):
    if not client: raise RuntimeError(f"Client not initialized: {init_error}")
    current_model = model
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=current_model, contents=[prompt],
                config=types.GenerateContentConfig(temperature=0.7, top_p=0.95, max_output_tokens=8192)
            )
            return response
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "resource_exhausted" in msg or "503" in msg:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Rate limit hit ({current_model}). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            if "403" in msg or "404" in msg or "not found" in msg or "permission_denied" in msg:
                if current_model in VALID_MODELS:
                    try:
                        current_idx = VALID_MODELS.index(current_model)
                        if current_idx + 1 < len(VALID_MODELS):
                            fallback = VALID_MODELS[current_idx + 1]
                            logger.warning(f"Model '{current_model}' blocked. Switching to: {fallback}")
                            current_model = fallback
                            continue
                    except ValueError: pass
            raise e
    raise RuntimeError(f"LLM failed after {max_retries} retries.")

# ------------------------------
# Core Function
# ------------------------------

def call_llm(prompt: str, model: str = None):
    target_model = model or PRIMARY_MODEL
    if client is None: return {"status": "error", "error": init_error}
    try:
        raw_response = safe_generate(prompt, target_model)
        text_output = extract_text(raw_response)
        if text_output.startswith("[BLOCKED]"): return {"status": "error", "error": text_output}
        return {"status": "success", "response": text_output}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================

def run_llm_tool(prompt: str, model: str = "default"):
    if model == "default": model = PRIMARY_MODEL
    return call_llm(prompt, model)

# --- CRITICAL ALIAS FIX ---
llm_caller = run_llm_tool
# --------------------------

METADATA = {
    "name": "llm_caller",
    "description": "Access a Large Language Model (Gemini 2.5) to summarize text or write code.",
    "function": "run_llm_tool",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "default"}
        },
        "required": ["prompt"]
    }
}