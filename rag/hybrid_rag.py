"""
rag/hybrid_rag.py - Hybrid retrieval: vector similarity (vector_store.py)
fused with keyword matching (bm25_store.py) via Reciprocal Rank Fusion.

Why RRF and not a weighted score average: cosine distance and BM25 score
live on completely different, incomparable scales (distance is bounded
~[0, 2], BM25 is an unbounded corpus-dependent score). Averaging them
would require an arbitrary normalization constant with no principled
value. RRF sidesteps that entirely — it only uses each result's RANK
position in its own list, never the raw score, so no normalization
constant is needed and no scale mismatch can silently bias the fusion.

generate() is NOT reimplemented here — it's imported directly from
naive_rag.py. Only retrieve() differs between naive and hybrid RAG; the
generation step (prompt assembly, LLM call, response extraction) is
identical, so duplicating it here would just be two copies to keep in
sync for no reason.
"""
from __future__ import annotations

from rag.bm25_store import BM25Store
from rag.naive_rag import RAGResult, generate
from rag.vector_store import VectorStore
RRF_K = 60  # standard default from the original RRF paper (Cormack et al.)


def retrieve(
    vector_store: VectorStore,
    bm25_store: BM25Store,
    query: str,
    n_results: int = 5,
    candidate_pool: int = 10,
    where: dict | None = None,
) -> list[dict]:
    """Retrieve candidate_pool results from EACH retriever, fuse by RRF,
    return the top n_results fused chunks. candidate_pool > n_results on
    purpose — fusion needs a wider pool to actually re-rank against, not
    just the two retrievers' already-final top-n_results."""
    vector_hits = vector_store.search(query, n_results=candidate_pool, where=where)
    bm25_hits = bm25_store.search(query, n_results=candidate_pool)

    # rank -> reciprocal rank contribution, summed across both retrievers
    rrf_scores: dict[str, float] = {}
    chunk_lookup: dict[str, dict] = {}

    for rank, hit in enumerate(vector_hits):
        rrf_scores[hit["chunk_id"]] = rrf_scores.get(hit["chunk_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
        chunk_lookup[hit["chunk_id"]] = hit

    for rank, hit in enumerate(bm25_hits):
        rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        if hit.chunk_id not in chunk_lookup:
            chunk_lookup[hit.chunk_id] = {
                "chunk_id": hit.chunk_id,
                "text": hit.text,
                "metadata": hit.metadata,
                "distance": None,
            }

    ranked_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)
    top_ids = ranked_ids[:n_results]

    results = []
    for cid in top_ids:
        chunk = dict(chunk_lookup[cid])
        chunk["rrf_score"] = rrf_scores[cid]
        results.append(chunk)
    return results


def answer_question(
    vector_store: VectorStore,
    bm25_store: BM25Store,
    query: str,
    n_results: int = 5,
    where: dict | None = None,
) -> RAGResult:
    """Full hybrid RAG pipeline: fused retrieve, then the same generate()
    naive RAG uses."""
    chunks = retrieve(vector_store, bm25_store, query, n_results=n_results, where=where)
    answer = generate(query, chunks)
    return RAGResult(answer=answer, retrieved_chunks=chunks, query=query)