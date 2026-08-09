"""
context_eval/transcript.py — Generates the long-context test transcript(s)
all 4 context management strategies are evaluated against.

Scenario (adapted from the lab's own worked example to Copperleaf's
domain): early in a long investigation conversation, a critical fact is
mentioned once ("Prime Ribeye failed its temperature check at receiving").
Then 25+ turns of unrelated tool-call noise pile up (routine inventory
checks, other items, other branches) before a final question that can only
be answered correctly if the critical fact survived whatever pruning
happened in between.

Per the lab's cost note: input tokens are cheap, output tokens are
expensive/rate-limited. So this transcript leans on large REALISTIC TOOL
OUTPUT (JSON-like inventory dumps) to bury the fact, rather than trying to
generate huge amounts of model output.
"""
from dataclasses import dataclass


@dataclass
class TranscriptTurn:
    role: str  # 'user' | 'assistant' | 'tool'
    content: str
    is_critical: bool = False  # marks the one turn every strategy must preserve


# A large, realistic-looking tool result used purely as noise filler —
# mimics what get_inventory / get_transaction_history actually return.
_NOISE_TOOL_RESULT = """{{
  "branch_id": {branch}, "item_id": {item}, "item_name": "{name}",
  "current_quantity": {qty}, "unit": "kg", "reorder_threshold": 10.0,
  "last_restocked": "2026-07-{day:02d}", "unit_cost": {cost},
  "recent_transactions": [
    {{"type": "usage", "quantity": {qty2}, "date": "2026-07-{day2:02d}"}},
    {{"type": "delivery", "quantity": {qty3}, "date": "2026-07-{day3:02d}"}}
  ]
}}"""

_FILLER_ITEMS = [
    ("Yellow Onions", 12), ("Feta Cheese", 8), ("Basmati Rice", 40),
    ("Chicken Breast", 15), ("Cucumbers", 9), ("Whole Milk", 20),
    ("Salmon Fillet", 6), ("Roma Tomatoes", 4.5),
]


def build_long_context_transcript(noise_turns: int = 26) -> list[TranscriptTurn]:
    """Builds one transcript instance. `noise_turns` controls how many
    filler turns separate the critical fact from the final question —
    kept as a parameter so the test suite can run multiple lengths."""
    turns: list[TranscriptTurn] = []

    turns.append(TranscriptTurn(
        role="user",
        content="Can you check receiving logs and flag anything that might need a food-safety review this week?",
    ))
    turns.append(TranscriptTurn(
        role="assistant",
        content="Sure, let me check recent receiving records across branches.",
    ))
    turns.append(TranscriptTurn(
        role="tool",
        content=(
            "receiving_log(branch_id=1, item_id=10) -> temperature reading 6.1C at delivery"
        ),
    ))
    # THE CRITICAL FACT — mentioned once, early, in DIALOGUE (not buried
    # inside a tool JSON result). This matches the lab's own worked
    # example: the critical detail a manager needs to recall later is
    # something someone SAID, not raw tool output — which is exactly why
    # observation masking (protects dialogue, discards old tool JSON) is
    # a meaningfully different strategy from sliding window here, rather
    # than failing the same way for the same reason.
    turns.append(TranscriptTurn(
        role="assistant",
        content=(
            "Flagging this: Prime Ribeye's delivery on 2026-07-03 failed its "
            "temperature check at receiving (arrived at 6.1C, required <=2C). "
            "Not written off yet -- pending manager review."
        ),
        is_critical=True,
    ))
    turns.append(TranscriptTurn(
        role="assistant",
        content="Noted. Let me continue checking other recent activity across branches.",
    ))

    # Noise: realistic tool-output-heavy filler, cycling through items/branches.
    for i in range(noise_turns):
        item_name, base_qty = _FILLER_ITEMS[i % len(_FILLER_ITEMS)]
        branch = (i % 2) + 1
        day = (i % 28) + 1
        turns.append(TranscriptTurn(
            role="tool",
            content=_NOISE_TOOL_RESULT.format(
                branch=branch, item=(i % 12) + 1, name=item_name,
                qty=base_qty + (i * 0.3), day=day,
                qty2=round(base_qty * 0.4, 1), day2=max(1, day - 3),
                qty3=round(base_qty * 1.2, 1), day3=max(1, day - 7),
                cost=round(2.5 + (i % 5), 2),
            ),
        ))
        if i % 4 == 0:
            turns.append(TranscriptTurn(
                role="assistant",
                content=f"{item_name} at branch {branch} looks within normal range, continuing.",
            ))

    # Final question — can only be answered correctly by recalling the
    # critical fact from many turns ago.
    turns.append(TranscriptTurn(
        role="user",
        content="Based on everything so far, is there anything I should flag for a food-safety review?",
    ))

    return turns


def critical_fact_marker() -> str:
    """The exact substring used to check whether the critical fact
    survived a given pruning strategy — deterministic, no LLM needed for
    this check."""
    return "Prime Ribeye"


if __name__ == "__main__":
    t = build_long_context_transcript()
    print(f"Generated transcript: {len(t)} turns")
    print(f"Critical fact turn index: {[i for i, x in enumerate(t) if x.is_critical]}")
    print(f"Total transcript characters: {sum(len(x.content) for x in t)}")