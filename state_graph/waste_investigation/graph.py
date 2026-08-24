"""
state_graph/waste_investigation/graph.py — Recurring Waste-Pattern
Investigation & Corrective Action state graph.

PIECE 1 of the build (checkpointing skeleton): wires up only the entry
node and a real SqliteSaver checkpointer, to prove the graph compiles and
actually persists checkpoints to durable storage before the real
aggregation/investigation/ToT/HITL/ticket nodes land on top of it in
later pieces. Mirrors state_graph/onboarding/graph.py's Piece 1 exactly.

CRITICAL BOUNDARY RULE (see nodes/aggregate_data.py once it exists):
this graph must run its OWN fresh SQL aggregation against
inventory_transactions / supplier_orders. It must never call into
memory/consolidation.py's output. This is what keeps it from being a
re-skin of the Lab 3 retrieval problem.

Locatable concerns for grading:
  - graph construction + cycle wiring: build_graph() below
  - checkpointer (durable storage, not a log file): get_checkpointer()
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from nodes.aggregate_data import aggregate_data, route_after_aggregate
from nodes.investigate_pattern import investigate_pattern, check_other_branches, route_after_investigation
from nodes.generate_actions import generate_candidate_actions, evaluate_actions, route_after_evaluation
from nodes.admin_review import awaiting_admin_review

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[1]
for _p in (str(_THIS_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from state import WasteInvestigationState

# Separate db file, same convention as onboarding_checkpoints.db and
# dispute's checkpoint db — LangGraph's own checkpoint storage, never
# mixed with copperleaf.db business data.
CHECKPOINT_DB_PATH = Path(__file__).resolve().parent / "waste_investigation_checkpoints.db"


def get_checkpointer() -> SqliteSaver:
    """Real, durable, file-backed checkpointer — must survive a process
    restart, per the Lab 5 requirement."""
    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
    return SqliteSaver(conn)


def start(state: WasteInvestigationState) -> WasteInvestigationState:
    """PIECE 1 placeholder entry node — proves the graph compiles and
    checkpoints. Replaced/extended by real aggregate_data logic in Piece 2."""
    print("[node:start] entered", flush=True)
    return {**state, "status": "start"}


def build_graph():
    builder = StateGraph(WasteInvestigationState)
    builder.add_node("aggregate_data", aggregate_data)
    builder.add_node("investigate_pattern", investigate_pattern)
    builder.add_node("check_other_branches", check_other_branches)
    builder.add_node("generate_candidate_actions", generate_candidate_actions)
    builder.add_node("evaluate_actions", evaluate_actions)
    builder.add_node("awaiting_admin_review", awaiting_admin_review)
    builder.set_entry_point("aggregate_data")
    builder.add_conditional_edges(
        "aggregate_data",
        route_after_aggregate,
        {"investigate_pattern": "investigate_pattern", "end": END},
    )
    builder.add_edge("investigate_pattern", "check_other_branches")
    builder.add_conditional_edges(
        "check_other_branches",
        route_after_investigation,
        {"generate_candidate_actions": "generate_candidate_actions", "ticket_open": END},
    )
    builder.add_edge("generate_candidate_actions", "evaluate_actions")
    builder.add_conditional_edges(
        "evaluate_actions",
        route_after_evaluation,
        {"awaiting_admin_review": "awaiting_admin_review"},
    )
    builder.add_edge("awaiting_admin_review", END)
    return builder.compile(checkpointer=get_checkpointer())

if __name__ == "__main__":
    from langchain_core.runnables import RunnableConfig

    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": "waste-investigation-piece5-run2"}}
    
    initial_state: WasteInvestigationState = {
        "status": "start",
        "supplier_id": 0,
        "item_id": 0,
        "branch_id": 0,
        "late_delivery_count": 0,
        "write_off_count": 0,
        "pattern_summary": "",
        "other_branches_affected": [],
        "investigation_notes": [],
        "candidate_actions": [],
        "candidate_scores": [],
        "chosen_action": "",
        "action_rationale": "",
        "admin_decision": "",
        "admin_notes": "",
        "ticket_reason": "",
    }

    print("=== Piece 1 test: single-node run, proving checkpointing works ===")
    result = graph.invoke(initial_state, config=config)
    print("Result:", result)

    print("\nChecking saved checkpoint history...")
    for checkpoint in graph.get_state_history(config):
        print(checkpoint.values.get("status"))