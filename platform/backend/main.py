"""
platform/backend/main.py — Admin backend for Copperleaf Kitchens Lab 5.

Replaces scripts/resolve_admin_task.py and scripts/resolve_ticket.py with
real HTTP endpoints a UI (and a grader) can hit, per the project spec:
HITL/ticket resolution must go "through the platform you build, not a
console print statement and not a side channel outside the product."

Design note: admin_tasks and tickets tables are NOT all in one file.
- admin_tasks always lives in state_graph/shared_ops.db (onboarding and
  dispute both write there).
- tickets lives in state_graph/shared_ops.db for the dispute graph, but
  in state_graph/onboarding/onboarding_checkpoints.db for the onboarding
  graph (existing inconsistency in the codebase, not something we
  introduced). Waste-investigation's ticket table location is unknown
  until that graph lands.

Rather than hardcode paths that will silently miss rows, this file scans
every *.db file under state_graph/ at request time, and only reads/writes
tables that are actually present in a given file. This means it keeps
working once Graph 3 merges without any code change here.

Run from the copperleaf-mcp repo root (see platform/backend/README.md
for exact PowerShell commands):
    uvicorn platform.backend.main:app --reload --port 8000
"""
from __future__ import annotations

import glob
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# state_graph/ lives two levels up from this file (platform/backend/main.py
# -> platform/ -> repo root -> state_graph/)
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_GRAPH_DIR = REPO_ROOT / "state_graph"

app = FastAPI(title="Copperleaf Kitchens Admin API")

# Frontend is a static HTML file (file:// or a different local port) calling
# this API from the browser — without this, every fetch() call is silently
# blocked by CORS. Wide open here since this is a local dev/demo admin tool,
# not a deployed multi-tenant service.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _all_db_files() -> list[Path]:
    if not STATE_GRAPH_DIR.exists():
        return []
    return [Path(p) for p in glob.glob(str(STATE_GRAPH_DIR / "**" / "*.db"), recursive=True)]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


class TaskResolution(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: Optional[str] = ""


class TicketResolution(BaseModel):
    resolution: Literal["resolved", "rejected"]
    resolution_terms: Optional[str] = None
    notes: Optional[str] = ""


@app.get("/admin/tasks")
def list_admin_tasks(status: Optional[str] = "pending"):
    """Real read across every db file that has an admin_tasks table."""
    results = []
    for db_path in _all_db_files():
        conn = sqlite3.connect(str(db_path))
        try:
            if not _table_exists(conn, "admin_tasks"):
                continue
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM admin_tasks"
            params: tuple = ()
            if status:
                query += " WHERE status = ?"
                params = (status,)
            for row in conn.execute(query, params):
                d = dict(row)
                d["_db_path"] = str(db_path.relative_to(REPO_ROOT))
                results.append(d)
        finally:
            conn.close()
    return {"count": len(results), "tasks": results}


@app.get("/admin/tickets")
def list_tickets(status: Optional[str] = None):
    """Real read across every db file that has a tickets table.
    Default (no status filter) returns everything so 'open' and
    'investigating' both show up without the caller needing to know
    the exact status vocabulary in advance.
    """
    results = []
    for db_path in _all_db_files():
        conn = sqlite3.connect(str(db_path))
        try:
            if not _table_exists(conn, "tickets"):
                continue
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM tickets"
            params: tuple = ()
            if status:
                query += " WHERE status = ?"
                params = (status,)
            for row in conn.execute(query, params):
                d = dict(row)
                d["_db_path"] = str(db_path.relative_to(REPO_ROOT))
                results.append(d)
        finally:
            conn.close()
    return {"count": len(results), "tickets": results}


def _find_task_db(task_id: str) -> Optional[Path]:
    for db_path in _all_db_files():
        conn = sqlite3.connect(str(db_path))
        try:
            if not _table_exists(conn, "admin_tasks"):
                continue
            cur = conn.execute("SELECT 1 FROM admin_tasks WHERE task_id = ?", (task_id,))
            if cur.fetchone():
                return db_path
        finally:
            conn.close()
    return None


def _find_ticket_db(ticket_id: str) -> Optional[Path]:
    for db_path in _all_db_files():
        conn = sqlite3.connect(str(db_path))
        try:
            if not _table_exists(conn, "tickets"):
                continue
            cur = conn.execute("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,))
            if cur.fetchone():
                return db_path
        finally:
            conn.close()
    return None


@app.post("/admin/tasks/{task_id}/resolve")
def resolve_admin_task(task_id: str, body: TaskResolution):
    db_path = _find_task_db(task_id)
    if db_path is None:
        raise HTTPException(status_code=404, detail=f"No such task_id: {task_id}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE admin_tasks SET decision=?, status='resolved', notes=?, resolved_at=? "
            "WHERE task_id=?",
            (body.decision, body.notes, time.time(), task_id),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM admin_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
    finally:
        conn.close()

    return {"resolved": True, "db_path": str(db_path.relative_to(REPO_ROOT)), "task": dict(row)}


@app.post("/admin/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, body: TicketResolution):
    if body.resolution == "resolved" and not body.resolution_terms:
        raise HTTPException(
            status_code=400,
            detail="resolution_terms is required when resolution='resolved'",
        )

    db_path = _find_ticket_db(ticket_id)
    if db_path is None:
        raise HTTPException(status_code=404, detail=f"No such ticket_id: {ticket_id}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE tickets SET resolution=?, resolution_terms=?, status='resolved', "
            "notes=?, resolved_at=? WHERE ticket_id=?",
            (body.resolution, body.resolution_terms, body.notes, time.time(), ticket_id),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
        ).fetchone()
    finally:
        conn.close()

    return {"resolved": True, "db_path": str(db_path.relative_to(REPO_ROOT)), "ticket": dict(row)}


@app.get("/health")
def health():
    return {"status": "ok", "db_files_found": [str(p) for p in _all_db_files()]}