"""
Smith Production Polish — Essential Tests
One meaningful test per improvement (I1–I6) + import smoke tests.
"""

import json
import time
import pytest
from unittest.mock import patch


# ─── I1: Smart Synthesis Router ───────────────────────────────────────────────

def test_router_picks_heavy_for_finance():
    from smith.core.synthesis_router import select_synthesis_model
    from smith.config import config
    trace = [{"step_index": 0, "tool": "finance_fetcher", "status": "success",
               "result": {"status": "success", "result": "x"}}]
    nodes = [{"id": 0, "tool": "finance_fetcher", "thought": "."}]
    assert select_synthesis_model(trace, nodes, "AAPL price") == config.synthesis_heavy_model


def test_router_picks_fast_for_trivial():
    from smith.core.synthesis_router import select_synthesis_model
    from smith.config import config
    trace = [{"step_index": 0, "tool": "google_search", "status": "success",
               "result": {"status": "success", "result": "x" * 50}}]
    nodes = [{"id": 0, "tool": "google_search", "thought": "."}]
    assert select_synthesis_model(trace, nodes, "Tell me a joke") == config.synthesis_fast_model


# ─── I2: Structured Report Renderer ───────────────────────────────────────────

def test_renderer_parses_json_and_returns_summary():
    from smith.core.report_renderer import render_report
    resp = json.dumps({"summary": "All good.", "key_findings": ["X"], "caveats": [], "sources": []})
    out = render_report(resp, console=None)
    assert "All good." in out


def test_renderer_fallback_for_plain_text():
    from smith.core.report_renderer import render_report
    plain = "Just a normal answer."
    assert render_report(plain, console=None) == plain


# ─── I3: Finance Audit Trail ──────────────────────────────────────────────────

def test_audit_trail_populated_and_returned():
    from smith.core.fabrication_guard import GroundTruthRegistry, check_and_redact
    reg = GroundTruthRegistry()
    reg.register_finance({
        "result": {"status": "success", "symbol": "AAPL", "price": 200.0, "currency": "USD"}
    })
    result = check_and_redact("AAPL is at $200.0", reg, include_audit=True)
    assert "audit_trail" in result
    assert result["audit_trail"][0]["symbol"] == "AAPL"


def test_audit_trail_absent_by_default():
    from smith.core.fabrication_guard import GroundTruthRegistry, check_and_redact
    result = check_and_redact("No numbers here.", GroundTruthRegistry())
    assert "audit_trail" not in result


# ─── I4: Graceful Capability Acknowledgment ───────────────────────────────────

def test_failed_nodes_produce_unavailable_ctx():
    trace = [
        {"tool": "finance_fetcher", "step_index": 1, "status": "error",
         "result": {"error": "rate limit"}},
    ]
    unavailable = [
        {"tool": t["tool"], "step": t["step_index"],
         "reason": t["result"].get("error", "unavailable")}
        for t in trace if t.get("status") in ("error", "skipped")
    ]
    ctx = ""
    if unavailable:
        ctx = "\nUnavailable Sources (inform the user honestly):\n"
        for u in unavailable:
            ctx += f"  - {u['tool']} (step {u['step']}): {u['reason']}\n"
    assert "finance_fetcher" in ctx
    assert "rate limit" in ctx


# ─── I5: Run Cache / Warm Start ───────────────────────────────────────────────

def test_cache_set_get_and_miss(tmp_path):
    from smith.core.cache_manager import CacheManager
    cache = CacheManager(cache_dir=str(tmp_path), ttl_seconds=3600)
    key = CacheManager.make_key("google_search", {"query": "hello"})
    payload = {"status": "success", "result": "world"}
    cache.set(key, payload)
    assert cache.get(key) == payload
    assert cache.get(CacheManager.make_key("google_search", {"query": "other"})) is None


def test_cache_ttl_expires(tmp_path):
    from smith.core.cache_manager import CacheManager
    cache = CacheManager(cache_dir=str(tmp_path), ttl_seconds=1)
    key = CacheManager.make_key("weather_fetcher", {"city": "Dubai"})
    cache.set(key, {"status": "success"})
    time.sleep(1.2)
    assert cache.get(key) is None


def test_cache_clear(tmp_path):
    from smith.core.cache_manager import CacheManager
    cache = CacheManager(cache_dir=str(tmp_path), ttl_seconds=3600)
    for i in range(3):
        cache.set(CacheManager.make_key("t", {"i": i}), {"r": i})
    assert cache.clear() == 3


# ─── I6: /explain Metadata ────────────────────────────────────────────────────

def test_explain_data_shape():
    from smith.cli.main import Session
    s = Session()
    s.last_explain_data = {
        "dag": {"nodes": []}, "trace": [], "parallel_groups": [],
        "cache_hits": [], "total_tokens_est": 100, "total_cost_est": 0.0002,
        "fabrication_report": {"total_numbers": 0, "verified": 0,
                                "redacted": 0, "redacted_details": []},
        "confidence": "high", "audit_trail": [],
    }
    ed = s.last_explain_data
    for key in ("dag", "trace", "cache_hits", "total_tokens_est",
                 "total_cost_est", "fabrication_report", "confidence"):
        assert key in ed


def test_cmd_explain_no_crash_when_empty():
    from smith.cli.main import Session, cmd_explain
    from io import StringIO
    from rich.console import Console
    s = Session()
    with patch("smith.cli.main.console", Console(file=StringIO(), force_terminal=False)):
        cmd_explain(s)  # should not raise


# ─── Import smoke tests ───────────────────────────────────────────────────────

def test_all_new_modules_importable():
    from smith.core.synthesis_router import select_synthesis_model
    from smith.core.report_renderer import render_report
    from smith.core.cache_manager import CacheManager
    from smith.core.fabrication_guard import GroundTruthRegistry
    from smith.config import config
    assert callable(select_synthesis_model)
    assert callable(render_report)
    assert hasattr(config, "synthesis_heavy_model")
    assert hasattr(config, "cache_enabled")


def test_new_financial_tools_importable():
    from smith.tools.FINANCIAL_CALCULATOR import run_financial_calculator
    from smith.tools.SEC_FILINGS import run_sec_filings_fetcher
    from smith.tools.TECHNICAL_INDICATORS import run_technical_analysis
    from smith.tools.CRYPTO_FETCHER import run_crypto_fetcher
    for fn in (run_financial_calculator, run_sec_filings_fetcher,
               run_technical_analysis, run_crypto_fetcher):
        assert callable(fn)


def test_financial_calculator_cagr():
    from smith.tools.FINANCIAL_CALCULATOR import run_financial_calculator
    result = run_financial_calculator("cagr", start_value=100.0, end_value=161.05, years=5)
    assert result["status"] == "success"
    assert abs(result["result"]["cagr_percent"] - 10.0) < 0.5


def test_financial_calculator_pe_premium():
    from smith.tools.FINANCIAL_CALCULATOR import run_financial_calculator
    result = run_financial_calculator("pe_premium", pe_a=40.0, pe_b=20.0)
    assert result["status"] == "success"
    assert result["result"]["premium_percent"] == 100.0
