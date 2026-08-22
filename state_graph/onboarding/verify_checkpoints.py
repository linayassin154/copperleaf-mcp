"""
state_graph/onboarding/verify_checkpoints.py — quick, real proof that
LangGraph's checkpointer wrote actual rows to durable SQLite storage,
not just returned successfully in memory. Run directly after graph.py.
"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parent / "onboarding_checkpoints.db"
if not db_path.exists():
    raise SystemExit(f"No checkpoint file at {db_path} — run graph.py first.")

conn = sqlite3.connect(str(db_path))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", tables)

rows = conn.execute("SELECT thread_id, checkpoint_id FROM checkpoints").fetchall()
print(f"Checkpoint rows ({len(rows)}):")
for row in rows:
    print(" ", row)