"""
retrieval_eval/run_comparison.py - Runs every question in questions.py
against all three retrieval architectures (naive / hybrid / agentic)
using the REAL corpus and REAL Gemini calls (embeddings + generation),
same "real corpus, real Gemini" standard as rag/ingest.py. Mirrors
context_eval/run_comparison.py's structure: build once, loop, time,
estimate tokens, print a table.

Run from the repo root:  python retrieval_eval/run_comparison.py
Redirect to a log for the committed evidence file, same pattern as
context_eval/run_comparison_output.log:
  python retrieval_eval/run_comparison.py > retrieval_eval/run_comparison_output.log
"""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "rag"))
sys.path.insert(0, str(REPO_ROOT))  # so `memory.semantic` etc. resolve for self_rag.py

from chunking import chunk_corpus
from vector_store import VectorStore
from bm25_store import BM25Store
import naive_rag
import hybrid_rag
import agentic_rag

from questions import QUESTIONS


def estimate_tokens(text: str) -> int:
    """Same word-based approximation as context_eval/strategies.py
    (~1.3 tokens/word) — consistent methodology across the whole project,
    and the RELATIVE comparison across architectures is what matters,
    same reasoning as that module's docstring."""
    return round(len(text.split()) * 1.3)


def score(answer: str, expected_keywords: list[str]) -> bool:
    """Correct if at least half the expected keywords appear in the
    answer, case-insensitive. Deliberately simple/deterministic, same
    rule-based philosophy as memory/consolidation.py's fact extraction —
    a cheap check that's still traceable to a reason, not an LLM grader
    whose own errors would need a second eval to catch."""
    answer_lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return hits >= len(expected_keywords)  # every expected keyword must appear, not just half


def run():
    print("=== RETRIEVAL ARCHITECTURE COMPARISON (real corpus, real Gemini) ===\n")

    chunks = chunk_corpus()
    vector_store = VectorStore()
    vector_store.reset()
    vector_store.add_chunks(chunks)
    bm25_store = BM25Store(chunks)
    print(f"Indexed {vector_store.count()} chunks into vector store + BM25 store.\n")

    rows = []

    for eq in QUESTIONS:
        # --- naive ---
        t0 = time.perf_counter()
        naive_chunks = naive_rag.retrieve(vector_store, eq.question, n_results=4)
        naive_answer = naive_rag.generate(eq.question, naive_chunks)
        naive_latency = time.perf_counter() - t0
        naive_correct = score(naive_answer, eq.expected_keywords)
        rows.append((eq.question, eq.category, "naive", naive_correct, estimate_tokens(naive_answer), naive_latency))

        # --- hybrid ---
        t0 = time.perf_counter()
        hybrid_chunks = hybrid_rag.retrieve(vector_store, bm25_store, eq.question, n_results=4)
        hybrid_answer = naive_rag.generate(eq.question, hybrid_chunks)
        hybrid_latency = time.perf_counter() - t0
        hybrid_correct = score(hybrid_answer, eq.expected_keywords)
        rows.append((eq.question, eq.category, "hybrid", hybrid_correct, estimate_tokens(hybrid_answer), hybrid_latency))

        # --- agentic ---
        t0 = time.perf_counter()
        agentic_result = agentic_rag.answer_question(vector_store, bm25_store, eq.question, max_hops=3)
        agentic_latency = time.perf_counter() - t0
        agentic_correct = score(agentic_result.answer, eq.expected_keywords)
        rows.append((eq.question, eq.category, "agentic", agentic_correct, estimate_tokens(agentic_result.answer), agentic_latency))

    print(f"{'Question':60s} | {'Arch':8s} | {'Correct':7s} | {'Tokens':6s} | {'Latency':8s}")
    print("-" * 100)
    for question, category, arch, correct, tokens, latency in rows:
        q_short = (question[:57] + "...") if len(question) > 60 else question
        print(f"{q_short:60s} | {arch:8s} | {str(correct):7s} | {tokens:6d} | {latency:6.2f}s")

    print("\n=== AGGREGATE ===")
    print(f"{'Architecture':12s} | {'Accuracy':9s} | {'Avg Tokens':10s} | {'Avg Latency':11s}")
    for arch in ("naive", "hybrid", "agentic"):
        arch_rows = [r for r in rows if r[2] == arch]
        accuracy = sum(1 for r in arch_rows if r[3]) / len(arch_rows)
        avg_tokens = sum(r[4] for r in arch_rows) / len(arch_rows)
        avg_latency = sum(r[5] for r in arch_rows) / len(arch_rows)
        print(f"{arch:12s} | {accuracy:8.0%} | {avg_tokens:10.0f} | {avg_latency:10.2f}s")

    print("\nDONE — paste the AGGREGATE table into README.md's Retrieval Architecture Comparison section.")


if __name__ == "__main__":
    run()