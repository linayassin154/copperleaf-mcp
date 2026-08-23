"""
state_graph/onboarding/nodes/policy_check.py — RAG addition #1 for the
Onboarding graph. Compares each extracted contract term against the real
policy corpus (rag/corpus/) so a conflict is caught by retrieval against
real documents, not the model's own opinion of what's acceptable.

Reuses rag/hybrid_rag.py and rag/vector_store.py exactly as they already
exist for the memory/RAG agent — does NOT reimplement retrieval, and does
NOT call the memory/RAG agent's own consolidation/answer code path. This
node builds its own BM25Store from chunk_corpus() and its own
hybrid_rag.retrieve() call, which keeps this graph's scope independent of
the RAG agent's runtime state, matching the 're-skin' guardrail from the
team plan doc.
"""
from __future__ import annotations

import json
import os
import time

from langchain_google_genai import ChatGoogleGenerativeAI

from rag.bm25_store import BM25Store
from rag.chunking import chunk_corpus
from rag.hybrid_rag import retrieve as hybrid_retrieve
from rag.naive_rag import _extract_text
from rag.vector_store import VectorStore

from state import OnboardingState

_CONFLICT_PROMPT = (
    "You are checking one extracted supplier-contract term against "
    "Copperleaf's own retrieved policy text. Decide only whether the term "
    "CONFLICTS with the policy — do not judge anything not stated in the "
    "policy text below.\n\n"
    "Extracted term: {term}\n\n"
    "Retrieved policy context:\n{context}\n\n"
    'Respond with ONLY JSON, no markdown fences: '
    '{{"conflicts": true|false, "reason": "<one sentence citing the policy text>"}}'
)


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(no relevant policy text retrieved)"
    return "\n\n".join(
        f"[{c['metadata'].get('doc_id')}::{c['metadata'].get('section_title', '')}]\n{c['text']}"
        for c in chunks
    )


def policy_check(state: OnboardingState) -> OnboardingState:
    # Piece 6 (kill/restart demo): this print, one per term with flush=True
    # and a real per-term Gemini call in between, is what gives a real
    # OS-level Ctrl+C a genuine multi-second window to land INSIDE this
    # node's execution rather than between nodes. See run_kill_demo.py.
    #
    # DEMO-ONLY SLOWDOWN (Piece 6): the live Gemini calls below are fast
    # enough that a human often can't press Ctrl+C before the whole loop
    # finishes, which was the actual failure mode observed on the real
    # machine (see test_evidence/piece6_kill_restart_recovery.txt from
    # the run BEFORE this fix). ONBOARDING_DEMO_SLOWDOWN_SECONDS inserts a
    # deliberate pause after each "checking term" print and before that
    # term's real Gemini call, purely to widen the human reaction window.
    # It is 0 (a no-op) unless a caller explicitly sets the env var --
    # run_kill_demo.py is the ONLY script in this repo that sets it. It
    # does not touch: the Gemini call itself (still real, still live),
    # the checkpointing mechanism, node boundaries, or anything reachable
    # from run_resume_after_kill.py, the tests, or production use of this
    # graph.
    _demo_slowdown_seconds = float(os.environ.get("ONBOARDING_DEMO_SLOWDOWN_SECONDS", "0") or "0")

    print(f"[node:policy_check] entered, {len(state['extracted_terms'])} term(s) to check", flush=True)
    vector_store = VectorStore()
    bm25_store = BM25Store(chunk_corpus())
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0)

    matches: list[str] = []
    conflicts: list[str] = []

    for i, term in enumerate(state["extracted_terms"], start=1):
        print(f"[node:policy_check] checking term {i}/{len(state['extracted_terms'])}: {term}", flush=True)

        if _demo_slowdown_seconds > 0:
            print(
                f"[node:policy_check] DEMO-ONLY: sleeping {_demo_slowdown_seconds}s "
                "before this term's Gemini call (ONBOARDING_DEMO_SLOWDOWN_SECONDS is "
                "set) -- Ctrl+C now to kill mid-node.",
                flush=True,
            )
            time.sleep(_demo_slowdown_seconds)

        chunks = hybrid_retrieve(vector_store, bm25_store, term, n_results=3)
        matches.append(f"{term} -> " + ", ".join(
            f"{c['metadata'].get('doc_id')}::{c['metadata'].get('section_title', '')}"
            for c in chunks
        ))

        prompt = _CONFLICT_PROMPT.format(term=term, context=_format_context(chunks))
        response = llm.invoke([{"role": "user", "content": prompt}])
        raw = _extract_text(response).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError:
            verdict = {"conflicts": False, "reason": f"Unparseable critic response: {raw[:200]}"}

        if verdict.get("conflicts"):
            conflicts.append(f"{term}: {verdict.get('reason', 'no reason given')}")

    print("[node:policy_check] all terms checked, node complete", flush=True)
    return {
        **state,
        "status": "policy_check",
        "policy_matches": matches,
        "policy_conflicts": conflicts,
    }