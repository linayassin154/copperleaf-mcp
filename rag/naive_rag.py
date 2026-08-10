"""
rag/naive_rag.py - Baseline RAG: embed the query, retrieve top-k chunks by
vector similarity alone, stuff them into a prompt, generate an answer.

This is the reference point every other architecture (hybrid, agentic) is
compared against — no keyword matching, no multi-hop reasoning, no query
rewriting. It's the simplest thing that could work, and it's expected to
win on general/conceptual questions and lose on exact-identifier questions
("what does Section 4.2 say") where a chunk's embedding doesn't reliably
encode its own section number.

retrieve() and generate() are kept as two separate functions (not fused
into one answer_question() call) specifically so they can be tested and
timed independently — retrieve() costs one embedding call, generate()
costs one generation call, and the comparison table in retrieval_eval/
needs to report tokens/latency for each separately, not just the total.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain_google_genai import ChatGoogleGenerativeAI

from vector_store import VectorStore

GENERATION_MODEL = "gemini-flash-lite-latest"

SYSTEM_PROMPT = (
    "You are a Copperleaf Kitchens operations assistant. Answer the "
    "question using ONLY the retrieved context below — never from general "
    "knowledge, and never by guessing. If the retrieved context doesn't "
    "actually contain the answer, say so explicitly rather than making "
    "something up. Cite which section each fact comes from when you use it."
)


@dataclass
class RAGResult:
    answer: str
    retrieved_chunks: list[dict]
    query: str
    # Added for hybrid_rag.py / agentic_rag.py compatibility. Default to
    # naive RAG's own shape (1 hop, the single original query) so this
    # dataclass extension doesn't break naive_rag's existing callers/tests.
    hops: int = 1
    queries_used: list[str] = field(default_factory=lambda: None)

    def __post_init__(self):
        if self.queries_used is None:
            self.queries_used = [self.query]


def retrieve(store: VectorStore, query: str, n_results: int = 3, where: dict | None = None) -> list[dict]:
    """Pure vector similarity retrieval — no keyword component, no
    multi-hop. This is the entire "naive" part of naive RAG."""
    return store.search(query, n_results=n_results, where=where)


def _build_prompt(query: str, chunks: list[dict]) -> str:
    if not chunks:
        context = "(no chunks retrieved)"
    else:
        context = "\n\n".join(
            f"[{c['metadata'].get('doc_id')}::{c['metadata'].get('section_title', '')}]\n{c['text']}"
            for c in chunks
        )
    return f"Retrieved context:\n{context}\n\nQuestion: {query}"


def _extract_text(response) -> str:
    """Extract plain text from an LLM response, handling both shapes
    LangChain can return: a plain string, or (seen in practice with recent
    langchain-google-genai versions) a list of content blocks like
    [{"type": "text", "text": "...", "extras": {...}}] when the response
    carries extra metadata (e.g. a signature). Without this, callers get
    Python's repr() of the block list instead of the actual answer text."""
    content = response.content if hasattr(response, "content") else response

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "".join(parts)

    return str(content)


def generate(query: str, chunks: list[dict], llm: ChatGoogleGenerativeAI | None = None) -> str:
    """Generate an answer grounded ONLY in the given chunks. llm is an
    injectable parameter (not constructed inside this function) specifically
    so tests can pass a fake/mock LLM and verify the prompt-assembly logic
    without spending a real API call."""
    if llm is None:
        llm = ChatGoogleGenerativeAI(model=GENERATION_MODEL, temperature=0, max_tokens=1024)

    prompt = _build_prompt(query, chunks)
    response = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])
    return _extract_text(response)


def answer_question(store: VectorStore, query: str, n_results: int = 3, where: dict | None = None) -> RAGResult:
    """Full naive RAG pipeline: retrieve then generate. Convenience wrapper
    around the two separable steps above."""
    chunks = retrieve(store, query, n_results=n_results, where=where)
    answer = generate(query, chunks)
    return RAGResult(answer=answer, retrieved_chunks=chunks, query=query)