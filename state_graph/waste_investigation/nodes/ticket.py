"""
state_graph/waste_investigation/nodes/ticket.py — unplanned-failure path.

Distinct code path from awaiting_admin_review (HITL): HITL is an expected
pause for a decision the agent isn't allowed to make alone (approving a
chosen corrective action). A ticket is unplanned -- the investigation
produced no usable findings, or evaluate_actions couldn't find a clear
winner among the candidate actions. A grader should be able to tell the
two apart by trigger, not just by name.

Shares the tickets table with dispute/nodes/ticket.py and
onboarding/nodes/ticket.py via state_graph/shared_ops.db.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from state import WasteInvestigationState

DB_PATH = Path(__file__).resolve().parents[2] / "shared_ops.db"


def _ensure_tickets_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            reason TEXT,
            state_snapshot TEXT,
            resolution TEXT,
            resolution_terms TEXT,
            notes TEXT,
            created_at REAL,
            resolved_at REAL
        )
        """
    )
    conn.commit()


def ticket_open(state: WasteInvestigationState, config: RunnableConfig) -> WasteInvestigationState:
    print("[node:ticket_open] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    ticket_id = f"waste-investigation-{thread_id}"

    if not state.get("investigation_notes"):
        reason = (
            f"Investigation inconclusive for supplier_id={state.get('supplier_id')}: "
            "investigate_pattern produced no usable findings."
        )
    else:
        scores = state.get("candidate_scores") or []
        reason = (
            f"No clear corrective action for supplier_id={state.get('supplier_id')}: "
            f"candidate scores {scores} did not cross the confidence threshold."
        )

    conn = sqlite3.connect(str(DB_PATH))
    _ensure_tickets_table(conn)
    row = conn.execute("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO tickets "
            "(ticket_id, thread_id, status, reason, state_snapshot, created_at) "
            "VALUES (?, ?, 'open', ?, ?, ?)",
            (ticket_id, thread_id, reason, json.dumps(dict(state), default=str), time.time()),
        )
        conn.commit()
    conn.close()

    return {**state, "status": "ticketed", "ticket_reason": reason}


def ticket_wait(state: WasteInvestigationState, config: RunnableConfig) -> WasteInvestigationState:
    print("[node:ticket_wait] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    ticket_id = f"waste-investigation-{thread_id}"

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT resolution, resolution_terms FROM tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    conn.close()

    if row and row[0]:
        return _apply_resolution(state, row[0], row[1])

    interrupt({"ticket_id": ticket_id, "reason": "Awaiting ticket resolution"})

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT resolution, resolution_terms FROM tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        raise RuntimeError(
            f"ticket_wait for {ticket_id} was resumed but no resolution is recorded."
        )

    return _apply_resolution(state, row[0], row[1])


def _apply_resolution(
    state: WasteInvestigationState, resolution: str, resolution_terms: str | None
) -> WasteInvestigationState:
    if resolution == "rejected":
        return {**state, "status": "closed"}
    # "resolved" -- an admin supplied manual terms/notes to close the loop;
    # this graph doesn't re-enter evaluate_actions automatically, since a
    # human already made the call outside the agent's own scoring.
    return {
        **state,
        "status": "closed",
        "admin_notes": resolution_terms or state.get("admin_notes", ""),
    }


def route_after_ticket(state: WasteInvestigationState) -> str:
    return "end"