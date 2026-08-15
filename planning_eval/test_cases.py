"""
planning_eval/test_cases.py — frozen test suite for the demand-spike /
expedite-order planning problem.

Per the lab's guardrail: freeze this before scoring. Don't edit case text
once run_comparison.py has been run for the comparison table — changing
cases mid-comparison invalidates the table.

Categories map directly to the four required minimums:
  - favors_decomposition_first: no mid-plan surprise, a full up-front plan
    executes fine.
  - favors_dynamic: a real mid-plan failure (expedite rejection) that only
    dynamic decomposition can react to.
  - needs_lookahead: several valid orderings/choices need to be weighed
    before committing (routes through Tree of Thoughts).
  - needs_reflexion: a single retry isn't enough; only cross-trial memory
    (carrying the first failure's lesson into a second attempt) recovers
    a workable plan.
"""

TEST_CASES = [
    # --- favors_decomposition_first: well-stocked items, no surprises ---
    {
        "id": "df-1",
        "category": "favors_decomposition_first",
        "goal": "Check current stock of Roma Tomatoes at branch 1 and report whether it's below the reorder threshold.",
    },
    {
        "id": "df-2",
        "category": "favors_decomposition_first",
        "goal": "Look up recent supplier orders for branch 1 and summarize which are still pending.",
    },
    {
        "id": "df-3",
        "category": "favors_decomposition_first",
        "goal": "Place a standard (non-expedited) order for item_id=1 (Roma Tomatoes) from supplier_id=1, quantity 10kg.",
    },

    # --- favors_dynamic: real mid-plan supplier rejection ---
    {
        "id": "dyn-1",
        "category": "favors_dynamic",
        "goal": (
            "Branch 1 has a large catering order and needs 15kg of Roma Tomatoes "
            "urgently. Expedite an order for item_id=1 from supplier_id=1. If the "
            "expedite is rejected because the supplier is at capacity, fall back "
            "to a standard order instead."
        ),
    },
    {
        "id": "dyn-2",
        "category": "favors_dynamic",
        "goal": (
            "Branch 1 needs an urgent expedited order for item_id=1 from "
            "supplier_id=1 for 8kg. If that supplier can't take an expedited "
            "order right now, place a standard order for the same item instead "
            "and note that it won't arrive as fast."
        ),
    },
    {
        "id": "dyn-3",
        "category": "favors_dynamic",
        "goal": (
            "Check whether supplier_id=1 can currently take an expedited order. "
            "If yes, expedite 5kg of item_id=1. If no, place a standard order "
            "for the same quantity and explain why the expedite wasn't possible."
        ),
    },

    # --- needs_lookahead: ranking multiple candidate choices ---
    {
        "id": "tot-1",
        "category": "needs_lookahead",
        "goal": (
            "Compare ordering item_id=1 (Roma Tomatoes) vs a standard order for "
            "a dairy item at branch 1 — rank which should be prioritized first "
            "given spoilage risk and current stock levels, then explain the choice."
        ),
    },
    {
        "id": "tot-2",
        "category": "needs_lookahead",
        "goal": (
            "Branch 1 is low on multiple items. Rank the three lowest-stock "
            "items by how urgently each needs reordering, considering current "
            "quantity relative to its reorder threshold."
        ),
    },

    # --- needs_reflexion: only cross-trial memory recovers a working plan ---
    {
        "id": "refl-1",
        "category": "needs_reflexion",
        "goal": (
            "Supplier_id=1 is already at its daily expedite capacity. Try to "
            "expedite 12kg of item_id=1 from supplier_id=1 anyway. Learn from "
            "the rejection and produce a final plan that actually succeeds."
        ),
    },
    {
        "id": "refl-2",
        "category": "needs_reflexion",
        "goal": (
            "Attempt to place an expedited order for item_id=1 from a supplier "
            "that is already over capacity for today. Use the rejection to "
            "revise your approach and commit to a plan that will actually go "
            "through."
        ),
    },
]


def cases_by_category(category: str) -> list[dict]:
    return [c for c in TEST_CASES if c["category"] == category]