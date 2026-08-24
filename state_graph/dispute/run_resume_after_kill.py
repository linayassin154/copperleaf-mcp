"""
state_graph/dispute/run_resume_after_kill.py -- second half of the kill
demo. Run in a FRESH process after killing run_kill_demo.py mid
investigate_discrepancy with Ctrl+C. Same thread_id, same on-disk
checkpoint DB.
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

THREAD_ID = "dispute-crash-demo-2"

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
    print("Last persisted status before resume:", state_before.values.get("status"), flush=True)
    print("Graph's recorded 'next' node(s) before resume:", state_before.next, flush=True)

    print("=== Resuming from last checkpoint (input=None, NOT a new run) ===", flush=True)
    final = graph.invoke(None, config=config)

    print()
    print("Final status:", final["status"])
    print("Chosen resolution:", final.get("chosen_resolution"))
    print("Subcheck results:", final.get("subcheck_results"))

    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH))
    post_count = conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (THREAD_ID,)
    ).fetchone()[0]
    conn.close()
    print(f"\nCheckpoint rows for {THREAD_ID}: {pre_count} before resume -> {post_count} after")
