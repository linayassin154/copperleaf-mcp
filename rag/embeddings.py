"""
rag/embeddings.py - Embedding wrapper for the Copperleaf RAG corpus.

Uses Google's text-embedding-004 via langchain-google-genai (already a
project dependency, and reuses the same GOOGLE_API_KEY already set up for
recursive summarization in context_eval/ — no new credential needed).

Google's embedding model is ASYMMETRIC: retrieval quality is materially
better when corpus chunks are embedded with task_type="RETRIEVAL_DOCUMENT"
and search queries are embedded separately with task_type="RETRIEVAL_QUERY".
Using one call for both — the naive integration — throws that away for
free, so embed_documents() and embed_query() are kept as two distinct
functions rather than one embed(text) that guesses.
"""
from __future__ import annotations

import time

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from google.api_core.exceptions import ResourceExhausted

load_dotenv()

EMBED_MODEL = "models/text-embedding-004"
EMBED_DIM = 768


def _client() -> GoogleGenerativeAIEmbeddings:
    # google_api_key not passed explicitly - the client reads GOOGLE_API_KEY
    # from the environment itself, same as context_eval/strategies_llm.py.
    return GoogleGenerativeAIEmbeddings(model=EMBED_MODEL)


def _with_retry(fn, *args, max_retries: int = 4, **kwargs):
    """Same shape as agent/client.py's Groq retry logic. Free-tier
    embedding calls hit per-minute rate limits too, and embedding the
    whole 41-chunk corpus in one ingest run is exactly the kind of burst
    that trips one."""
    delay = 2.0
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except ResourceExhausted:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed corpus chunks for indexing. task_type=RETRIEVAL_DOCUMENT."""
    client = _client()
    return _with_retry(client.embed_documents, texts, task_type="RETRIEVAL_DOCUMENT")


def embed_query(text: str) -> list[float]:
    """Embed a user query for search. task_type=RETRIEVAL_QUERY — a
    DIFFERENT embedding-space alignment than embed_documents, by design,
    not an inconsistency."""
    client = _client()
    return _with_retry(client.embed_query, text, task_type="RETRIEVAL_QUERY")


if __name__ == "__main__":
    sample_doc = (
        "Feta cheese stored in brine has a materially longer shelf life "
        "than vacuum-packed feta."
    )
    sample_query = "how long does brined feta last?"

    print("Embedding one sample document chunk and one sample query...\n")

    doc_vec = embed_documents([sample_doc])[0]
    query_vec = embed_query(sample_query)

    print(f"Document embedding: dim={len(doc_vec)}, first 5 values={doc_vec[:5]}")
    print(f"Query embedding:    dim={len(query_vec)}, first 5 values={query_vec[:5]}")

    assert len(doc_vec) == EMBED_DIM, f"expected {EMBED_DIM} dims, got {len(doc_vec)}"
    assert len(query_vec) == EMBED_DIM, f"expected {EMBED_DIM} dims, got {len(query_vec)}"
    print(f"\nPASS: both embeddings are {EMBED_DIM}-dimensional, as expected for text-embedding-004.")