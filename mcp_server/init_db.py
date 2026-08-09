"""
init_db.py — Builds copperleaf.db from schema.sql + seed.sql.

Run once before starting the server (or any time you want a clean reset):
    python mcp_server/init_db.py

This is intentionally separate from db.py: db.py only ever OPENS the
database and expects it to already exist. Nothing in the server itself
creates or seeds tables — that's a deliberate separation, so "how does the
demo data get there" is one obvious file, not folded into server startup.
"""
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent.parent / "db"
DB_PATH = DB_DIR / "copperleaf.db"
SCHEMA_PATH = DB_DIR / "schema.sql"
SEED_PATH = DB_DIR / "seed.sql"


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # encoding="utf-8-sig" strips a UTF-8 byte-order-mark if one is
        # present at the start of the file. Some Windows editors/terminals
        # (notably PowerShell's `Set-Content -Encoding utf8`) silently add
        # a BOM. Python's own .py file loader tolerates that automatically,
        # but sqlite3.executescript() does not — a leading BOM shows up as
        # a literal "near "ï»¿": syntax error" on the first statement.
        # utf-8-sig reads correctly whether a BOM is present or not, so
        # this works regardless of which editor/OS saved these files.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
        conn.executescript(SEED_PATH.read_text(encoding="utf-8-sig"))
        conn.commit()
        print(f"Built {DB_PATH} from schema.sql + seed.sql")
    finally:
        conn.close()

if __name__ == "__main__":
    build()