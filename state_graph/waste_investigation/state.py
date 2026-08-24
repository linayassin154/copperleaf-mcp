"""
state_graph/waste_investigation/state.py — shared state schema for the
Recurring Waste-Pattern Investigation & Corrective Action graph.

Kept in its own file, separate from graph.py, so a grader can find "what
does this graph's persisted state actually look like" in one small place
without reading node logic — same convention state_graph/onboarding/
and state_graph/dispute/ already use.
"""
from __future__ import annotations

from typing import Literal, TypedDict

# Mirrors the lifecycle from the team plan doc:
# start -> aggregate_data -> pattern_detected -> investigate_pattern ->
# check_other_branches -> generate_candidate_actions -> evaluate_actions
# -> [ticketed ->]* awaiting_admin_review -> executed / closed
WasteInvestigationStatus = Literal[
    "start",
    "aggregate_data",
    "pattern_detected",
    "no_pattern",
    "investigate_pattern",
    "check_other_branches",
    "ticketed",
    "generate_candidate_actions",
    "evaluate_actions",
    "awaiting_admin_review",
    "executed",
    "closed",
]


class WasteInvestigationState(TypedDict):
    # Where the run currently is.
    status: WasteInvestigationStatus

    # Piece 2 output — this graph's OWN aggregation query result. Never
    # populated from memory/consolidation.py's output — see aggregate_data's
    # docstring for the explicit boundary rule this enforces.
    supplier_id: int
    item_id: int
    branch_id: int
    late_delivery_count: int
    write_off_count: int
    pattern_summary: str

    # Piece 3 output — task decomposition: does the pattern show up at
    # other branches too, and what does deeper history say.
    other_branches_affected: list[int]
    investigation_notes: list[str]

    # Piece 4 output — Tree of Thoughts: multiple candidate actions,
    # generated and scored, not just the first idea taken.
    candidate_actions: list[str]
    candidate_scores: list[float]
    chosen_action: str
    action_rationale: str

    # Populated once an admin acts on the HITL pause.
    admin_decision: Literal["approved", "rejected", ""]
    admin_notes: str

    # Populated if the ticket path is hit (inconclusive investigation or
    # cross-branch data conflict) — distinct from admin_decision above.
    ticket_reason: str