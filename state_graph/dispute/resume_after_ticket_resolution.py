"""
state_graph/dispute/resume_after_ticket_resolution.py -- resumes the
dispute graph after a pending ticket_wait pause has been resolved via
scripts/resolve_ticket.py. Per route_after_ticket, a "resolved" ticket
routes back into investigate_discrepancy (real Gemini call) and onward
-- this is not a short resume, it re-enters two more real nodes and may
pause again at credit_approval; resolve that the same way if it does.

Usage: python resume_after_ticket_resolution.py <thread_id>
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
        print("Usage: python resume_after_ticket_resolution.py <thread_id>")
        raise SystemExit(1)
    thread_id = sys.argv[1]

    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    state_before = graph.get_state(config)
    print("Status before resume:", state_before.values.get("status"))
    print("Paused at:", state_before.next)

    print("\n=== Resuming (input=None -- reads the ticket resolution from disk) ===")
    final = graph.invoke(None, config=config)

    state_after = graph.get_state(config)
    print("\nStatus after this invoke:", final.get("status"))
    print("Subcheck results:", final.get("subcheck_results"))
    print("Chosen resolution:", final.get("chosen_resolution"))
    print("Still paused at:", state_after.next, "(empty tuple means the run finished)")