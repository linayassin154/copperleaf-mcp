"""
state_graph/dispute/nodes/apply_resolution.py — the real MCP write.

Calls the actual mcp_server tool functions (write_off_inventory,
create_supplier_order) with a real Session, not a parallel
reimplementation of the write.

write_off_inventory only fires for dispute_type == "damaged": those are
units that physically arrived, entered real inventory, and are now
being removed from stock. A "short_qty" or "wrong_item" credit is a
purely financial claim against the supplier for units that never
arrived in the first place -- there's nothing in physical stock to
write off, so calling write_off_inventory on the shortfall for those
types would incorrectly try to remove inventory that was never added.
That distinction is recorded in the `disputes` table via
_mark_dispute_row regardless of dispute_type; only the MCP inventory
write is conditional on it.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.auth import Session
from mcp_server.tools import ToolError, create_supplier_order, write_off_inventory
from state import DisputeState

DISPUTES_DB_PATH = _REPO_ROOT / "db" / "copperleaf.db"

_WRITE_OFF_REASON_MAP = {
    "short_qty": "other",
    "damaged": "damaged_in_delivery",
    "wrong_item": "other",
}


def _session_for(state: DisputeState) -> Session:
    conn = sqlite3.connect(str(DISPUTES_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT staff_id, branch_id, full_name, role FROM staff WHERE staff_id = ?",
        (state["staff_id"],),
    ).fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"staff_id={state['staff_id']} not found -- cannot authorize MCP write.")
    return Session(staff_id=row["staff_id"], branch_id=row["branch_id"], full_name=row["full_name"], role=row["role"])


def apply_resolution(state: DisputeState) -> DisputeState:
    print("[node:apply_resolution] entered, resolution:", state["chosen_resolution"], flush=True)
    session = _session_for(state)
    shortfall = max(0.0, state["expected_quantity"] - state["received_quantity"])
    result_note = ""

    try:
        if state["dispute_type"] == "damaged" and state["chosen_resolution"] in ("full_credit", "partial_credit_reorder"):
            # Only "damaged" writes off real, physically received stock.
            # Uses received_quantity (what's actually sitting in
            # inventory and damaged), not the shortfall.
            wo = write_off_inventory(
                session=session,
                item_id=state["item_id"],
                quantity=state["received_quantity"],
                reason=_WRITE_OFF_REASON_MAP.get(state["dispute_type"], "other"),
            )
            result_note += f"write_off: {wo}; "
        elif state["chosen_resolution"] in ("full_credit", "partial_credit_reorder"):
            result_note += "no inventory write-off needed (short/wrong-item credit is financial only); "

        if state["chosen_resolution"] == "partial_credit_reorder":
            order = create_supplier_order(
                session=session,
                item_id=state["item_id"],
                supplier_id=state["supplier_id"],
                quantity=shortfall,
            )
            result_note += f"reorder: {order}; "

        if state["chosen_resolution"] == "replacement":
            order = create_supplier_order(
                session=session,
                item_id=state["item_id"],
                supplier_id=state["supplier_id"],
                quantity=state["expected_quantity"],
                expedited=True,
            )
            result_note += f"replacement order: {order}; "

    except ToolError as e:
        result_note = f"MCP write failed: {e}"
        _mark_dispute_row(state, status="open", resolution_type=None)
        return {**state, "status": "investigating", "mcp_write_result": result_note}

    _mark_dispute_row(state, status="resolved", resolution_type=state["chosen_resolution"])
    return {**state, "status": "resolved", "mcp_write_result": result_note}


def _mark_dispute_row(state: DisputeState, status: str, resolution_type: str | None) -> None:
    conn = sqlite3.connect(str(DISPUTES_DB_PATH))
    conn.execute(
        "UPDATE disputes SET status = ?, resolution_type = ?, proposed_credit = ?, "
        "resolved_at = CASE WHEN ? = 'resolved' THEN datetime('now') ELSE resolved_at END "
        "WHERE dispute_id = ?",
        (status, resolution_type, state.get("proposed_credit", 0), status, state["dispute_id"]),
    )
    conn.commit()
    conn.close()