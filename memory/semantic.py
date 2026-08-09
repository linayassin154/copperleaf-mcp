"""
memory/semantic.py — Semantic memory store for Copperleaf Kitchens.

A semantic fact is something durable derived FROM episodic memory — e.g.
"Nile Fresh Produce's delivery reliability at branch 1". Critically, this
store is NEVER written to by the promote-or-drop router (router.py) — only
the consolidation layer (consolidation.py) writes here, and only via a
separate, periodic pass. That separation is enforced structurally: this
module has no dependency on router.py at all.

Every fact is versioned. When a new episode implies a different value for
the same (subject, attribute) pair, the OLD version is marked superseded
(with a timestamp and a reason) rather than deleted or overwritten — so a
manager can see "this used to be true, then changed" instead of the
history silently disappearing. This is the lab's explicit requirement:
contradictions must be resolved with a visible, dated trace, never a
silent overwrite.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SemanticFact:
    subject: str        # e.g. "Nile Fresh Produce" (a supplier)
    attribute: str       # e.g. "delivery_reliability_branch_1"
    value: str           # e.g. "reliable" | "unreliable"
    version: int
    status: str = "active"  # 'active' | 'superseded' | 'expired'
    superseded_by_version: Optional[int] = None
    superseded_reason: Optional[str] = None
    source_episode_contents: list[str] = field(default_factory=list)
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: Optional[str] = None


class SemanticStore:
    """Keyed by (subject, attribute) -> list of SemanticFact versions,
    oldest first. `current()` returns the latest active version."""

    def __init__(self):
        # (subject, attribute) -> list[SemanticFact], append-only per key
        self._facts: dict[tuple[str, str], list[SemanticFact]] = {}

    def upsert_fact(
        self,
        subject: str,
        attribute: str,
        value: str,
        source_episode_content: str,
        ttl_days: Optional[int] = None,
    ) -> SemanticFact:
        """Add a new fact version. If a current active version already
        exists with a DIFFERENT value, this is a genuine conflict: the old
        version is marked superseded (kept, not deleted) and a new active
        version is created. If the value is the SAME, the existing
        version's source list just gets the new corroborating episode
        appended (reinforcement, not a new version)."""
        key = (subject, attribute)
        history = self._facts.setdefault(key, [])
        current = self._current_locked(history)

        expires_at = None
        if ttl_days is not None:
            # Stored as an ISO string offset conceptually; kept simple by
            # storing the ttl_days directly on the fact via expires_at as
            # a marker the test/demo advances manually (no real clock
            # dependency needed for a lab demo).
            expires_at = f"+{ttl_days}d"

        if current is None:
            # First fact ever recorded for this (subject, attribute).
            new_fact = SemanticFact(
                subject=subject, attribute=attribute, value=value,
                version=1, source_episode_contents=[source_episode_content],
                expires_at=expires_at,
            )
            history.append(new_fact)
            return new_fact

        if current.value == value:
            # Reinforces the existing fact rather than creating a new
            # version — this isn't a conflict, it's corroborating evidence.
            current.source_episode_contents.append(source_episode_content)
            return current

        # Genuine conflict: same (subject, attribute), different value.
        current.status = "superseded"
        current.superseded_by_version = current.version + 1
        current.superseded_reason = (
            f"New episode contradicts prior value "
            f"({current.value!r} -> {value!r}): {source_episode_content!r}"
        )
        new_fact = SemanticFact(
            subject=subject, attribute=attribute, value=value,
            version=current.version + 1,
            source_episode_contents=[source_episode_content],
            expires_at=expires_at,
        )
        history.append(new_fact)
        return new_fact

    def _current_locked(self, history: list[SemanticFact]) -> Optional[SemanticFact]:
        for fact in reversed(history):
            if fact.status == "active":
                return fact
        return None

    def current(self, subject: str, attribute: str) -> Optional[SemanticFact]:
        return self._current_locked(self._facts.get((subject, attribute), []))

    def history(self, subject: str, attribute: str) -> list[SemanticFact]:
        """Full versioned history — this is what proves nothing was
        silently lost when a conflict was resolved."""
        return list(self._facts.get((subject, attribute), []))

    def expire(self, subject: str, attribute: str, version: int, reason: str) -> None:
        """Explicitly mark a specific version expired (e.g. it's gone
        stale). Kept in history, just no longer 'active'."""
        for fact in self._facts.get((subject, attribute), []):
            if fact.version == version and fact.status == "active":
                fact.status = "expired"
                fact.superseded_reason = reason