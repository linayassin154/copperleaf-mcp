import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "shared_ops.db"

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute(
    "SELECT task_id, status, thread_id, reason FROM admin_tasks WHERE status='pending'"
).fetchall()
tix = conn.execute(
    "SELECT ticket_id, status, thread_id, reason FROM tickets WHERE status='open'"
).fetchall()
conn.close()

print("Pending admin tasks:")
for row in rows:
    print(" ", row)
print("\nOpen tickets:")
for row in tix:
    print(" ", row)