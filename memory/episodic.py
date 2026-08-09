"""
memory/episodic.py — Episodic memory store for Copperleaf Kitchens.

Deliberately simple: an append-only list of episodes. This is the ONLY
thing the promote-or-drop router (router.py) is allowed to write to.
Semantic memory (a separate module, added in a later commit) is NEVER
written to directly by the router — semantic facts only get created by a
separate, periodic consolidation pass that reads FROM this episodic store.
That separation is a hard lab requirement, not a style choice, so it's
enforced by simply not giving this class or the router any semantic-write
method at all — there's nothing here to accidentally call.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Episode:
    content: str
    source_role: str  # role of the original turn ('user' | 'assistant' | 'tool')
    reason_promoted: str  # why the router decided to keep this
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EpisodicStore:
    """Append-only episodic memory. No update/delete on purpose — that's
    exactly the kind of mutation the consolidation layer (later commit)
    is responsible for, with explicit versioning. This store just
    accumulates raw promoted episodes."""

    def __init__(self):
        self._episodes: list[Episode] = []

    def add(self, content: str, source_role: str, reason_promoted: str) -> Episode:
        episode = Episode(content=content, source_role=source_role, reason_promoted=reason_promoted)
        self._episodes.append(episode)
        return episode

    def all(self) -> list[Episode]:
        return list(self._episodes)

    def __len__(self) -> int:
        return len(self._episodes)