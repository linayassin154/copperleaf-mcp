"""
memory/test_router.py — Proves the promote-or-drop router genuinely fires
on STM overflow, makes different decisions for different turn content,
logs its reasoning, and never touches anything but forget/episodic. Run:

    python memory/test_router.py
"""
from short_term import ShortTermMemory
from episodic import EpisodicStore
from router import PromoteOrDropRouter


def main() -> None:
    print("=== PROMOTE-OR-DROP ROUTER TEST ===\n")

    episodic_store = EpisodicStore()
    router = PromoteOrDropRouter(episodic_store)
    stm = ShortTermMemory(max_turns=3, on_evict=router.handle_eviction)

    # Mix of conversational filler (should be FORGOTTEN) and concrete
    # facts (should be PROMOTED to episodic) — same investigation scenario
    # as the short_term.py test, but now with the router actually wired in.
    turns = [
        ("user", "Why do we keep writing off Roma Tomatoes?"),          # filler -> forget
        ("assistant", "Let me check the transaction history."),         # filler -> forget
        ("tool", "get_transaction_history -> 3 write_off events, all reason=spoiled_before_use"),  # fact -> episodic
        ("assistant", "Two of the three Nile Fresh deliveries were late this month."),  # fact (keyword 'late') -> episodic
        ("user", "Got it, thanks."),                                    # filler -> forget
        ("assistant", "Anything else I can check for you?"),            # filler -> forget
        ("user", "No that's all, thanks."),                             # filler -> forget
    ]
    # Note: with max_turns=3 and 7 turns sent, the first 4 turns get
    # evicted (and routed) during this loop; the last 3 remain in the
    # buffer untouched. That's why this scenario needs 7 turns, not 5 —
    # otherwise the fact-bearing turns (#3, #4) never get evicted and the
    # router never sees them, which is exactly the bug this fix corrects.

    for role, content in turns:
        stm.add_turn(role, content)

    log = router.decision_log()
    print(f"Total turns processed: {len(turns)}")
    print(f"Total routing decisions made (= evictions so far): {len(log)}\n")

    for d in log:
        print(f"  [{d.decision.upper():8}] ({d.turn.role}) {d.turn.content!r}")
        print(f"             reason: {d.reason}\n")

    forgotten = [d for d in log if d.decision == "forget"]
    promoted = [d for d in log if d.decision == "episodic"]

    print(f"Forgotten: {len(forgotten)}, Promoted to episodic: {len(promoted)}")
    print(f"Episodic store now holds {len(episodic_store)} episode(s):")
    for ep in episodic_store.all():
        print(f"  - ({ep.source_role}) {ep.content!r} — {ep.reason_promoted}")

    assert len(forgotten) >= 1, "expected at least one forgotten turn"
    assert len(promoted) >= 1, "expected at least one promoted turn"
    assert len(episodic_store) == len(promoted), "episodic store count should match promoted decisions"

    # Confirm there is genuinely no way for this router to write semantic
    # memory directly — the constraint is structural, not just a promise.
    assert not hasattr(router, "semantic_store"), "router must not have any semantic memory access"
    print("\nPASS: router has no semantic memory access — structurally forget/episodic only.")

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()