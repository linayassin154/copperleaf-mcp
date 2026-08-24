"""
state_graph/dispute/run_ticket_demo.py -- reproducible driver for
verifying the ticket path. Run multiple times as separate `python`
process invocations, not a pytest file.

Usage: python run_ticket_demo.py <thread_id>

First run (fresh thread_id): starts a new dispute and resumes it with an
EMPTY supplier reply, three times (MAX_REPLY_ROUNDS), so route_after_reply
legitimately routes to ticket_open. Prints the ticket_id to resolve.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command  # noqa: E402

from graph import build_graph  # noqa: E402
from state import DisputeState  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_ticket_demo.py <thread_id>")
        raise SystemExit(1)
    thread_id = sys.argv[1]
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    graph = build_graph()

    state = graph.get_state(config)

    if not state.values:
        print(f"=== Fresh run, thread_id={thread_id} ===")
        initial_state: DisputeState = {
            "dispute_id": thread_id,
            "order_id": 3,          # replace with a real delivered order_id
            "item_id": 1,
            "supplier_id": 1,
            "branch_id": 1,
            "staff_id": 1,
            "dispute_type": "short_qty",
            "status": "dispute_opened",
            "expected_quantity": 5,
            "received_quantity": 3,
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
        graph.invoke(initial_state, config=config)

        # Drive empty replies until reply_round exceeds the cap -> ticket
        for _ in range(4):
            state = graph.get_state(config)
            if state.next == ("ticket_open",) or state.next == ("ticket_wait",):
                break
            graph.invoke(Command(resume=""), config=config)

        state = graph.get_state(config)
        print("Paused at:", state.next)
        print("Persisted status:", state.values.get("status"))
        return

    print(f"=== Re-invoking existing thread_id={thread_id} ===")
    print("Current persisted status:", state.values.get("status"))
    print("Currently paused at:", state.next)
    if not state.next:
        print("Run already complete. Final state:", state.values)
        return

    try:
        result = graph.invoke(Command(resume="check"), config=config)
    except RuntimeError as exc:
        print("Resume attempt raised RuntimeError (expected if unresolved):")
        print(" ", exc)
        return

    state = graph.get_state(config)
    print("Result after resume:", result)
    print("Now paused at:", state.next)
    print("Persisted status:", state.values.get("status"))


if __name__ == "__main__":
    main()