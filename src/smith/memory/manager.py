"""
MemoryManager — high-level read/write/summarize API over MemoryStore.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from smith.memory.store import MemoryRecord, MemoryStore

logger = logging.getLogger("smith.memory.manager")


class MemoryManager:
    def __init__(self, store: Optional[MemoryStore] = None):
        self._store = store or MemoryStore()
        self._session_id: str = str(uuid.uuid4())[:8]
        self._turn_counter: int = 0

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    def write_interaction(self, user_message: str, assistant_response: str) -> None:
        """Store a user/assistant turn as a single memory chunk."""
        from smith.config import config
        if not config.memory_enabled:
            return

        # Truncate assistant response to keep chunks focused
        response_snippet = (assistant_response or "")[:600].strip()
        chunk = f"User: {user_message.strip()}\nSmith: {response_snippet}"

        self._store.add(
            text=chunk,
            session_id=self._session_id,
            source_type="interaction",
            metadata={"turn": self._turn_counter},
        )
        self._turn_counter += 1

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    def read_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        """
        Return a formatted block of relevant past memories for injection into the planner.
        Returns an empty string if memory is disabled or nothing relevant is found.
        """
        from smith.config import config
        if not config.memory_enabled or self._store.count() == 0:
            return ""

        k = top_k or config.memory_top_k
        limit = max_chars or config.memory_inject_max_chars

        results = self._store.search(
            query,
            top_k=k,
            min_score=config.memory_min_score,
        )
        if not results:
            return ""

        lines: List[str] = []
        total = 0
        for record, score in results:
            dt = datetime.fromtimestamp(record.timestamp).strftime("%Y-%m-%d %H:%M")
            entry = f"[{dt} | score={score:.2f}]\n{record.text}"
            if total + len(entry) > limit:
                break
            lines.append(entry)
            total += len(entry)

        return "\n\n".join(lines)

    # ------------------------------------------------------------------ #
    # Summarize                                                            #
    # ------------------------------------------------------------------ #

    def maybe_summarize(self, force: bool = False) -> Optional[str]:
        """
        Compress oldest records into a summary when the store is near capacity.
        No-op unless count > 90% of memory_max_records.
        """
        from smith.config import config
        threshold = int(config.memory_max_records * 0.9)

        if not force and self._store.count() < threshold:
            return None

        batch_size = config.memory_summarize_batch
        oldest = sorted(self._store.get_recent(self._store.count()), key=lambda r: r.timestamp)
        batch = oldest[:batch_size]

        if not batch:
            return None

        joined = "\n\n".join(r.text for r in batch)
        prompt = (
            "Summarize the following past conversation memories into one compact paragraph. "
            "Preserve key facts, decisions, user preferences, and recurring topics. Be concise.\n\n"
            f"---\n{joined}\n---"
        )

        try:
            from smith.tools.LLM_CALLER import call_llm
            result = call_llm(prompt)
            if result.get("status") != "success":
                return None

            summary = result.get("response", "").strip()
            if not summary:
                return None

            # Write summary, delete originals
            self._store.add(
                text=summary,
                session_id=self._session_id,
                source_type="summary",
                metadata={"compressed_count": len(batch)},
            )
            self._store.delete_batch([r.id for r in batch])
            logger.info(f"MemoryManager: summarized {len(batch)} records into 1 summary.")
            return summary

        except Exception as e:
            logger.warning(f"MemoryManager: summarization failed (non-fatal): {e}")
            return None

    # ------------------------------------------------------------------ #
    # Query helpers                                                        #
    # ------------------------------------------------------------------ #

    def search(self, query: str, top_k: int = 10) -> List[Tuple[MemoryRecord, float]]:
        return self._store.search(query, top_k=top_k)

    def get_recent(self, n: int = 10) -> List[MemoryRecord]:
        return self._store.get_recent(n)

    def clear(self) -> int:
        return self._store.clear()

    def stats(self) -> dict:
        return self._store.stats()
