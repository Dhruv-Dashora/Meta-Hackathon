"""Server-held evidence cache: sessions + cached unified analyses (MVP).

Trust model:
- The cache holds server-generated ``UnifiedAnalysisResponse`` objects only.
  Client-submitted findings are never stored or trusted.
- Each entry is owned by one browser session. Retrieval requires BOTH the
  owning session id and the unpredictable analysis reference, so a leaked
  or guessed reference alone grants nothing.
- Unknown refs, wrong sessions, and expired entries are indistinguishable
  (all return None); routes map that to one generic "unavailable" error.

Bounds: entry count, per-entry serialized bytes, and TTL are all capped
(see ``app.core.config``). Oversize responses are not cached.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.schemas.unified_analysis import UnifiedAnalysisResponse

SESSION_HEADER = "x-session-id"
ANALYSIS_REF_PREFIX = "anl_"


@dataclass
class CachedAnalysis:
    response: UnifiedAnalysisResponse
    width: int
    height: int
    stored_at: float = field(default_factory=time.monotonic)
    expires_at: float = 0.0


class SessionStore:
    """Opaque browser-session ids with TTL. Thread-safe."""

    def __init__(self, ttl_s: float | None = None) -> None:
        self._ttl_s = ttl_s if ttl_s is not None else settings.session_ttl_s
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}

    def create(self) -> str:
        session_id = secrets.token_urlsafe(16)
        with self._lock:
            self._prune_locked()
            self._sessions[session_id] = time.monotonic() + self._ttl_s
        return session_id

    def valid(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            self._prune_locked()
            return session_id in self._sessions

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [sid for sid, exp in self._sessions.items() if exp <= now]
        for sid in expired:
            del self._sessions[sid]


class AnalysisStore:
    """Bounded TTL cache of server-generated analyses. Thread-safe."""

    def __init__(
        self,
        ttl_s: float | None = None,
        max_entries: int | None = None,
        max_entry_bytes: int | None = None,
    ) -> None:
        self._ttl_s = ttl_s if ttl_s is not None else settings.analysis_cache_ttl_s
        self._max_entries = (
            max_entries
            if max_entries is not None
            else settings.analysis_cache_max_entries
        )
        self._max_entry_bytes = (
            max_entry_bytes
            if max_entry_bytes is not None
            else settings.analysis_cache_max_entry_bytes
        )
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, CachedAnalysis]] = {}

    def store(
        self, session_id: str, response: UnifiedAnalysisResponse, width: int, height: int
    ) -> str | None:
        """Cache a server-generated response; None when it cannot be cached."""
        if not session_id:
            return None
        try:
            approx_bytes = len(response.model_dump_json().encode("utf-8"))
        except Exception:
            return None
        if approx_bytes > self._max_entry_bytes:
            return None
        ref = f"{ANALYSIS_REF_PREFIX}{secrets.token_urlsafe(24)}"
        now = time.monotonic()
        entry = CachedAnalysis(
            response=response.model_copy(deep=True),
            width=width,
            height=height,
            stored_at=now,
            expires_at=now + self._ttl_s,
        )
        with self._lock:
            self._prune_locked()
            while len(self._entries) >= self._max_entries:
                oldest = min(
                    self._entries.items(), key=lambda kv: kv[1][1].stored_at
                )[0]
                del self._entries[oldest]
            self._entries[ref] = (session_id, entry)
        return ref

    def get(self, session_id: str | None, ref: str | None) -> CachedAnalysis | None:
        """Return the entry only for the owning live session, else None."""
        if not session_id or not ref:
            return None
        with self._lock:
            self._prune_locked()
            found = self._entries.get(ref)
            if found is None:
                return None
            owner, entry = found
            if owner != session_id or entry.expires_at <= time.monotonic():
                return None
            return entry

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [
            ref for ref, (_, entry) in self._entries.items() if entry.expires_at <= now
        ]
        for ref in expired:
            del self._entries[ref]


session_store = SessionStore()
analysis_store = AnalysisStore()
