"""
Cache Manager — Run Cache / Warm Start
---------------------------------------
Disk-backed TTL cache for tool results.

Cache key: SHA-256(tool_name + canonical-JSON-args)
Storage:   ~/.smith_cache/<hex_key>.json
Entry format:
  {
    "key":       "<hex>",
    "tool":      "google_search",
    "args_hash": "<hex>",
    "result":    { ... },
    "created_at": <unix timestamp>,
    "ttl":        3600
  }

On `get`: if entry exists and is not expired, return result. Expired entries
          are deleted lazily on read.
On `set`: write entry atomically using a .tmp file + rename.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("smith.cache_manager")


def _make_cache_key(tool_name: str, args: Dict[str, Any]) -> str:
    """Return a stable hex digest for (tool_name, args)."""
    try:
        # Sort keys for canonical form
        canonical = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, default=str)
    except Exception:
        canonical = f"{tool_name}:{str(args)}"
    return hashlib.sha256(canonical.encode()).hexdigest()


class CacheManager:
    """
    Disk-backed TTL cache for tool results.

    Usage:
        cache = CacheManager()
        key = cache.make_key("google_search", {"query": "hello"})
        hit = cache.get(key)
        if hit is None:
            result = run_tool()
            cache.set(key, result, tool_name="google_search")
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        ttl_seconds: int = 3600,
    ):
        from smith.config import config as _cfg

        _dir = cache_dir or getattr(_cfg, "cache_dir", "~/.smith_cache")
        self._cache_dir = Path(os.path.expanduser(_dir))
        self._ttl = ttl_seconds or getattr(_cfg, "cache_ttl_seconds", 3600)
        self._hits = 0
        self._misses = 0
        self._sets = 0

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"CacheManager: could not create cache dir {self._cache_dir}: {e}")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def make_key(tool_name: str, args: Dict[str, Any]) -> str:
        """Return a stable cache key for (tool_name, args)."""
        return _make_cache_key(tool_name, args)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached result.

        Returns the cached `result` dict, or None if missing / expired.
        """
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            self._misses += 1
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.debug(f"CacheManager.get: corrupt entry {key}: {e}")
            self._misses += 1
            return None

        # TTL check
        created_at = entry.get("created_at", 0)
        ttl = entry.get("ttl", self._ttl)
        if time.time() - created_at > ttl:
            # Expired — clean up lazily
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            logger.debug(f"CacheManager.get: expired entry {key}")
            self._misses += 1
            return None

        self._hits += 1
        logger.debug(
            f"CacheManager: HIT {key[:12]}… "
            f"(tool={entry.get('tool')}, age={int(time.time()-created_at)}s)"
        )
        return entry.get("result")

    def set(
        self,
        key: str,
        result: Dict[str, Any],
        tool_name: str = "unknown",
    ) -> None:
        """
        Store a result in the cache.

        Uses atomic write (tmp → rename) to prevent corrupt reads.
        """
        entry = {
            "key": key,
            "tool": tool_name,
            "result": result,
            "created_at": time.time(),
            "ttl": self._ttl,
        }
        tmp_path = self._cache_dir / f"{key}.tmp"
        final_path = self._cache_dir / f"{key}.json"
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(entry, f, default=str)
            tmp_path.replace(final_path)
            self._sets += 1
            logger.debug(f"CacheManager: SET {key[:12]}… (tool={tool_name})")
        except OSError as e:
            logger.warning(f"CacheManager.set: write failed for {key}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> int:
        """
        Remove all cache entries.

        Returns the number of entries removed.
        """
        removed = 0
        try:
            for p in self._cache_dir.glob("*.json"):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        except OSError as e:
            logger.warning(f"CacheManager.clear: {e}")
        logger.info(f"CacheManager: cleared {removed} entries")
        return removed

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for the current session."""
        # Count on-disk entries
        entry_count = 0
        total_size_bytes = 0
        try:
            for p in self._cache_dir.glob("*.json"):
                entry_count += 1
                try:
                    total_size_bytes += p.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass

        total_lookups = self._hits + self._misses
        hit_rate = (self._hits / total_lookups) if total_lookups > 0 else 0.0

        return {
            "entries_on_disk": entry_count,
            "total_size_kb": round(total_size_bytes / 1024, 1),
            "session_hits": self._hits,
            "session_misses": self._misses,
            "session_sets": self._sets,
            "session_hit_rate": round(hit_rate * 100, 1),
            "ttl_seconds": self._ttl,
            "cache_dir": str(self._cache_dir),
        }

    def evict_expired(self) -> int:
        """Proactively remove all expired entries. Returns count evicted."""
        evicted = 0
        now = time.time()
        try:
            for p in self._cache_dir.glob("*.json"):
                try:
                    with p.open("r", encoding="utf-8") as f:
                        entry = json.load(f)
                    created_at = entry.get("created_at", 0)
                    ttl = entry.get("ttl", self._ttl)
                    if now - created_at > ttl:
                        p.unlink()
                        evicted += 1
                except (OSError, json.JSONDecodeError):
                    pass
        except OSError:
            pass
        if evicted:
            logger.info(f"CacheManager: evicted {evicted} expired entries")
        return evicted


# Module-level singleton (lazy-init)
_cache_instance: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Return the shared CacheManager singleton (creates on first call)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager()
    return _cache_instance
