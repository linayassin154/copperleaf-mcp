"""
memory/short_term.py — Rolling short-term memory buffer + scratchpad for
the Copperleaf Kitchens agent.

Why these are two separate classes, not one:
A manager investigating "why do we keep writing off Roma Tomatoes" has a
multi-turn conversation — that's the TRANSCRIPT (ShortTermMemory). But the
agent also needs to hold a working hypothesis and sub-goal across many tool
calls within that investigation (e.g. "checking if this is a Nile Fresh
delivery problem vs a storage problem") — that's the SCRATCHPAD. If both
lived in the same buffer, pruning old transcript turns to save tokens would
also destroy the agent's current plan, which is exactly the bug this
design avoids (see lab requirement: "pruning the transcript never destroys
what the agent is actively doing").

Genuine trigger for THIS system specifically: an investigation into a
recurring write-off pattern can run long (many get_transaction_history /
get_supplier_orders calls before a conclusion), so the transcript grows
fast while the underlying goal ("is this Nile Fresh's fault?") stays fixed.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass
class Turn:
    """One entry in the rolling transcript buffer."""
    role: str  # 'user' | 'assistant' | 'tool'
    content: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ShortTermMemory:
    """Fixed-size rolling buffer of conversation turns.

    When the buffer is full and a new turn arrives, the OLDEST turn is
    evicted. Eviction does not mean the turn is necessarily forgotten —
    it's handed to `on_evict`, which the promote-or-drop router (see
    memory/router.py, added in a later commit) will use to decide whether
    the evicted turn is discarded or promoted to episodic memory. Until
    that router exists, `on_evict` defaults to a no-op so this class is
    independently usable and testable right now.
    """

    def __init__(self, max_turns: int = 12, on_evict: Optional[Callable[[Turn], None]] = None):
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self._max_turns = max_turns
        self._buffer: deque[Turn] = deque(maxlen=max_turns)
        self._on_evict = on_evict or (lambda turn: None)

    def add_turn(self, role: str, content: str) -> None:
        """Add a turn to the transcript. If the buffer is already full,
        the oldest turn is evicted and passed to on_evict BEFORE the new
        turn is added, so a router always sees the eviction happen."""
        if len(self._buffer) == self._max_turns:
            evicted = self._buffer[0]
            self._on_evict(evicted)
        self._buffer.append(Turn(role=role, content=content))

    def get_recent(self) -> list[Turn]:
        """Return the current transcript, oldest first."""
        return list(self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)


@dataclass
class Scratchpad:
    """The agent's current working state for an in-progress investigation
    — distinct from the transcript, and NEVER touched by ShortTermMemory's
    eviction. This is what survives when old transcript turns get pruned.
    """
    goal: Optional[str] = None
    hypothesis: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def set_goal(self, goal: str) -> None:
        self.goal = goal

    def set_hypothesis(self, hypothesis: str) -> None:
        self.hypothesis = hypothesis

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def clear(self) -> None:
        """Explicit reset — e.g. when an investigation concludes. This is
        the ONLY way the scratchpad empties; it never happens as a side
        effect of the transcript buffer filling up."""
        self.goal = None
        self.hypothesis = None
        self.notes = []