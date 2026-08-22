"""
scripts/resolve_admin_task.py — TEMPORARY stand-in for the admin surface
in platform/, which doesn't exist yet. Writes the same decision a future
platform UI action would write, into the same admin_tasks table the graph
node reads from. Once platform/ exists, this script is replaced by a real
UI action; the graph-side contract (a row in admin_tasks with a decision)
does not change.

Usage: python scripts/resolve_admin_task.py <task_id> <approved|rejected> [notes]
"""
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "state_graph" / "onboarding" / "onboarding_checkpoints.db"


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/resolve_admin_task.py <task_id> <approved|rejected> [notes]")
        raise SystemExit(1)
    task_id, decision = sys.argv[1], sys.argv[2]
    if decision not in ("approved", "rejected"):
        print("decision must be 'approved' or 'rejected'")
        raise SystemExit(1)
    notes = sys.argv[3] if len(sys.argv) > 3 else ""

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT status FROM admin_tasks WHERE task_id = ?", (task_id,))
    row = cur.fetchone()
    if row is None:
        print(f"No such task_id: {task_id}")
        raise SystemExit(1)

    conn.execute(
        "UPDATE admin_tasks SET decision=?, status='resolved', notes=?, resolved_at=? WHERE task_id=?",
        (decision, notes, time.time(), task_id),
    )
    conn.commit()
    for r in conn.execute("SELECT task_id, status, decision, notes FROM admin_tasks WHERE task_id=?", (task_id,)):
        print(r)
    conn.close()


if __name__ == "__main__":
    main()