"""
state_graph/onboarding/resume_after_ticket_resolution.py -- resumes the
onboarding graph after a pending ticket_wait pause has been resolved via
scripts/resolve_ticket.py. Note: per route_after_ticket in nodes/ticket.py,
a 'resolved' ticket routes back into policy_check (real Gemini calls) and
then into another awaiting_admin_review pause -- this is not a short
resume, it re-enters two more real nodes. If it pauses again, that's
expected; resolve the new admin_tasks entry the same way as before.

Usage: python resume_after_ticket_resolution.py <thread_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

_ONBOARDING_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ONBOARDING_DIR.parents[1]
for _p in (str(_ONBOARDING_DIR), str(_REPO_ROOT)):
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
    print("Extracted terms:", final.get("extracted_terms"))
    print("Policy conflicts:", final.get("policy_conflicts"))
    print("Still paused at:", state_after.next, "(empty tuple means the run finished)")