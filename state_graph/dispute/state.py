"""
state_graph/dispute/state.py — shared state schema for the Delivery
Dispute & Credit Resolution graph.

Kept in its own file, separate from graph.py, so a grader can see "what
does this graph's persisted state actually look like" in one small place
without reading node logic.

Real lifecycle, backed by the `disputes` table in db/schema.sql:
dispute_opened -> awaiting_supplier_response (genuine external interrupt,
can loop back to itself on a partial counter-offer) -> [ticketed ->]*
investigating -> proposing_resolution -> [awaiting_credit_approval ->]
resolved / rejected.

"ticketed" is its own value, not folded into "rejected" -- a platform
reading persisted state mid-pause needs to tell "waiting on a ticket"
apart from "waiting on an admin credit sign-off" (awaiting_credit_approval)
without a side lookup.
"""
from __future__ import annotations

from typing import Literal, TypedDict

DisputeStatus = Literal[
    "dispute_opened",
    "awaiting_supplier_response",
    "ticketed",
    "investigating",
    "proposing_resolution",
    "awaiting_credit_approval",
    "resolved",
    "rejected",
]


class DisputeState(TypedDict):
    # Identity of the real order this dispute is against. Looked up from
    # supplier_orders / inventory_items in nodes/intake.py -- never
    # asserted by the model.
    dispute_id: str
    order_id: int
    branch_id: int
    staff_id: int
    dispute_type: Literal["short_qty", "damaged", "wrong_item"]

    status: DisputeStatus

    # Ground-truth pulled from supplier_orders + inventory_items.
    item_id: int
    supplier_id: int
    expected_quantity: float
    received_quantity: float
    unit_cost: float

    # Supplier's reply text and how many wait/reply cycles have happened.
    # Bounded (see nodes/intake.py's MAX_REPLY_ROUNDS) so the genuine
    # self-loop on awaiting_supplier_response can't spin forever without
    # ever reaching the ticket path.
    supplier_reply: str
    reply_round: int

    # Populated by the task-decomposition node (investigate_discrepancy,
    # LLM addition #1). Each entry is one grounded sub-check's result.
    subcheck_plan_goal: str
    subcheck_results: list[str]

    # Populated by the Tree-of-Thoughts node (propose_resolution,
    # LLM addition #2).
    candidate_resolutions: list[str]
    chosen_resolution: Literal[
        "full_credit", "partial_credit_reorder", "replacement", "reject", ""
    ]
    resolution_rationale: str
    proposed_credit: float

    # Populated once an admin acts on the HITL pause (credit_approval.py).
    admin_decision: Literal["approved", "rejected", ""]
    admin_notes: str

    # Populated by apply_resolution.py after the real MCP write.
    mcp_write_result: str

    # Set by nodes/intake.py's dispute_opened if the order_id doesn't
    # resolve to a real, delivered supplier_orders row -- a genuine,
    # unplanned failure caught right at intake rather than crashing the
    # process. "" when intake succeeded normally.
    intake_error: str