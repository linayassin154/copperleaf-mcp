"""
state_graph/waste_investigation/run_kill_demo.py -- real mid-node
kill/restart demo against the actual waste-investigation graph.

HOW TO USE (see run_resume_after_kill.py for the second half):
  1. Run: python run_kill_demo.py
  2. Watch for "[node:investigate_pattern] entered" or
     "[node:evaluate_actions] entered" -- these are the real LLM-call
     nodes. Press Ctrl+C for real, any time while one of them is running
     (a live Gemini call over the network has enough natural latency to
     interrupt by hand -- confirmed working this way in Graph 2's demo;
     no artificial sleep needed).
  3. Run run_resume_after_kill.py in a FRESH process, same thread_id.
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
from state import WasteInvestigationState

THREAD_ID = "waste-investigation-kill-demo-1"

if __name__ == "__main__":
    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": THREAD_ID}}

    initial_state: WasteInvestigationState = {
        "status": "start",
        "supplier_id": 0,
        "item_id": 0,
        "branch_id": 0,
        "other_branch_ids": [],
        "late_delivery_count": 0,
        "write_off_count": 0,
        "pattern_summary": "",
        "other_branches_affected": [],
        "investigation_notes": [],
        "candidate_actions": [],
        "candidate_scores": [],
        "chosen_action": "",
        "action_rationale": "",
        "admin_decision": "",
        "admin_notes": "",
        "ticket_reason": "",
    }

    print("=== Starting run -- aggregate_data is fast/deterministic, no LLM call ===", flush=True)
    print("=== Watch for investigate_pattern or evaluate_actions entering -- Ctrl+C during either ===", flush=True)
    final = graph.invoke(initial_state, config=config)
    print("If you see this, the run completed WITHOUT being killed -- rerun and Ctrl+C sooner.")
    print("Final status:", final["status"])