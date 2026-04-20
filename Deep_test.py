"""
Deep_test.py
------------
Tests for run_deep_summarizer and _extract_text.

HOW THE PATCH WORKS:
  We patch `call_llm` at the point it is *used*, not where it is *defined*.
  The module is imported directly so Python doesn't need to resolve
  `smith.tools.deep_summarizer` as a dotted package path — which was
  causing the ModuleNotFoundError.

Usage:
    python Deep_test.py
"""

import sys
import json
import unittest
import importlib
from unittest.mock import patch, MagicMock

# ── Import the module object directly ────────────────────────────────────────
# Adjust this path if your file is named differently, e.g. DEEP_SUMMARIZER
import importlib.util, pathlib

# Try common naming variants automatically
_candidates = [
    "smith.tools.DEEP_SUMMARIZER",
    "smith.tools.deep_summarizer",
    "smith.tools.DeepSummarizer",
]

_mod = None
for _name in _candidates:
    try:
        _mod = importlib.import_module(_name)
        _MODULE_PATH = _name          # e.g. "smith.tools.DEEP_SUMMARIZER"
        print(f"[setup] Loaded module: {_name}")
        break
    except ModuleNotFoundError:
        continue

if _mod is None:
    print(
        "\n[ERROR] Could not import the deep_summarizer module under any known name.\n"
        "Edit _candidates at the top of this file to match your actual filename.\n"
    )
    sys.exit(1)

# Pull the two functions we need to test
run_deep_summarizer = _mod.run_deep_summarizer
_extract_text       = _mod._extract_text

# The patch target must match the module that was actually loaded
_PATCH_TARGET = f"{_MODULE_PATH}.call_llm"


# ─────────────────────────────────────────────────────────────────────────────
# SHARED FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

MOCK_LLM_SUCCESS = {
    "status": "success",
    "response": (
        "## Core Insights\n- Insight 1\n- Insight 2\n\n"
        "## Cause → Effect Relationships\n- A causes B\n\n"
        "## Key Patterns\n- Pattern X\n\n"
        "## Implications\n- Implication Y"
    ),
}

MOCK_LLM_FAILURE = {
    "status": "error",
    "error": "LLM timeout",
}

VALID_QUERY = "What are the key trends in AI hardware investment?"

VALID_TEXT = (
    "Nvidia reported a 122% YoY revenue increase driven by data center GPU demand. "
    "AMD launched MI300X to compete in the AI accelerator space. "
    "Intel is restructuring its foundry business after missing AI wave targets. " * 10
)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_text  (no mocking needed — pure logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractText(unittest.TestCase):

    def test_plain_string_returned_as_is(self):
        self.assertEqual(_extract_text("hello world"), "hello world")

    def test_none_returns_empty(self):
        self.assertEqual(_extract_text(None), "")

    def test_empty_string_returns_empty(self):
        self.assertEqual(_extract_text(""), "")

    def test_stringified_empty_dict_returns_empty(self):
        self.assertEqual(_extract_text("{}"), "")

    def test_dict_extracts_response_field_first(self):
        self.assertEqual(_extract_text({"response": "the answer", "summary": "other"}), "the answer")

    def test_dict_falls_back_to_summary(self):
        self.assertEqual(_extract_text({"summary": "fallback summary"}), "fallback summary")

    def test_dict_with_results_list(self):
        d = {"results": [{"snippet": "result one"}, {"snippet": "result two"}]}
        result = _extract_text(d)
        self.assertIn("result one", result)
        self.assertIn("result two", result)

    def test_dict_with_no_known_fields_serializes(self):
        result = _extract_text({"unknown_field": "some data", "other": 123})
        self.assertIn("unknown_field", result)

    def test_list_of_dicts_joins_snippets(self):
        result = _extract_text([{"snippet": "A"}, {"snippet": "B"}, {"snippet": "C"}])
        self.assertIn("A", result)
        self.assertIn("B", result)

    def test_list_of_strings(self):
        result = _extract_text(["alpha", "beta", "gamma"])
        self.assertIn("alpha", result)

    def test_list_priority_snippet_over_title(self):
        result = _extract_text([{"title": "Title", "snippet": "Snippet text"}])
        self.assertIn("Snippet text", result)

    def test_empty_list_returns_empty(self):
        self.assertEqual(_extract_text([]), "")

    def test_integer_fallback(self):
        self.assertEqual(_extract_text(42), "42")


# ─────────────────────────────────────────────────────────────────────────────
# run_deep_summarizer  (call_llm is mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunDeepSummarizer(unittest.TestCase):

    # ── Happy path ─────────────────────────────────────────────────────────

    def test_success_plain_string(self):
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS) as mock_llm:
            result = run_deep_summarizer(VALID_TEXT, VALID_QUERY)
            self.assertEqual(result["status"], "success")
            self.assertIn("Core Insights", result["response"])
            self.assertFalse(result["meta"]["truncated"])
            mock_llm.assert_called_once()

    def test_success_dict_input(self):
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS):
            result = run_deep_summarizer({"response": VALID_TEXT}, VALID_QUERY)
            self.assertEqual(result["status"], "success")

    def test_success_list_input(self):
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS):
            result = run_deep_summarizer([{"snippet": VALID_TEXT}], VALID_QUERY)
            self.assertEqual(result["status"], "success")

    # ── Truncation ──────────────────────────────────────────────────────────

    def test_long_input_is_truncated(self):
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS):
            result = run_deep_summarizer("x" * 20_000, VALID_QUERY)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["meta"]["truncated"])
            self.assertEqual(result["meta"]["input_chars"], 15_000)

    # ── Short but valid input ───────────────────────────────────────────────

    def test_short_input_proceeds(self):
        """Input below MIN_INPUT_CHARS should warn but NOT hard-fail."""
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS):
            result = run_deep_summarizer("brief summary.", VALID_QUERY)
            self.assertEqual(result["status"], "success")

    # ── Empty / null input ──────────────────────────────────────────────────

    def test_none_input_returns_error(self):
        with patch(_PATCH_TARGET) as mock_llm:
            result = run_deep_summarizer(None, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            self.assertIn("empty", result["error"].lower())
            mock_llm.assert_not_called()

    def test_empty_string_returns_error(self):
        with patch(_PATCH_TARGET) as mock_llm:
            result = run_deep_summarizer("", VALID_QUERY)
            self.assertEqual(result["status"], "error")
            mock_llm.assert_not_called()

    def test_empty_dict_returns_error(self):
        with patch(_PATCH_TARGET) as mock_llm:
            result = run_deep_summarizer({}, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            mock_llm.assert_not_called()

    def test_stringified_empty_dict_returns_error(self):
        with patch(_PATCH_TARGET) as mock_llm:
            result = run_deep_summarizer("{}", VALID_QUERY)
            self.assertEqual(result["status"], "error")
            mock_llm.assert_not_called()

    # ── LLM failure propagation ─────────────────────────────────────────────

    def test_llm_error_propagated(self):
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_FAILURE):
            result = run_deep_summarizer(VALID_TEXT, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            self.assertIn("LLM timeout", result["error"])

    def test_llm_returns_empty_response(self):
        with patch(_PATCH_TARGET, return_value={"status": "success", "response": "   "}):
            result = run_deep_summarizer(VALID_TEXT, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            self.assertIn("empty output", result["error"].lower())

    def test_llm_returns_wrong_type(self):
        with patch(_PATCH_TARGET, return_value="just a string, not a dict"):
            result = run_deep_summarizer(VALID_TEXT, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            self.assertIn("Invalid response format", result["error"])

    # ── Exception handling ──────────────────────────────────────────────────

    def test_llm_raises_exception(self):
        with patch(_PATCH_TARGET, side_effect=ConnectionError("Network unreachable")):
            result = run_deep_summarizer(VALID_TEXT, VALID_QUERY)
            self.assertEqual(result["status"], "error")
            self.assertIn("Network unreachable", result["error"])

    # ── Planner anti-pattern ────────────────────────────────────────────────

    def test_bare_steps_ref_dict_without_text_fields(self):
        """Planner passes a bare step result dict with no recognized text fields."""
        bad_ref = {"status": "success", "meta": {"model": "x"}}
        with patch(_PATCH_TARGET, return_value=MOCK_LLM_SUCCESS):
            result = run_deep_summarizer(bad_ref, VALID_QUERY)
            # Dict serializes to JSON — short but non-empty, so LLM gets called
            self.assertIn(result["status"], ("success", "error"))


# ─────────────────────────────────────────────────────────────────────────────
# LIVE LLM TEST  (no mocking — hits the real call_llm)
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveLLMCall(unittest.TestCase):
    """
    Calls run_deep_summarizer with NO mocking.
    Requires a working API key / network.
    Skipped automatically if call_llm raises an auth or connection error.
    """

    LIVE_TEXT = (
        "Nvidia reported record data center revenue of $22.6B in Q4 2024, "
        "a 409% increase year-over-year. The surge is driven entirely by "
        "demand for H100 and H200 GPUs used in LLM training and inference. "
        "AMD's MI300X is gaining traction at Microsoft and Meta but remains "
        "a distant second. Intel's Gaudi 3 has seen limited enterprise adoption."
    )
    LIVE_QUERY = "Which GPU companies are best positioned for AI infrastructure growth?"

    def test_live_call_returns_success(self):
        print("\n[LIVE] Calling real LLM — this may take a few seconds...")

        result = run_deep_summarizer(self.LIVE_TEXT, self.LIVE_QUERY)

        # If the API key is missing or network is down, skip rather than fail
        if result.get("status") == "error":
            err = result.get("error", "")
            if any(k in err.lower() for k in ("auth", "key", "unauthorized", "network", "connect", "timeout")):
                self.skipTest(f"Live LLM unavailable — skipping: {err}")

        self.assertEqual(result["status"], "success",
            msg=f"LLM returned error: {result.get('error')}")

        response = result.get("response", "")
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 100,
            msg="Response is suspiciously short — model may have returned garbage")

        for section in ("Core Insights", "Cause", "Patterns", "Implications"):
            self.assertIn(section, response,
                msg=f"Expected section '{section}' missing from response")

        meta = result.get("meta", {})
        self.assertEqual(meta.get("model"), _mod.DEEP_MODEL)
        self.assertFalse(meta.get("truncated"))

        print(f"[LIVE] Response received ({len(response)} chars)")
        print(f"[LIVE] Model: {meta.get('model')}")
        print(f"[LIVE] First 300 chars:\n{response[:300]}\n{'─'*60}")

    def test_live_call_with_dict_input(self):
        """Confirms the full pipeline works when input arrives as a dict (common planner shape)."""
        result = run_deep_summarizer({"response": self.LIVE_TEXT}, self.LIVE_QUERY)

        if result.get("status") == "error":
            err = result.get("error", "")
            if any(k in err.lower() for k in ("auth", "key", "unauthorized", "network", "connect", "timeout")):
                self.skipTest(f"Live LLM unavailable — skipping: {err}")

        self.assertEqual(result["status"], "success",
            msg=f"Dict-wrapped input failed: {result.get('error')}")
        print(f"\n[LIVE] Dict input pipeline OK ({len(result['response'])} chars)")


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run deep_summarizer tests")
    parser.add_argument("--live", action="store_true",
                        help="Also run live LLM tests (requires API access)")
    args, remaining = parser.parse_known_args()

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestExtractText))
    suite.addTests(loader.loadTestsFromTestCase(TestRunDeepSummarizer))

    if args.live:
        print("[setup] Live LLM tests ENABLED")
        suite.addTests(loader.loadTestsFromTestCase(TestLiveLLMCall))
    else:
        print("[setup] Live LLM tests SKIPPED (pass --live to enable)")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)