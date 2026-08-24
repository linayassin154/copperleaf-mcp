"""
state_graph/dispute/run_hitl_demo.py -- drives a fresh dispute run up to
the credit_approval HITL pause, for independent verification of the
HITL path (separate from the kill/restart and ticket demos).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langgraph.types import Command
# add to the imports at the top:
from langchain_core.runnables import RunnableConfig
from graph import build_graph
from state import DisputeState

THREAD_ID = "dispute-hitl-demo-4"

if __name__ == "__main__":
    graph = build_graph()
    config: RunnableConfig = {"configurable": {"thread_id": THREAD_ID}}

    initial_state: DisputeState = {
        "dispute_id": THREAD_ID,
        "order_id": 3,  # replace with a real delivered order_id from your seed data
        "item_id": 1,
        "supplier_id": 1,
        "branch_id": 1,
        "staff_id": 1,
        "dispute_type": "short_qty",
        "status": "dispute_opened",
        "expected_quantity": 0,
        "received_quantity": 0,  # 0 received -> max shortfall -> forces HITL threshold
        "unit_cost": 0.0,
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

    print("=== Resuming with a real supplier reply -- should proceed to investigate/propose/HITL ===", flush=True)
    graph.invoke(Command(resume="We accept full responsibility for the shortfall."), config=config)

    state = graph.get_state(config)
    print("\nPaused at:", state.next)
    print("Status:", state.values.get("status"))
    print("Proposed credit:", state.values.get("proposed_credit"))
    print("Chosen resolution:", state.values.get("chosen_resolution"))