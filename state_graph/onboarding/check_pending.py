import sqlite3

conn = sqlite3.connect("onboarding_checkpoints.db")
rows = conn.execute(
    "SELECT task_id, status, thread_id, reason FROM admin_tasks WHERE status='pending'"
).fetchall()
conn.close()

if not rows:
    print("No pending admin tasks found.")
else:
    for row in rows:
        print(row)