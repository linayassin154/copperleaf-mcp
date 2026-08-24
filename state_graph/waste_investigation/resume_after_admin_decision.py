"""
state_graph/waste_investigation/resume_after_admin_decision.py -- resumes
the waste-investigation graph after a pending awaiting_admin_review task
has been resolved via scripts/resolve_admin_task.py.

Usage: python resume_after_admin_decision.py <thread_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[1]
for _p in (str(_THIS_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langchain_core.runnables import RunnableConfig
from graph import build_graph

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python resume_after_admin_decision.py <thread_id>")
        raise SystemExit(1)

    thread_id = sys.argv[1]
    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    state_before = graph.get_state(config)
    print("Status before resume:", state_before.values.get("status"))
    print("Paused at:", state_before.next)

    print("\n=== Resuming (input=None -- reads the admin_tasks decision from disk) ===")
    final = graph.invoke(None, config=config)

    print("\nFinal status:", final["status"])
    print("Admin decision:", final.get("admin_decision"))
    print("Admin notes:", final.get("admin_notes"))
    print("Chosen action:", final.get("chosen_action"))