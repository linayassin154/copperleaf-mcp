"""
rag/ingest.py - Build the real, persistent vector index from the actual
corpus, using real Gemini embeddings. This is the one script in rag/ that
spends real API calls against the full corpus (41 chunks, one batched
embed_documents() call) — run it once to build .chroma/, then naive_rag.py
/ hybrid_rag.py / agentic_rag.py all read from what this produces.
"""
from chunking import chunk_corpus
from vector_store import VectorStore

print("=== INGEST: chunk corpus -> embed -> index ===\n")

chunks = chunk_corpus()
print(f"Chunked corpus: {len(chunks)} chunks across "
      f"{len(set(c.doc_id for c in chunks))} documents")

store = VectorStore()
store.reset()
print("\nEmbedding and indexing (1 batched API call for all chunks)...")
store.add_chunks(chunks)

print(f"\nIndexed count: {store.count()} (expected {len(chunks)})")
assert store.count() == len(chunks), "indexed count doesn't match chunk count — ingest is incomplete"

print("\n--- Sanity queries against the REAL index ---")
for query, where in [
    ("how long can brined feta be stored?", None),
    ("what does Section 4.2 of the Nile Fresh contract say about escalation?", None),
    ("cold chain temperature requirement", {"supplier_name": "Coastal Seafood & Meats"}),
]:
    print(f"\nQuery: {query!r}" + (f"  where={where}" if where else ""))
    results = store.search(query, n_results=3, where=where)
    for r in results:
        print(f"  {r['chunk_id']:35s} distance={r['distance']:.4f}  {r['metadata'].get('section_title', '')}")

print("\nPASS: real corpus ingested and queryable end-to-end with real embeddings.")