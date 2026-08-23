"""
state_graph/onboarding/run_resume_after_kill.py -- Piece 6, second half.

Run this in a FRESH process (new `python run_resume_after_kill.py`
invocation) after killing run_kill_demo.py mid policy_check with Ctrl+C.
Same thread_id, same on-disk checkpoint DB -- nothing carried over from
the killed process's memory.

`graph.invoke(None, config=config)` with input=None means "resume from
the last checkpoint", not "start a new run" -- this is the actual
mechanism being demonstrated, same as the toy script in
state_graph/checkpointing/resume_checkpoint.py, but against the real
three-LLM-call onboarding graph instead of a 3-node toy example.

What to check in the printed output after running this:
  - No [node:documents_requested], [node:awaiting_documents] "entered",
    or [node:intake_triage] "entered" lines should print again -- those
    steps were already checkpointed as complete and are not re-run.
  - [node:policy_check] SHOULD print "entered" again and re-run its
    per-term loop starting from term 1/N -- this is expected (see
    run_kill_demo.py's docstring for why), not a bug.
  - Final status should still reach "approved" or "rejected" via a real
    live Gemini call in this fresh process.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ONBOARDING_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ONBOARDING_DIR.parents[1]
for _p in (str(_ONBOARDING_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langchain_core.runnables import RunnableConfig

from graph import build_graph, CHECKPOINT_DB_PATH

THREAD_ID = "onboarding-crash-demo-1"

if __name__ == "__main__":
    # Proof this is genuinely a fresh process reading durable storage,
    # not anything held over in memory: show the checkpoint row count
    # BEFORE touching the graph object at all.
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
    print("Triage decision:", final.get("triage_decision"), "| reason:", final.get("triage_reason"))
    print("Extracted terms:", final["extracted_terms"])
    print("Policy conflicts:", final["policy_conflicts"])

    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH))
    post_count = conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (THREAD_ID,)
    ).fetchone()[0]
    conn.close()
    print(f"\nCheckpoint rows for {THREAD_ID}: {pre_count} before resume -> {post_count} after")