"""
rag/bm25_store.py - Keyword (BM25) index for the Copperleaf RAG corpus.

Built entirely in-memory from chunk_corpus() — unlike vector_store.py,
this needs no persistence and no API calls, so it's rebuilt fresh on every
process start (rebuilding from 41 chunks takes milliseconds). Its whole
job is to catch what vector search structurally can't: an exact section
number ("Section 4.2") or exact identifier doesn't reliably survive being
embedded into a dense vector, but it's a trivial keyword match.

Tokenization is deliberately simple (lowercase word-splitting via regex)
rather than a stemmer/lemmatizer pipeline — same "simple and explainable"
philosophy as memory/router.py's keyword-based routing: every retrieval
decision should be traceable to a reason a grader can read directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from chunking import Chunk

_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Result:
    chunk_id: str
    text: str
    metadata: dict
    bm25_score: float


class BM25Store:
    """Wraps rank_bm25.BM25Okapi. Constructed directly from a list of
    Chunk objects (from chunking.chunk_corpus()) — no separate ingest
    step, since there's nothing to persist."""

    def __init__(self, chunks: list[Chunk]):
        self._chunks = chunks
        self._corpus_tokens = [_tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens) if chunks else None

    def count(self) -> int:
        return len(self._chunks)

    def search(self, query_text: str, n_results: int = 5) -> list[BM25Result]:
        """Return the n_results highest-scoring chunks by BM25 score,
        descending. Returns [] if the store is empty rather than raising —
        an empty corpus is a valid (if useless) state, not an error."""
        if not self._bm25:
            return []

        query_tokens = _tokenize(query_text)
        scores = self._bm25.get_scores(query_tokens)

        ranked = sorted(
            range(len(self._chunks)), key=lambda i: scores[i], reverse=True
        )[:n_results]

        return [
            BM25Result(
                chunk_id=self._chunks[i].chunk_id,
                text=self._chunks[i].text,
                metadata=self._chunks[i].metadata(),
                bm25_score=float(scores[i]),
            )
            for i in ranked
        ]


if __name__ == "__main__":
    from chunking import chunk_corpus

    chunks = chunk_corpus()
    store = BM25Store(chunks)
    print(f"Indexed {store.count()} chunks (in-memory, no API calls).\n")

    for query in [
        "Section 4.2 escalation",
        "cold chain temperature requirement",
    ]:
        print(f"Query: {query!r}")
        for r in store.search(query, n_results=3):
            print(f"  {r.chunk_id:35s} score={r.bm25_score:.3f}  {r.metadata.get('section_title', '')}")
        print()