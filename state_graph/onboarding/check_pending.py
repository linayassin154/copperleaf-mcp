import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "shared_ops.db"

conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute(
    "SELECT task_id, status, thread_id, reason FROM admin_tasks WHERE status='pending'"
).fetchall()
conn.close()

if not rows:
    print("No pending admin tasks found.")
else:
    for row in rows:
        print(row)