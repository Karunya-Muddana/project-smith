"""
MemoryStore — disk-backed vector store for Smith long-term memory.

Layout on disk (~/.smith_memory/ by default):
    index.npz        — numpy matrix (N × 384) float32 + parallel key array
    records.ndjson   — one JSON object per line, ordered same as index rows
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from smith.memory.embedder import get_embedder

logger = logging.getLogger("smith.memory.store")


@dataclass
class MemoryRecord:
    id: str
    text: str
    timestamp: float
    session_id: str
    source_type: str          # "interaction" | "summary" | "tool_output"
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryStore:
    def __init__(self, store_dir: Optional[str] = None):
        from smith.config import config as _cfg

        _dir = store_dir or getattr(_cfg, "memory_dir", "~/.smith_memory")
        self._dir = Path(os.path.expanduser(_dir))
        self._index_path = self._dir / "index.npz"
        self._records_path = self._dir / "records.ndjson"
        self._lock = threading.Lock()

        self._records: List[MemoryRecord] = []
        self._matrix: np.ndarray = np.empty((0, 384), dtype=np.float32)

        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"MemoryStore: could not create dir {self._dir}: {e}")

        self._load()

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        """Load index and records from disk. Missing files start empty."""
        if not self._records_path.exists() or not self._index_path.exists():
            return
        try:
            records: List[MemoryRecord] = []
            with self._records_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        obj = json.loads(line)
                        records.append(MemoryRecord(**obj))

            data = np.load(str(self._index_path), allow_pickle=False)
            matrix = data["matrix"]

            if len(records) != matrix.shape[0]:
                logger.warning("MemoryStore: index/records mismatch — resetting.")
                return

            self._records = records
            self._matrix = matrix
            logger.debug(f"MemoryStore: loaded {len(records)} records from {self._dir}")
        except Exception as e:
            logger.warning(f"MemoryStore: load failed ({e}) — starting fresh.")
            self._records = []
            self._matrix = np.empty((0, 384), dtype=np.float32)

    def _save(self) -> None:
        """Atomic write: tmp files → os.replace()."""
        tmp_records = self._records_path.with_suffix(".tmp_ndjson")
        tmp_index = self._index_path.with_suffix(".tmp_npz")
        try:
            with tmp_records.open("w", encoding="utf-8") as f:
                for r in self._records:
                    f.write(json.dumps(asdict(r)) + "\n")

            np.savez_compressed(str(tmp_index), matrix=self._matrix)

            # Rename .npy.npz quirk: numpy adds .npz if not present
            actual_tmp = Path(str(tmp_index) + ".npz") if not tmp_index.exists() else tmp_index
            actual_tmp.replace(self._index_path)
            tmp_records.replace(self._records_path)
        except Exception as e:
            logger.warning(f"MemoryStore: save failed: {e}")
            for p in (tmp_records, tmp_index, Path(str(tmp_index) + ".npz")):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add(
        self,
        text: str,
        session_id: str,
        source_type: str = "interaction",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        embedder = get_embedder()
        vec = embedder.embed(text).reshape(1, -1)

        record = MemoryRecord(
            id=str(uuid.uuid4()),
            text=text,
            timestamp=time.time(),
            session_id=session_id,
            source_type=source_type,
            metadata=metadata or {},
        )

        with self._lock:
            self._records.append(record)
            self._matrix = np.vstack([self._matrix, vec]) if self._matrix.shape[0] else vec
            self._save()

        return record.id

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.25,
    ) -> List[Tuple[MemoryRecord, float]]:
        if self._matrix.shape[0] == 0:
            return []

        embedder = get_embedder()
        q_vec = embedder.embed(query)

        # Cosine similarity (vectors are already L2-normalized by embedder)
        scores = self._matrix @ q_vec  # shape (N,)

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score >= min_score:
                results.append((self._records[idx], score))

        return results

    def get_recent(self, n: int = 10) -> List[MemoryRecord]:
        sorted_records = sorted(self._records, key=lambda r: r.timestamp, reverse=True)
        return sorted_records[:n]

    def delete(self, record_id: str) -> bool:
        with self._lock:
            idx = next((i for i, r in enumerate(self._records) if r.id == record_id), None)
            if idx is None:
                return False
            self._records.pop(idx)
            self._matrix = np.delete(self._matrix, idx, axis=0)
            self._save()
        return True

    def delete_batch(self, record_ids: List[str]) -> int:
        id_set = set(record_ids)
        with self._lock:
            keep = [(i, r) for i, r in enumerate(self._records) if r.id not in id_set]
            removed = len(self._records) - len(keep)
            if removed == 0:
                return 0
            self._records = [r for _, r in keep]
            keep_idx = [i for i, _ in keep]
            self._matrix = self._matrix[keep_idx] if keep_idx else np.empty((0, 384), dtype=np.float32)
            self._save()
        return removed

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records = []
            self._matrix = np.empty((0, 384), dtype=np.float32)
            self._save()
        return count

    def count(self) -> int:
        return len(self._records)

    def stats(self) -> Dict[str, Any]:
        size_kb = 0.0
        for p in (self._index_path, self._records_path):
            try:
                size_kb += p.stat().st_size / 1024
            except OSError:
                pass

        oldest = min((r.timestamp for r in self._records), default=None)
        newest = max((r.timestamp for r in self._records), default=None)

        return {
            "records": len(self._records),
            "store_dir": str(self._dir),
            "size_kb": round(size_kb, 1),
            "oldest": oldest,
            "newest": newest,
        }
