"""
state_graph/onboarding/run_kill_demo.py -- Piece 6: real mid-node
kill/restart demo, run against the ACTUAL onboarding graph (not
state_graph/checkpointing/'s toy 3-node script, which only proves the
LangGraph pattern in isolation).

HOW TO USE (see the matching run_resume_after_kill.py for the second
half):

  1. Delete onboarding_checkpoints.db if you want a totally clean run
     (optional -- this script uses a dedicated thread_id so it won't
     collide with other demo runs in the same file).
  2. Run this script:  python run_kill_demo.py
  3. It will pause once at awaiting_documents (expected -- ignore this,
     it resumes itself automatically after a 1s pause, this isn't the
     kill point).
  4. Watch the printed [node:policy_check] lines. Once you see AT LEAST
     ONE "checking term i/N" line print (but not all of them), press
     Ctrl+C for real. This is a genuine OS-level process kill mid-node,
     not a simulated one -- policy_check is still inside its loop,
     mid an actual live Gemini call, when the process dies.
  5. Run run_resume_after_kill.py in a FRESH process (new terminal
     invocation, not a continuation) with the SAME thread_id. It proves:
       - documents_requested / awaiting_documents / intake_triage /
         terms_extracted do NOT print their entry lines again --
         genuinely not re-executed, because they were already
         checkpointed as complete before the kill.
       - policy_check DOES print "entered" again and re-runs its loop
         from term 1 -- this is the correct, expected LangGraph
         guarantee: checkpoints commit at node/superstep boundaries, so
         an INCOMPLETE node's partial work is discarded and that node
         restarts from its own beginning. Only completed steps are
         guaranteed not to re-run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ONBOARDING_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ONBOARDING_DIR.parents[1]
for _p in (str(_ONBOARDING_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langgraph.types import Command

from graph import build_graph

THREAD_ID = "onboarding-crash-demo-1"

if __name__ == "__main__":
    graph = build_graph()
    config = {"configurable": {"thread_id": THREAD_ID}}

    initial_state = {
        "supplier_name": "Nile Fresh",
        "contact_email": "orders@nilefresh.example",
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

    print("=== Starting run (fresh thread_id), pausing at awaiting_documents ===", flush=True)
    graph.invoke(initial_state, config=config)
    time.sleep(1)

    supplier_document = (
        "Delivery window: 3 days\n"
        "Payment terms: Net 30\n"
        "Return policy: Full refund on damaged goods within 7 days\n"
        "Quality guarantee: 95% freshness on arrival\n"
        "Contact: Storage requirement — produce refrigerated at 1°C\n"
    )

    print("=== Resuming with real supplier document -- watch for [node:policy_check] lines ===", flush=True)
    print("=== Once you see at least one 'checking term' line (but not all), Ctrl+C NOW ===", flush=True)
    final = graph.invoke(Command(resume=supplier_document), config=config)
    print("If you see this, the run completed WITHOUT being killed -- rerun and Ctrl+C sooner.")
    print("Final status:", final["status"])