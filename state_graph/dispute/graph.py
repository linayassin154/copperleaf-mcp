"""
state_graph/dispute/graph.py — wires the Delivery Dispute & Credit
Resolution graph together.

Mirrors state_graph/onboarding/graph.py's structure exactly: a
SqliteSaver checkpointer pointed at this graph's own checkpoint file
(dispute_checkpoints.db — separate from shared_ops.db, which only holds
the admin_tasks/tickets queues), so every meaningful transition is
persisted to durable storage, not just the end of a run.

Real cycle: awaiting_supplier_response can route back to itself
(route_after_reply) on a partial/counter offer -- not just a straight
line like onboarding's flow.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from nodes.apply_resolution import apply_resolution
from nodes.credit_approval import credit_approval
from nodes.intake import (
    awaiting_supplier_response,
    dispute_opened,
    route_after_intake,
    route_after_reply,
)
from nodes.investigate import investigate_discrepancy
from nodes.propose import propose_resolution, route_after_propose
from nodes.ticket import route_after_ticket, ticket_open, ticket_wait
from state import DisputeState

CHECKPOINT_DB_PATH = _THIS_DIR / "dispute_checkpoints.db"


def build_graph():
    builder = StateGraph(DisputeState)

    builder.add_node("dispute_opened", dispute_opened)
    builder.add_node("awaiting_supplier_response", awaiting_supplier_response)
    builder.add_node("investigate_discrepancy", investigate_discrepancy)
    builder.add_node("propose_resolution", propose_resolution)
    builder.add_node("credit_approval", credit_approval)
    builder.add_node("apply_resolution", apply_resolution)
    builder.add_node("ticket_open", ticket_open)
    builder.add_node("ticket_wait", ticket_wait)

    builder.set_entry_point("dispute_opened")

    builder.add_conditional_edges(
        "dispute_opened",
        route_after_intake,
        {
            "ticket_open": "ticket_open",
            "awaiting_supplier_response": "awaiting_supplier_response",
        },
    )

    builder.add_conditional_edges(
        "awaiting_supplier_response",
        route_after_reply,
        {
            "awaiting_supplier_response": "awaiting_supplier_response",  # genuine self-loop
            "investigate_discrepancy": "investigate_discrepancy",
            "ticket_open": "ticket_open",
        },
    )

    builder.add_edge("investigate_discrepancy", "propose_resolution")

    builder.add_conditional_edges(
        "propose_resolution",
        route_after_propose,
        {
            "credit_approval": "credit_approval",
            "apply_resolution": "apply_resolution",
        },
    )

    builder.add_edge("credit_approval", "apply_resolution")

    builder.add_edge("ticket_open", "ticket_wait")
    builder.add_conditional_edges(
        "ticket_wait",
        route_after_ticket,
        {
            "investigate_discrepancy": "investigate_discrepancy",
            "end": END,
        },
    )

    builder.add_edge("apply_resolution", END)

    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return builder.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    # Smoke test: just confirm the graph compiles and prints its node list.
    graph = build_graph()
    print("Dispute graph compiled. Nodes:", list(graph.get_graph().nodes.keys()))