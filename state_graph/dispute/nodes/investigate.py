"""
state_graph/dispute/nodes/investigate.py — investigate_discrepancy
(LLM addition #1: task decomposition).

Reuses planning/planning_lab/algorithms/decomposition.py's decompose_goal
directly rather than reimplementing decomposition.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from langchain_google_genai import ChatGoogleGenerativeAI

from mcp_server.db import get_connection
from planning.planning_lab.algorithms.decomposition import decompose_goal
from state import DisputeState

_TOOL_DESCRIPTIONS = (
    "- get_transaction_history(item_id): recent restock/write-off/usage "
    "history for the disputed item\n"
    "- get_prior_disputes(supplier_id): how many past disputes this "
    "supplier has had, and their outcomes\n"
)


def _get_transaction_history(item_id: int) -> str:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT change_type, quantity_change, reason, created_at "
            "FROM inventory_transactions WHERE item_id = ? "
            "ORDER BY created_at DESC LIMIT 5",
            (item_id,),
        ).fetchall()
    if not rows:
        return "no transaction history found"
    return "; ".join(
        f"{r['change_type']} {r['quantity_change']} ({r['reason']})" for r in rows
    )


def _get_prior_disputes(supplier_id: int) -> str:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.status, d.resolution_type
            FROM disputes d
            JOIN supplier_orders o ON d.order_id = o.order_id
            WHERE o.supplier_id = ?
            """,
            (supplier_id,),
        ).fetchall()
    if not rows:
        return "no prior disputes on record for this supplier"
    resolved = [r for r in rows if r["status"] == "resolved"]
    return f"{len(rows)} prior dispute(s), {len(resolved)} resolved"


_TOOL_MAP = {
    "get_transaction_history": _get_transaction_history,
    "get_prior_disputes": _get_prior_disputes,
}


def investigate_discrepancy(state: DisputeState) -> DisputeState:
    print("[node:investigate_discrepancy] entered", flush=True)
    goal = (
        f"Investigate a delivery dispute: order {state['order_id']}, "
        f"type '{state['dispute_type']}', expected quantity "
        f"{state['expected_quantity']}, received quantity "
        f"{state['received_quantity']}, item_id {state['item_id']}, "
        f"supplier_id {state['supplier_id']}. Supplier's reply: "
        f"{state['supplier_reply']!r}."
    )
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0)
    plan = decompose_goal(goal=goal, llm=llm, tool_descriptions=_TOOL_DESCRIPTIONS)

    results: list[str] = []
    for task in plan.tasks:
        if task.tool_name in _TOOL_MAP:
            fn = _TOOL_MAP[task.tool_name]
            arg = state["item_id"] if task.tool_name == "get_transaction_history" else state["supplier_id"]
            results.append(f"{task.id} ({task.instruction}): {fn(arg)}")
        else:
            results.append(f"{task.id} ({task.instruction}): [requires judgment, deferred]")

    return {
        **state,
        "status": "investigating",
        "subcheck_plan_goal": goal,
        "subcheck_results": results,
    }
