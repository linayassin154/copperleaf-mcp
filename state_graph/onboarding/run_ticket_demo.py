"""
state_graph/onboarding/run_ticket_demo.py — reproducible driver for
manually verifying Piece 5 (ticket path), in the same "separate real
process invocations" style already used to verify Piece 4 (see
test_evidence/piece4_admin_review_run.txt). This is a script you run
multiple times as separate `python` processes — not a pytest file.

Usage:
  python run_ticket_demo.py <thread_id>

First run (fresh thread_id): starts a new onboarding run and resumes it
with a GARBLED document (no "Label: value" lines at all), so
terms_extracted legitimately produces zero terms -> the graph pauses at
ticket_wait. Prints the ticket_id you need to resolve.

Later runs (same thread_id): re-invokes the same thread. If the ticket
in the `tickets` table is still unresolved, it pauses again (proving the
state survived — whether or not you killed the process in between) and,
per the premature-resume safeguard, raises RuntimeError if you attempt a
resume before a resolution is recorded. Once resolved via
scripts/resolve_ticket.py, the next run resumes and shows the final
state.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langgraph.types import Command  # noqa: E402

from graph import build_graph  # noqa: E402

GARBLED_DOCUMENT = (
    "Hey, thanks for reaching out! We're excited to work with Copperleaf.\n"
    "Let us know what info you need from our side and we'll send it over.\n"
)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_ticket_demo.py <thread_id>")
        raise SystemExit(1)
    thread_id = sys.argv[1]
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph()

    state = graph.get_state(config)

    if not state.values:
        print(f"=== Fresh run, thread_id={thread_id} ===")
        initial_state = {
            "supplier_name": "Garbled Foods Ltd",
            "contact_email": "hello@garbledfoods.example",
            "status": "new_supplier",
            "documents": [],
            "extracted_terms": [],
            "policy_matches": [],
            "policy_conflicts": [],
            "admin_decision": "",
            "admin_notes": "",
        }
        result = graph.invoke(initial_state, config=config)
        state = graph.get_state(config)
        print("After first invoke, paused at:", state.next)
        assert state.next == ("awaiting_documents",), "expected pause at awaiting_documents"

        print(f"\n=== Resuming with a GARBLED document (thread_id={thread_id}) ===")
        result = graph.invoke(Command(resume=GARBLED_DOCUMENT), config=config)
        state = graph.get_state(config)
        print("Result:", result)
        print("Paused at:", state.next)
        print("Persisted status:", state.values.get("status"))
        print("Extracted terms:", state.values.get("extracted_terms"))
        return

    print(f"=== Re-invoking existing thread_id={thread_id} ===")
    print("Current persisted status:", state.values.get("status"))
    print("Currently paused at:", state.next)
    if not state.next:
        print("Run already complete. Final state:", state.values)
        return

    try:
        # NOTE: Command(resume=None) crashes with an UnboundLocalError
        # inside langgraph 1.2.11's Pregel loop (a LangGraph bug, not our
        # node logic — confirmed by reproducing it directly). Any non-None
        # resume value works; the actual value is discarded, since
        # ticket_wait/awaiting_admin_review both re-read their own table
        # for the real answer rather than trusting interrupt()'s return.
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