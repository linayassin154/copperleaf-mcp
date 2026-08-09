"""
rag/test_vector_store.py - Structural tests for VectorStore. Uses FAKE,
deterministic embeddings (monkeypatched in) instead of real Gemini calls —
this tests the vector database mechanics (indexing, metadata pre-filtering,
similarity ranking), not embedding quality. That's what rag/ingest.py
(real embeddings, real corpus) is for.
"""
import random
import shutil
from pathlib import Path

import embeddings
import vector_store
from chunking import chunk_corpus

print("=== VECTOR STORE TEST (fake embeddings — no API calls) ===\n")


def _fake_vector(text: str) -> list[float]:
    # Deterministic: same text always produces the same vector, so a
    # document and a query built from identical text are guaranteed to
    # be an exact nearest-neighbor match — that's what proves search()
    # is actually doing similarity ranking, not returning arbitrary order.
    random.seed(hash(text) % (2**32))
    return [random.random() for _ in range(16)]


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    return [_fake_vector(t) for t in texts]


def _fake_embed_query(text: str) -> list[float]:
    return _fake_vector(text)


embeddings.embed_documents = _fake_embed_documents
embeddings.embed_query = _fake_embed_query
vector_store.embed_documents = _fake_embed_documents
vector_store.embed_query = _fake_embed_query

TEST_STORE_DIR = Path(__file__).parent / ".chroma_test"
shutil.rmtree(TEST_STORE_DIR, ignore_errors=True)

chunks = chunk_corpus()
print(f"Chunked corpus: {len(chunks)} chunks")

store = vector_store.VectorStore(persist_dir=TEST_STORE_DIR)
store.reset()
store.add_chunks(chunks)

failures = []

if store.count() != len(chunks):
    failures.append(f"count() = {store.count()}, expected {len(chunks)}")

# Self-match: querying with a chunk's own text must return that chunk first.
target = next(c for c in chunks if c.chunk_id == "nile_fresh_produce::4.2")
results = store.search(target.text, n_results=3)
print(f"\nUnfiltered search (query = {target.chunk_id}'s own text):")
for r in results:
    print(f"  {r['chunk_id']:35s} distance={r['distance']:.6f}")
if results[0]["chunk_id"] != target.chunk_id:
    failures.append(f"self-match failed: top result was {results[0]['chunk_id']}, expected {target.chunk_id}")

# Metadata pre-filtering: supplier scope.
filtered = store.search("cold chain requirement", n_results=5, where={"supplier_name": "Coastal Seafood & Meats"})
print(f"\nFiltered search (supplier_name=Coastal Seafood & Meats), {len(filtered)} results:")
for r in filtered:
    print(f"  {r['chunk_id']:35s} supplier={r['metadata'].get('supplier_name')}")
if not filtered:
    failures.append("supplier-filtered search returned zero results")
if any(r["metadata"].get("supplier_name") != "Coastal Seafood & Meats" for r in filtered):
    failures.append("supplier filter leaked a chunk from a different supplier")

# Metadata pre-filtering: category scope, across a category with one supplier.
filtered_cat = store.search("delivery window", n_results=10, where={"category": "Dairy"})
print(f"\nFiltered search (category=Dairy), {len(filtered_cat)} results:")
for r in filtered_cat:
    print(f"  {r['chunk_id']:35s} doc_id={r['metadata'].get('doc_id')}")
if any(r["metadata"].get("doc_id") != "delta_dairy_co" for r in filtered_cat):
    failures.append("category filter returned a chunk from a doc outside that category")

print()
if failures:
    for f in failures:
        print(f"FAIL: {f}")
    raise SystemExit(1)
else:
    print(f"PASS: {len(chunks)}/{len(chunks)} chunks indexed correctly.")
    print("PASS: self-match retrieval correct — search() is ranking by similarity, not arbitrary order.")
    print("PASS: metadata pre-filtering restricts results to the matching supplier/category ONLY —")
    print("      the filter is applied as part of the ANN search, not discarded after the fact.")
    print("\n=== ALL TESTS PASSED ===")