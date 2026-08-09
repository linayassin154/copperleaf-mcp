"""
memory/test_consolidation.py — Proves the consolidation layer resolves a
real contradiction with versioning (not a silent overwrite), reinforces
matching facts instead of duplicating them, and only processes NEW
episodes on each periodic run. Run:

    python memory/test_consolidation.py
"""
from episodic import EpisodicStore
from semantic import SemanticStore
from consolidation import ConsolidationPass


def main() -> None:
    print("=== SEMANTIC CONSOLIDATION TEST ===\n")

    episodic_store = EpisodicStore()
    semantic_store = SemanticStore()
    consolidation = ConsolidationPass(episodic_store, semantic_store)

    # --- Round 1: early episodes say Nile Fresh was reliable ---
    episodic_store.add(
        content="Nile Fresh Produce delivery arrived on time for order #4021.",
        source_role="tool",
        reason_promoted="role='tool'",
    )
    episodic_store.add(
        content="Confirmed with front desk: Nile Fresh Produce delivered on time again this week.",
        source_role="assistant",
        reason_promoted="matched a fact-signal keyword",
    )

    print("--- Consolidation run #1 (2 new episodes) ---")
    log_1 = consolidation.run()
    for line in log_1:
        print(f"  {line}")

    fact = semantic_store.current("Nile Fresh Produce", "delivery_status")
    print(f"\nCurrent fact after run #1: value={fact.value!r}, version={fact.version}")
    assert fact.value == "on_time"
    assert fact.version == 1

    # --- Time passes. A NEW episode contradicts the earlier ones. ---
    episodic_store.add(
        content="Nile Fresh Produce delivery was 3 days late for order #4098 at branch 1.",
        source_role="assistant",
        reason_promoted="matched a fact-signal keyword",
    )

    print("\n--- Consolidation run #2 (1 new episode — the real conflict) ---")
    log_2 = consolidation.run()
    for line in log_2:
        print(f"  {line}")
    assert any("CONFLICT RESOLVED" in line for line in log_2), "expected a logged conflict resolution"

    # --- Prove the old fact was NOT silently lost ---
    full_history = semantic_store.history("Nile Fresh Produce", "delivery_status")
    print(f"\nFull versioned history ({len(full_history)} version(s)):")
    for f in full_history:
        print(f"  v{f.version}: value={f.value!r}, status={f.status!r}"
              + (f", superseded_reason={f.superseded_reason!r}" if f.superseded_reason else ""))

    assert len(full_history) == 2, "expected exactly 2 versions (old preserved, new added)"
    v1, v2 = full_history
    assert v1.status == "superseded" and v1.value == "on_time"
    assert v2.status == "active" and v2.value == "late"
    assert v1.superseded_reason is not None, "old version must carry a reason, not just vanish"

    current_now = semantic_store.current("Nile Fresh Produce", "delivery_status")
    print(f"\nCurrent fact after conflict: value={current_now.value!r}, version={current_now.version}")
    assert current_now.value == "late"

    # --- Confirm a third, empty run doesn't reprocess old episodes ---
    print("\n--- Consolidation run #3 (0 new episodes) ---")
    log_3 = consolidation.run()
    print(f"  (log entries: {len(log_3)})")
    assert len(log_3) == 0, "run #3 should not reprocess already-consolidated episodes"

    print("\nPASS: real conflict resolved via versioning, old fact preserved with a dated reason.")
    print("PASS: periodic runs only process new episodes, never re-scan the whole store.")
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()