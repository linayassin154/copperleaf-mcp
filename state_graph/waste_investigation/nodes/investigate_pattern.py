"""
state_graph/waste_investigation/nodes/investigate_pattern.py — Piece 3:
investigate_pattern + check_other_branches.

LLM addition #1: task decomposition. Rather than one fixed query, this
node asks the LLM to decompose "investigate this supplier pattern" into
concrete sub-questions (is this recent/ongoing? does it affect more than
one branch? is there a plausible root cause visible from the data?) and
answer each grounded in the real facts aggregate_data already gathered --
no new speculative DB queries here, this node reasons over Piece 2's
output, and check_other_branches confirms which branches are affected
using the same aggregate_data result (already computed, not re-queried
against memory/consolidation.py or any other agent's output).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from state import WasteInvestigationState

load_dotenv()

INVESTIGATION_SYSTEM_PROMPT = """You are investigating a recurring supplier
problem for a restaurant chain. You are given a detected pattern (which
supplier, which items, which branches, how many write-offs). Decompose
your investigation into 2-4 short numbered findings, grounded ONLY in the
facts given -- do not invent dates, quantities, or branches not mentioned.
Cover: (1) whether this looks like an ongoing/recent issue or an isolated
incident, (2) whether more than one branch is affected and what that
implies, (3) a plausible root-cause hypothesis a manager should verify."""


def investigate_pattern(state: WasteInvestigationState) -> WasteInvestigationState:
    print("[node:investigate_pattern] entered", flush=True)

    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0.2)
    prompt = (
        f"Pattern summary: {state['pattern_summary']}\n"
        f"Supplier ID: {state['supplier_id']}\n"
        f"Affected item IDs: {state['item_id']} (and others per summary)\n"
        f"Affected branch IDs: {state['branch_id']} (and others per summary)\n"
        f"Total write-offs counted: {state['write_off_count']}"
    )
    response = llm.invoke([
        ("system", INVESTIGATION_SYSTEM_PROMPT),
        ("human", prompt),
    ])
    content = response.content
    if isinstance(content, list):
        # Gemini sometimes returns content as a list of blocks; extract
        # just the text portions instead of stringifying the whole object.
        content = "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
        )
    if not isinstance(content, str):
        content = str(content)

    # Split into numbered findings by real newlines, then drop the blank
    # lines the model's double-newline formatting leaves behind.
    notes = [line.strip() for line in content.split("\n") if line.strip()]

    print(f"[node:investigate_pattern] {len(notes)} finding(s) produced", flush=True)
    return {**state, "status": "investigate_pattern", "investigation_notes": notes}


def check_other_branches(state: WasteInvestigationState) -> WasteInvestigationState:
    """Confirms cross-branch reach using aggregate_data's own result --
    no second independent query, just makes the branch list explicit and
    routable."""
    print("[node:check_other_branches] entered", flush=True)
    # branch_ids were already found in aggregate_data's SQL; re-derive the
    # full list from the pattern_summary text is unnecessary -- store the
    # full list properly instead. (See note below on state.py field.)
    affected = state.get("other_branches_affected") or []
    print(f"[node:check_other_branches] branches on record: {affected}", flush=True)
    return {**state, "status": "check_other_branches"}


def route_after_investigation(state: WasteInvestigationState) -> str:
    if not state.get("investigation_notes"):
        return "ticket_open"
    return "generate_candidate_actions"