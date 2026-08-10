"""
rag/agentic_rag.py - Agentic RAG: a multi-hop retrieval loop.

Genuine trigger for THIS corpus specifically: a question like "which
suppliers have had late deliveries that also violate the food-safety
storage policy" needs one retrieval into a supplier contract AND a
separate retrieval into food_safety_storage_policy.md — no single
embedding query (even hybrid) reliably retrieves both halves in one pass,
because the two halves don't share enough vocabulary or a common section
number to co-rank highly together.

Loop: retrieve -> ask the LLM "is this enough to answer, or what should I
search next?" -> if insufficient, retrieve again with the follow-up query
-> repeat up to max_hops -> generate the final answer from the FULL
accumulated (deduped) chunk set, not just the last hop's chunks.
"""
from __future__ import annotations

import json

from langchain_google_genai import ChatGoogleGenerativeAI

from hybrid_rag import retrieve as hybrid_retrieve
from naive_rag import GENERATION_MODEL, RAGResult, _extract_text, generate
from bm25_store import BM25Store
from vector_store import VectorStore

SUFFICIENCY_PROMPT = (
    "You are deciding whether retrieved context is enough to fully answer "
    "a question, or whether another, DIFFERENT search is needed.\n\n"
    "Question: {query}\n\n"
    "Retrieved context so far:\n{context}\n\n"
    "Respond with ONLY a JSON object, no markdown fences, no preamble:\n"
    '{{"sufficient": true|false, "follow_up_query": "<a different, more '
    'specific search query, or null if sufficient>", "reasoning": "<one '
    'sentence>"}}\n\n'
    "The follow_up_query must search for something the current context is "
    "missing — never repeat the original question verbatim."
)


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(nothing retrieved yet)"
    return "\n\n".join(
        f"[{c['metadata'].get('doc_id')}::{c['metadata'].get('section_title', '')}]\n{c['text']}"
        for c in chunks
    )


def _assess_sufficiency(query: str, chunks: list[dict], llm: ChatGoogleGenerativeAI) -> dict:
    prompt = SUFFICIENCY_PROMPT.format(query=query, context=_format_context(chunks))
    response = llm.invoke([{"role": "user", "content": prompt}])
    raw = _extract_text(response).strip()
    # Strip markdown fences defensively — some Gemini responses wrap JSON
    # in ```json fences even when explicitly told not to.
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A malformed sufficiency response should never crash the whole
        # pipeline — treat it as "sufficient" so the loop falls through
        # to generation with whatever was already retrieved.
        return {"sufficient": True, "follow_up_query": None, "reasoning": "parse failure, stopping hops"}


def answer_question(
    vector_store: VectorStore,
    bm25_store: BM25Store,
    query: str,
    max_hops: int = 3,
    n_results_per_hop: int = 4,
    llm: ChatGoogleGenerativeAI | None = None,
) -> RAGResult:
    if llm is None:
        llm = ChatGoogleGenerativeAI(model=GENERATION_MODEL, temperature=0, max_tokens=512)

    accumulated: dict[str, dict] = {}  # chunk_id -> chunk, deduped across hops
    queries_used: list[str] = []
    current_query = query
    hops_taken = 0

    for hop in range(max_hops):
        hops_taken += 1
        queries_used.append(current_query)

        hits = hybrid_retrieve(vector_store, bm25_store, current_query, n_results=n_results_per_hop)
        for hit in hits:
            accumulated[hit["chunk_id"]] = hit

        chunks_so_far = list(accumulated.values())
        assessment = _assess_sufficiency(query, chunks_so_far, llm)

        if assessment.get("sufficient") or not assessment.get("follow_up_query"):
            break
        current_query = assessment["follow_up_query"]
    else:
        # Loop exhausted max_hops without ever being marked sufficient —
        # fall through to generation with whatever was accumulated. This
        # is a real outcome to report on, not silently swallowed.
        pass

    final_chunks = list(accumulated.values())
    answer = generate(query, final_chunks, llm=llm)

    return RAGResult(
        answer=answer,
        retrieved_chunks=final_chunks,
        query=query,
        hops=hops_taken,
        queries_used=queries_used,
    )