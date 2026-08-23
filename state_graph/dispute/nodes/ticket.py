"""
state_graph/dispute/nodes/ticket.py — unplanned-failure path.

Shares the tickets table with onboarding/nodes/ticket.py via
state_graph/shared_ops.db.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from state import DisputeState

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


def ticket_open(state: DisputeState, config: RunnableConfig) -> DisputeState:
    print("[node:ticket_open] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    ticket_id = f"dispute-{thread_id}"

    if state.get("intake_error"):
        reason = f"Dispute intake failed for {state['dispute_id']}: {state['intake_error']}"
    elif not (state.get("supplier_reply") or "").strip():
        reason = (
            f"No usable supplier reply for dispute {state['dispute_id']} "
            f"after {state['reply_round']} round(s) -- order {state['order_id']}."
        )
    else:
        reason = (
            f"Supplier reply round cap ({state['reply_round']}) exceeded for "
            f"dispute {state['dispute_id']} with no resolution reached."
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

    return {**state, "status": "ticketed"}


def ticket_wait(state: DisputeState, config: RunnableConfig) -> DisputeState:
    print("[node:ticket_wait] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    ticket_id = f"dispute-{thread_id}"

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


def _apply_resolution(state: DisputeState, resolution: str, resolution_terms: str | None) -> DisputeState:
    if resolution == "rejected":
        return {**state, "status": "rejected", "admin_decision": "rejected"}
    return {
        **state,
        "status": "investigating",
        "supplier_reply": resolution_terms or state.get("supplier_reply", ""),
    }


def route_after_ticket(state: DisputeState) -> str:
    return "end" if state["status"] == "rejected" else "investigate_discrepancy"