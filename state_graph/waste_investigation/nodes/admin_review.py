"""
state_graph/waste_investigation/nodes/admin_review.py — Piece 5 (HITL
node).

Any chosen corrective action from evaluate_actions touches a real
supplier relationship (renegotiate, switch, or a formal branch-practice
flag) -- the agent is never allowed to execute one alone. This node
pauses, persists full state, and only resumes once a real decision is
recorded in admin_tasks.

Shares state_graph/shared_ops.db and the admin_tasks table with
onboarding/nodes/admin_review.py and scripts/resolve_admin_task.py --
deliberately, so ONE resolution script and ONE table serve every graph's
HITL pauses, rather than each graph inventing its own admin surface
stand-in. (NOTE: onboarding's own admin_review.py currently points at a
DIFFERENT db file than resolve_admin_task.py does -- flagged to the team
as a likely pre-existing bug there. This file avoids that mismatch by
using shared_ops.db consistently, matching resolve_admin_task.py and
resolve_ticket.py's actual shared convention.)
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


def awaiting_admin_review(state: WasteInvestigationState, config: RunnableConfig) -> WasteInvestigationState:
    print("[node:awaiting_admin_review] entered", flush=True)
    thread_id = (config.get("configurable") or {})["thread_id"]
    task_id = f"waste-investigation-{thread_id}"
    reason = (
        f"Recommended action: {state['chosen_action']} for supplier_id={state['supplier_id']} "
        f"(score={max(state['candidate_scores']) if state['candidate_scores'] else 'n/a'}). "
        f"Rationale: {state['action_rationale']}"
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
            "status": "executed" if decision == "approved" else "closed",
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

    # Same defensive pattern as onboarding's admin_review.py: never trust
    # interrupt()'s return value alone -- re-read the DB after resuming,
    # and fail loudly if no real decision was recorded.
    interrupt({"task_id": task_id, "reason": reason})

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT decision, notes FROM admin_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        raise RuntimeError(
            f"awaiting_admin_review for {task_id} was resumed but no decision "
            "is recorded in admin_tasks. Do not resume this node until the "
            "task's status is 'resolved' -- check admin_tasks directly, don't "
            "resume speculatively."
        )

    decision, notes = row
    return {
        **state,
        "status": "executed" if decision == "approved" else "closed",
        "admin_decision": decision,
        "admin_notes": notes or "",
    }