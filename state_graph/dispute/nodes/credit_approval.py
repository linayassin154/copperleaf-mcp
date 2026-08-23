"""
state_graph/dispute/nodes/credit_approval.py — HITL node.

Shares the admin_tasks table with onboarding/nodes/admin_review.py via
state_graph/shared_ops.db -- one admin queue for the whole platform.
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


def _ensure_admin_tasks_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_tasks (
            task_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            state_snapshot TEXT,
            decision TEXT,
            notes TEXT,
            created_at REAL,
            resolved_at REAL
        )
        """
    )
    conn.commit()


def credit_approval(state: DisputeState, config: RunnableConfig) -> DisputeState:
    print("[node:credit_approval] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    task_id = f"dispute-{thread_id}"
    reason = (
        f"Proposed resolution '{state['chosen_resolution']}' for dispute "
        f"{state['dispute_id']} needs sign-off: proposed_credit="
        f"{state['proposed_credit']} — {state['resolution_rationale']}"
    )

    conn = sqlite3.connect(str(DB_PATH))
    _ensure_admin_tasks_table(conn)

    row = conn.execute(
        "SELECT decision, notes FROM admin_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()

    if row and row[0]:
        decision, notes = row
        conn.close()
        return {
            **state,
            "status": "resolved" if decision == "approved" else "rejected",
            "admin_decision": decision,
            "admin_notes": notes or "",
        }

    if not row:
        conn.execute(
            "INSERT INTO admin_tasks "
            "(task_id, thread_id, status, reason, state_snapshot, created_at) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (task_id, thread_id, reason, json.dumps(dict(state), default=str), time.time()),
        )
        conn.commit()
    conn.close()

    interrupt({"task_id": task_id, "reason": reason})

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT decision, notes FROM admin_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        raise RuntimeError(
            f"credit_approval for {task_id} was resumed but no decision is "
            "recorded in admin_tasks."
        )

    decision, notes = row
    return {
        **state,
        "status": "resolved" if decision == "approved" else "rejected",
        "admin_decision": decision,
        "admin_notes": notes or "",
    }