import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "db" / "copperleaf.db"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT order_id, item_id, quantity, status FROM supplier_orders WHERE status='delivered' LIMIT 5"
).fetchall()
conn.close()

for r in rows:
    print(dict(r))