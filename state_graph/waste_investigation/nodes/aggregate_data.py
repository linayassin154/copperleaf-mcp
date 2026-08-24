"""
state_graph/waste_investigation/nodes/aggregate_data.py — Piece 2:
aggregate_data + pattern_detected.

CRITICAL BOUNDARY RULE: this node runs its OWN fresh SQL aggregation
against inventory_transactions joined to inventory_items, grouped by
supplier_id. It never reads memory/consolidation.py's output, imports
anything from memory/, or relies on any prior "already noticed" signal.
This is what keeps this graph from being a re-skin of the Lab 3
retrieval/memory problem — the pattern is detected here, fresh, every run.

Threshold rationale: >=2 write-offs for the same supplier across ANY of
their items (not just one item) is what actually indicates a supplier-
level problem worth investigating, as opposed to one bad batch of a
single item. Confirmed against real seed data: supplier_id=2 has 2
write-offs (Whole Milk, item 3; Feta Cheese, item 7) -- a real,
demonstrable pattern, not a threshold picked to look reasonable on paper.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.db import get_connection
from state import WasteInvestigationState

WRITE_OFF_PATTERN_THRESHOLD = 2


def aggregate_data(state: WasteInvestigationState) -> WasteInvestigationState:
    """Own fresh aggregation query: count write-offs per supplier, across
    all their items, and flag the supplier with the most if it crosses
    the threshold. This is the ONLY place this graph looks at raw
    transaction history -- later nodes work from this node's output, not
    from a second independent query."""
    print("[node:aggregate_data] entered", flush=True)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                ii.supplier_id,
                COUNT(*) AS write_off_count,
                GROUP_CONCAT(DISTINCT ii.item_id) AS item_ids,
                GROUP_CONCAT(DISTINCT ii.branch_id) AS branch_ids
            FROM inventory_transactions it
            JOIN inventory_items ii ON ii.item_id = it.item_id
            WHERE it.change_type = 'write_off'
            GROUP BY ii.supplier_id
            ORDER BY write_off_count DESC
            """
        ).fetchall()

    if not rows or rows[0]["write_off_count"] < WRITE_OFF_PATTERN_THRESHOLD:
        print("[node:aggregate_data] no supplier crosses the pattern threshold", flush=True)
        return {**state, "status": "no_pattern", "pattern_summary": ""}

    top = rows[0]
    supplier_id = top["supplier_id"]
    write_off_count = top["write_off_count"]
    item_ids = [int(x) for x in top["item_ids"].split(",")]
    branch_ids = [int(x) for x in top["branch_ids"].split(",")]

    summary = (
        f"supplier_id={supplier_id} has {write_off_count} write-offs across "
        f"item_id(s) {item_ids}, affecting branch_id(s) {branch_ids}."
    )
    print(f"[node:aggregate_data] pattern found: {summary}", flush=True)

    return {
        **state,
        "status": "pattern_detected",
        "supplier_id": supplier_id,
        "item_id": item_ids[0],
        "branch_id": branch_ids[0],
        "other_branch_ids": branch_ids,
        "write_off_count": write_off_count,
        "pattern_summary": summary,
    }


def route_after_aggregate(state: WasteInvestigationState) -> str:
    return "investigate_pattern" if state["status"] == "pattern_detected" else "end"
