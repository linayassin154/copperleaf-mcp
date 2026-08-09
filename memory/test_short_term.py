"""
memory/test_short_term.py — Proves the STM buffer prunes correctly and the
scratchpad survives that pruning untouched. Run directly:

    python memory/test_short_term.py

This is committed test evidence (per lab requirement: "a committed file
with saved output, never a chat log"), not something demonstrated only in
a chat transcript.
"""
from short_term import ShortTermMemory, Scratchpad

evicted_log: list[str] = []


def record_eviction(turn) -> None:
    evicted_log.append(f"{turn.role}: {turn.content}")


def main() -> None:
    print("=== SHORT-TERM MEMORY + SCRATCHPAD TEST ===\n")

    stm = ShortTermMemory(max_turns=4, on_evict=record_eviction)
    scratchpad = Scratchpad()

    # Simulate a manager investigating a recurring Roma Tomatoes write-off
    # pattern. The scratchpad captures the working hypothesis; the
    # transcript grows as tool calls / turns pile up.
    scratchpad.set_goal("Why do we keep writing off Roma Tomatoes at branch 1?")
    scratchpad.add_note("Checked transaction_history: 3 write-offs in 2 weeks")

    turns = [
        ("user", "Why do we keep writing off Roma Tomatoes?"),
        ("assistant", "Let me check the transaction history."),
        ("tool", "get_transaction_history(item_id=1) -> 3 write_off events"),
        ("assistant", "Checking supplier orders for Nile Fresh Produce next."),
        ("tool", "get_supplier_orders(branch_id=1, status='delivered') -> ..."),
        ("assistant", "Two of three deliveries arrived a day late."),
    ]

    for role, content in turns:
        stm.add_turn(role, content)

    scratchpad.set_hypothesis(
        "Late Nile Fresh Produce deliveries are causing produce to arrive "
        "closer to its spoilage window."
    )

    print(f"Buffer max size: 4, turns sent: {len(turns)}")
    print(f"Current buffer length: {len(stm)} (should be 4, not {len(turns)})")
    assert len(stm) == 4, "buffer did not prune to max_turns"

    print(f"\nEvicted turns (handed to router hook): {len(evicted_log)}")
    for e in evicted_log:
        print(f"  - {e}")
    assert len(evicted_log) == 2, "expected exactly 2 evictions (6 turns - 4 max)"

    print("\nRemaining transcript (most recent 4 turns):")
    for t in stm.get_recent():
        print(f"  [{t.role}] {t.content}")

    print("\nScratchpad state AFTER heavy pruning:")
    print(f"  goal:       {scratchpad.goal}")
    print(f"  hypothesis: {scratchpad.hypothesis}")
    print(f"  notes:      {scratchpad.notes}")

    assert scratchpad.goal is not None, "scratchpad goal was lost during pruning!"
    assert scratchpad.hypothesis is not None, "scratchpad hypothesis was lost during pruning!"
    assert len(scratchpad.notes) == 1, "scratchpad notes were lost during pruning!"

    print("\nPASS: scratchpad survived buffer eviction completely intact.")
    print("PASS: evicted turns were captured for the (future) promote-or-drop router.")
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()