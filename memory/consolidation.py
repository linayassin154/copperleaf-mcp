"""
memory/consolidation.py — Semantic memory consolidation.

This is a SEPARATE, PERIODIC pass over the episodic store — it is never
triggered at write time (i.e. never called from router.py), and the
promote-or-drop router has no reference to this module or to
SemanticStore at all. You call `ConsolidationPass.run()` on a schedule
(a cron job, a periodic task, or manually between shifts) — not on every
episode as it's created.

Extraction is deliberately simple and rule-based (keyword matching for
known suppliers + delivery-status language) rather than an LLM call —
this keeps the conflict-resolution logic itself fully deterministic and
inspectable, which is what actually matters for the lab requirement
("show a real conflict your consolidation layer resolves").
"""
from memory.episodic import EpisodicStore
from memory.semantic import SemanticStore

_KNOWN_SUPPLIERS = (
    "Nile Fresh Produce",
    "Delta Dairy Co.",
    "Coastal Seafood & Meats",
)

_ON_TIME_PHRASES = ("on time", "delivered on time", "on-time")
_LATE_PHRASES = ("late", "delayed", "days late")


class ConsolidationPass:
    def __init__(self, episodic_store: EpisodicStore, semantic_store: SemanticStore):
        self._episodic_store = episodic_store
        self._semantic_store = semantic_store
        # How many episodes we've already consolidated — periodic runs
        # only process NEW episodes since the last pass, not the whole
        # store every time.
        self._processed_count = 0

    def _extract_delivery_status(self, content: str) -> list[tuple[str, str, str]]:
        """Returns a list of (subject, attribute, value) candidate facts
        found in one episode's content. A single episode could plausibly
        mention more than one supplier, so this returns a list, not a
        single tuple."""
        content_lower = content.lower()
        facts_found = []
        for supplier in _KNOWN_SUPPLIERS:
            if supplier.lower() not in content_lower:
                continue
            is_late = any(phrase in content_lower for phrase in _LATE_PHRASES)
            is_on_time = any(phrase in content_lower for phrase in _ON_TIME_PHRASES)
            if is_late and not is_on_time:
                facts_found.append((supplier, "delivery_status", "late"))
            elif is_on_time and not is_late:
                facts_found.append((supplier, "delivery_status", "on_time"))
            # If both or neither phrase type is present, we deliberately
            # extract nothing rather than guess — a wrong fact is worse
            # than a missed one.
        return facts_found

    def run(self) -> list[str]:
        """Process every episode added since the last run. Returns a log
        of what was consolidated, for visibility."""
        all_episodes = self._episodic_store.all()
        new_episodes = all_episodes[self._processed_count:]
        log: list[str] = []

        for episode in new_episodes:
            candidate_facts = self._extract_delivery_status(episode.content)
            for subject, attribute, value in candidate_facts:
                existing = self._semantic_store.current(subject, attribute)
                fact = self._semantic_store.upsert_fact(
                    subject=subject, attribute=attribute, value=value,
                    source_episode_content=episode.content,
                )
                if existing is not None and existing.value != value:
                    log.append(
                        f"CONFLICT RESOLVED: {subject} / {attribute} "
                        f"{existing.value!r} (v{existing.version}, now superseded) "
                        f"-> {value!r} (v{fact.version}, now active)"
                    )
                elif existing is not None:
                    log.append(
                        f"REINFORCED: {subject} / {attribute} = {value!r} "
                        f"(v{fact.version}, additional supporting evidence)"
                    )
                else:
                    log.append(
                        f"NEW FACT: {subject} / {attribute} = {value!r} (v{fact.version})"
                    )

        self._processed_count = len(all_episodes)
        return log