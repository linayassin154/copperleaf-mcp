"""
scripts/resolve_ticket.py — TEMPORARY stand-in for the admin surface's
ticket-resolution action, until platform/ exists. Mirrors
resolve_admin_task.py exactly, but writes into the `tickets` table
instead of `admin_tasks` — same "different table = different code path"
separation nodes/ticket.py documents.

Usage:
  python scripts/resolve_ticket.py <ticket_id> resolved "term1, term2" [notes]
  python scripts/resolve_ticket.py <ticket_id> rejected [notes]
"""
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "state_graph" / "shared_ops.db"
def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python scripts/resolve_ticket.py <ticket_id> resolved \"term1, term2\" [notes]\n"
            "  python scripts/resolve_ticket.py <ticket_id> rejected [notes]"
        )
        raise SystemExit(1)

    ticket_id, resolution = sys.argv[1], sys.argv[2]
    if resolution not in ("resolved", "rejected"):
        print("resolution must be 'resolved' or 'rejected'")
        raise SystemExit(1)

    if resolution == "resolved":
        if len(sys.argv) < 4:
            print("resolved requires a comma-separated terms string, e.g. \"Delivery window: 3 days\"")
            raise SystemExit(1)
        resolution_terms = sys.argv[3]
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
    else:
        resolution_terms = None
        notes = sys.argv[3] if len(sys.argv) > 3 else ""

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row = cur.fetchone()
    if row is None:
        print(f"No such ticket_id: {ticket_id}")
        raise SystemExit(1)

    conn.execute(
        "UPDATE tickets SET resolution=?, resolution_terms=?, status='resolved', "
        "notes=?, resolved_at=? WHERE ticket_id=?",
        (resolution, resolution_terms, notes, time.time(), ticket_id),
    )
    conn.commit()
    for r in conn.execute(
        "SELECT ticket_id, status, resolution, resolution_terms, notes FROM tickets WHERE ticket_id=?",
        (ticket_id,),
    ):
        print(r)
    conn.close()


if __name__ == "__main__":
    main()