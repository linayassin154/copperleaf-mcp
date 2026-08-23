"""
state_graph/onboarding/run_ticket_demo_zero_terms.py -- triggers the
ticket path via the "purely mechanical" trigger documented in
nodes/ticket.py: terms_extracted finds zero usable terms, NOT the
flag_for_review judgment-call trigger.

Unlike run_ticket_demo.py's GARBLED_DOCUMENT (which has no contract text
at all and correctly makes intake_triage pick request_documents instead),
this document reads as a real contract with clear, quotable terms -- so
a live intake_triage call should pick extract_terms -- but it uses label
words outside intake.py's regex whitelist (delivery window, payment
terms, return policy, quality guarantee, contact), so the deterministic
extractor legitimately finds zero matches.

Usage: python run_ticket_demo_zero_terms.py <thread_id>
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
from langgraph.types import Command

from graph import build_graph
from state import OnboardingState

MISMATCHED_LABEL_DOCUMENT = (
    "Shipping timeline: 5 business days\n"
    "Invoice terms: Net 45\n"
    "Refund policy: Full refund within 10 days if damaged\n"
    "Freshness guarantee: 98% on arrival\n"
    "Cold storage requirement: 2 degrees C\n"
)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_ticket_demo_zero_terms.py <thread_id>")
        raise SystemExit(1)
    thread_id = sys.argv[1]
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    graph = build_graph()

    initial_state: OnboardingState = {
        "supplier_name": "Mismatched Labels Co",
        "contact_email": "hello@mismatched.example",
        "status": "new_supplier",
        "documents": [],
        "extracted_terms": [],
        "policy_matches": [],
        "policy_conflicts": [],
        "admin_decision": "",
        "admin_notes": "",
        "triage_decision": "",
        "triage_reason": "",
    }

    print(f"=== Fresh run, thread_id={thread_id} ===", flush=True)
    graph.invoke(initial_state, config=config)

    print("\n=== Resuming with a real-looking contract using non-whitelisted labels ===", flush=True)
    result = graph.invoke(Command(resume=MISMATCHED_LABEL_DOCUMENT), config=config)

    state = graph.get_state(config)
    print("\nResult:", result)
    print("Paused at:", state.next)
    print("Persisted status:", state.values.get("status"))
    print("Triage decision:", state.values.get("triage_decision"), "| reason:", state.values.get("triage_reason"))
    print("Extracted terms:", state.values.get("extracted_terms"))