"""
state_graph/waste_investigation/run_resume_after_kill.py -- second half
of the kill/restart demo. Run this in a FRESH process (new terminal or
new python invocation) after killing run_kill_demo.py mid-node.

Usage: python run_resume_after_kill.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[1]
for _p in (str(_THIS_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langchain_core.runnables import RunnableConfig
from graph import build_graph, CHECKPOINT_DB_PATH

THREAD_ID = "waste-investigation-kill-demo-1"

if __name__ == "__main__":
    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH))
    pre_count = conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (THREAD_ID,)
    ).fetchone()[0]
    conn.close()
    print(f"=== Fresh process. {pre_count} checkpoint row(s) already on disk for {THREAD_ID} ===", flush=True)

    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": THREAD_ID}}

    state_before = graph.get_state(config)
    print("Last persisted status before resume:", state_before.values.get("status"))
    print("Graph's recorded 'next' node(s) before resume:", state_before.next)

    print("=== Resuming from last checkpoint (input=None, NOT a new run) ===", flush=True)
    final = graph.invoke(None, config=config)

    print("\nFinal status:", final["status"])
    print("Chosen action:", final.get("chosen_action"))
    print("Investigation notes:", final.get("investigation_notes"))

    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH))
    post_count = conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (THREAD_ID,)
    ).fetchone()[0]
    conn.close()
    print(f"\nCheckpoint rows for {THREAD_ID}: {pre_count} before resume -> {post_count} after")