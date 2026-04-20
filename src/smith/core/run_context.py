"""
RunContextManager — Per-Run Step Accumulator + BM25 RAG Retrieval
-----------------------------------------------------------------
Writes every non-final step output to a .ndjson file on disk.
Provides BM25-style keyword retrieval so the synthesis critic
can pull relevant sections without being limited by context window.

File format: newline-delimited JSON, one record per step.
Location: {project_root}/.smith_runs/run_{run_id}.ndjson
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.run_context")

# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

def _runs_dir() -> Path:
    """Return (and create) the .smith_runs directory next to the project root."""
    # Walk up from this file to find the project root (contains pyproject.toml)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / "setup.py").exists():
            runs = parent / ".smith_runs"
            runs.mkdir(exist_ok=True)
            return runs
    # Fallback: cwd
    fallback = Path.cwd() / ".smith_runs"
    fallback.mkdir(exist_ok=True)
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# BM25 helpers (no external deps)
# ─────────────────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "it", "this", "that", "be",
    "as", "by", "from", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "not", "no",
}

_K1 = 1.5
_B  = 0.75


def _tokenize(text: str) -> List[str]:
    """Lowercase word-tokenization, removing stopwords and short tokens."""
    tokens = re.findall(r"[a-z]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _bm25_score(query_terms: List[str], doc_tokens: List[str], avg_dl: float) -> float:
    """Compute BM25 score for a single document."""
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for term in query_terms:
        f = tf.get(term, 0)
        if f == 0:
            continue
        idf = math.log(2)  # Simplified IDF (no corpus-wide stats)
        num = f * (_K1 + 1)
        den = f + _K1 * (1 - _B + _B * dl / max(avg_dl, 1))
        score += idf * (num / den)
    return score


# ─────────────────────────────────────────────────────────────────────────────
# RunContextManager
# ─────────────────────────────────────────────────────────────────────────────

class RunContextManager:
    """
    Manages the per-run step accumulator file and provides RAG retrieval.

    Usage:
        ctx = RunContextManager(run_id="abc123")
        ctx.append_step(step_idx=0, tool="llm_caller", thought="...", response="...")
        results = ctx.retrieve("missing sections on memory systems", top_k=3)
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._path: Path = _runs_dir() / f"run_{run_id}.ndjson"
        self._records: List[Dict[str, Any]] = []
        logger.debug(f"RunContextManager: run file at {self._path}")

    # ── Write ────────────────────────────────────────────────────────────────

    def append_step(
        self,
        step_idx: int,
        tool: str,
        thought: str,
        response_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append a completed step's output to the run context file.
        Also keeps an in-memory cache for fast access within the same run.
        """
        if not response_text or not response_text.strip():
            return  # Don't store empty results

        record: Dict[str, Any] = {
            "step":      step_idx,
            "tool":      tool,
            "thought":   thought,
            "text":      response_text,
            "tokens":    len(response_text) // 4,  # approximate
            "ts":        time.time(),
            **(metadata or {}),
        }
        self._records.append(record)

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"RunContextManager: failed to write step {step_idx}: {e}")

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_all_steps(self) -> List[Dict[str, Any]]:
        """Return all accumulated step records (from memory cache)."""
        return list(self._records)

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """
        BM25-style retrieval over accumulated step texts.
        Returns top_k most relevant step texts for the given query.
        """
        if not self._records:
            return []

        query_terms = _tokenize(query)
        if not query_terms:
            # Fallback: return last top_k records
            return [r["text"] for r in self._records[-top_k:]]

        # Tokenize all docs
        doc_tokens = [_tokenize(r["text"]) for r in self._records]

        # Average document length for BM25 normalization
        avg_dl = sum(len(d) for d in doc_tokens) / max(len(doc_tokens), 1)

        # Score each record
        scored = []
        for i, (record, tokens) in enumerate(zip(self._records, doc_tokens)):
            score = _bm25_score(query_terms, tokens, avg_dl)
            scored.append((score, i, record))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx, record in scored[:top_k]:
            if score > 0:
                header = f"[Step {record['step']} — {record['tool']}: {record['thought'][:80]}]"
                results.append(f"{header}\n{record['text']}")
            else:
                break  # No more relevant results

        return results

    def retrieve_all_text(self, max_chars: int = 20_000) -> str:
        """
        Return all step texts joined together, truncated to max_chars.
        Used for full-paper synthesis where we want everything.
        """
        parts = []
        total = 0
        for record in self._records:
            header = f"\n\n## Step {record['step']} — {record['tool']}\n"
            chunk = header + record["text"]
            if total + len(chunk) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    parts.append(chunk[:remaining] + "\n[... truncated ...]")
                break
            parts.append(chunk)
            total += len(chunk)
        return "".join(parts)

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup(self, keep_latest: int = 20) -> None:
        """Remove old run files, keeping only the N most recent."""
        try:
            runs_dir = self._path.parent
            files = sorted(runs_dir.glob("run_*.ndjson"), key=lambda p: p.stat().st_mtime)
            for old_file in files[:-keep_latest]:
                old_file.unlink(missing_ok=True)
                logger.debug(f"RunContextManager: cleaned up {old_file.name}")
        except OSError:
            pass
