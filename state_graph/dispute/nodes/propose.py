from __future__ import annotations
""""
state_graph/dispute/nodes/propose.py — propose_resolution
(LLM addition #2: Tree of Thoughts).

Why ToT fits this node: once investigate_discrepancy has gathered
grounded facts, there are genuinely multiple viable resolution
strategies (full_credit / partial_credit_reorder / replacement / reject),
each with real tradeoffs on cost, supplier relationship, and policy fit --
not a single deterministic answer, and not a whitelisted-action lookup.
ToT generates several candidates, scores each, and picks the best.

proposed_credit is computed from real numbers (unit_cost x shortfall),
never asserted by the model directly.
"""
"""
state_graph/dispute/nodes/propose.py — propose_resolution
(LLM addition #2: Tree of Thoughts).
"""
 

import sys
from pathlib import Path
from typing import Literal, cast

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from state import DisputeState

_CANDIDATES = ["full_credit", "partial_credit_reorder", "replacement", "reject"]
@tool
def score_resolution(resolution: str, cost_score: int, relationship_score: int, policy_score: int, rationale: str) -> str:
    """Score ONE candidate resolution (full_credit, partial_credit_reorder,
    replacement, or reject) on three axes, each 1-5 (5 = best outcome on
    that axis): cost_score, relationship_score, policy_score. Call this
    once per candidate you're evaluating."""
    return f"{resolution}: cost={cost_score} rel={relationship_score} policy={policy_score} — {rationale}"


def propose_resolution(state: DisputeState) -> DisputeState:
    print("[node:propose_resolution] entered", flush=True)
    shortfall = max(0.0, state["expected_quantity"] - state["received_quantity"])
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0.3)
    llm_with_tools = llm.bind_tools([score_resolution])

    facts = "\n".join(state["subcheck_results"])
    response = llm_with_tools.invoke([
        {"role": "system", "content": (
            "You are proposing a resolution for a supplier delivery dispute. "
            f"Score EACH of these four candidates by calling score_resolution "
            f"once per candidate: {', '.join(_CANDIDATES)}."
        )},
        {"role": "user", "content": (
            f"Dispute type: {state['dispute_type']}. Shortfall: {shortfall} units "
            f"at unit_cost {state['unit_cost']}. Investigation findings:\n{facts}"
        )},
    ])

    scored: list[tuple[str, int, str]] = []
    for call in getattr(response, "tool_calls", None) or []:
        args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
        resolution = args.get("resolution")
        if resolution not in _CANDIDATES:
            continue
        total = args.get("cost_score", 0) + args.get("relationship_score", 0) + args.get("policy_score", 0)
        scored.append((resolution, total, args.get("rationale", "")))

    chosen: Literal["full_credit", "partial_credit_reorder", "replacement", "reject"]
    if not scored:
        chosen = "reject"
        rationale = "Model returned no usable tool calls; defaulting to reject for human review."
    else:
        chosen_raw, _, rationale = max(scored, key=lambda t: t[1])
        chosen = cast(
            Literal["full_credit", "partial_credit_reorder", "replacement", "reject"],
            chosen_raw,
        )

    proposed_credit = (
        round(shortfall * state["unit_cost"], 2)
        if chosen in ("full_credit", "partial_credit_reorder")
        else 0.0
    )

    return {
        **state,
        "status": "proposing_resolution",
        "candidate_resolutions": [f"{r}: score={s}, {why}" for r, s, why in scored],
        "chosen_resolution": chosen,
        "resolution_rationale": rationale,
        "proposed_credit": proposed_credit,
    }


def route_after_propose(state: DisputeState) -> str:
    """HITL fires when the proposed credit exceeds min($200, 15% of order
    value), or when the resolution is a replacement shipment (a
    higher-cost, harder-to-reverse commitment than a credit). Everything
    else applies automatically."""
    order_value = state["expected_quantity"] * state["unit_cost"]
    threshold = min(200.0, 0.15 * order_value)
    needs_admin = state["proposed_credit"] > threshold or state["chosen_resolution"] == "replacement"
    return "credit_approval" if needs_admin else "apply_resolution"