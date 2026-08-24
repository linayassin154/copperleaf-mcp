"""
state_graph/waste_investigation/nodes/generate_actions.py — Piece 4:
generate_candidate_actions + evaluate_actions.

LLM addition #2: Tree of Thoughts. Three real candidate corrective
actions (renegotiate terms, switch supplier, flag branch practice) are
generated and INDEPENDENTLY scored against investigate_pattern's actual
findings -- not committed to in generation order. This is what makes the
node genuinely ToT rather than a single LLM call: generation and scoring
are separate steps, and the chosen_action is whichever scores highest,
not whichever came first.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from state import WasteInvestigationState

load_dotenv()

CANDIDATE_ACTIONS = [
    "renegotiate_terms",
    "switch_supplier",
    "flag_branch_practice",
]

SCORING_SYSTEM_PROMPT = """You are scoring ONE candidate corrective action
for a recurring supplier problem, based ONLY on the investigation findings
given. Score from 0.0 (clearly wrong fit) to 1.0 (clearly the right fit).
Respond with EXACTLY two lines:
SCORE: <a number between 0.0 and 1.0>
REASON: <one sentence, grounded only in the findings given>"""


def _extract_text(content) -> str:
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
        )
    return content if isinstance(content, str) else str(content)


def generate_candidate_actions(state: WasteInvestigationState) -> WasteInvestigationState:
    """Generation step: the three whitelisted actions are fixed and known
    up front (this is a constrained decision, not open brainstorming) --
    what ToT adds here is the independent evaluation step below, not the
    action list itself."""
    print("[node:generate_candidate_actions] entered", flush=True)
    return {**state, "status": "generate_candidate_actions", "candidate_actions": list(CANDIDATE_ACTIONS)}


def evaluate_actions(state: WasteInvestigationState) -> WasteInvestigationState:
    """Evaluation step: score each candidate action independently against
    the real investigation findings, then select the highest scorer.
    Each candidate gets its own LLM call so one action's reasoning can't
    anchor/bias another's score."""
    print("[node:evaluate_actions] entered", flush=True)

    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0.2)
    findings_text = "\n".join(state["investigation_notes"])

    scores: list[float] = []
    reasons: list[str] = []

    for action in state["candidate_actions"]:
        prompt = (
            f"Candidate action: {action.replace('_', ' ')}\n\n"
            f"Investigation findings:\n{findings_text}\n\n"
            f"Pattern summary: {state['pattern_summary']}"
        )
        response = llm.invoke([
            ("system", SCORING_SYSTEM_PROMPT),
            ("human", prompt),
        ])
        text = _extract_text(response.content)

        score_match = re.search(r"SCORE:\s*([\d.]+)", text)
        reason_match = re.search(r"REASON:\s*(.+)", text)
        score = float(score_match.group(1)) if score_match else 0.0
        reason = reason_match.group(1).strip() if reason_match else "(no reason parsed)"

        print(f"[node:evaluate_actions] {action}: score={score} -- {reason}", flush=True)
        scores.append(score)
        reasons.append(reason)

    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    chosen = state["candidate_actions"][best_idx]
    rationale = reasons[best_idx]

    print(f"[node:evaluate_actions] chosen: {chosen} (score={scores[best_idx]})", flush=True)
    return {
        **state,
        "status": "evaluate_actions",
        "candidate_scores": scores,
        "chosen_action": chosen,
        "action_rationale": rationale,
    }


def route_after_evaluation(state: WasteInvestigationState) -> str:
    return "awaiting_admin_review"