"""
state_graph/dispute/run_kill_demo.py -- real mid-node kill/restart demo
against the actual dispute graph.

HOW TO USE (see run_resume_after_kill.py for the second half):
  1. Run: python run_kill_demo.py
  2. It pauses once at awaiting_supplier_response (expected) and resumes
     itself automatically with a usable reply.
  3. Watch for the "[DEMO] sleeping ...s before decompose_goal call..."
     line printed by investigate_discrepancy. Press Ctrl+C for real,
     any time during that sleep or the LLM call right after it.
  4. Run run_resume_after_kill.py in a FRESH process, same thread_id.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DISPUTE_DEMO_SLOWDOWN_SECONDS", "4")

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[1]
for _p in (str(_THIS_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from graph import build_graph
from state import DisputeState

THREAD_ID = "dispute-crash-demo-2"

if __name__ == "__main__":
    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": THREAD_ID}}

    initial_state: DisputeState = {
        "dispute_id": "crash-demo-1",
        "order_id": 3,              # real delivered order in seed data: branch 1, supplier 2, item 3
        "item_id": 3,
        "supplier_id": 2,
        "branch_id": 1,
        "dispute_type": "short_qty",
        "status": "dispute_opened",
        "received_quantity": 3,     # set below expected_quantity so shortfall > 0
        "expected_quantity": 5,
        "unit_cost": 10.0,
        "supplier_reply": "",
        "reply_round": 0,
        "subcheck_plan_goal": "",
        "subcheck_results": [],
        "candidate_resolutions": [],
        "chosen_resolution": "",
        "resolution_rationale": "",
        "proposed_credit": 0.0,
        "admin_decision": "",
        "admin_notes": "",
        "mcp_write_result": "",
        "intake_error": "",
    }

    print("=== Starting run, pausing at awaiting_supplier_response ===", flush=True)
    graph.invoke(initial_state, config=config)
    time.sleep(1)

    print("=== Resuming with a real supplier reply -- watch for the DEMO sleep line ===", flush=True)
    final = graph.invoke(Command(resume="We accept the shortfall, please proceed."), config=config)
    print("If you see this, the run completed WITHOUT being killed -- rerun and Ctrl+C sooner.")
    print("Final status:", final["status"])