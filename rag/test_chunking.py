"""
rag/test_chunking.py - Structural tests for the corpus chunker. No API
calls, no cost — this only checks that chunk_corpus() is doing the right
thing before anything gets embedded.
"""
from chunking import chunk_corpus, DOC_METADATA

print("=== CHUNKING TEST ===\n")

chunks = chunk_corpus()

by_doc: dict[str, int] = {}
for c in chunks:
    by_doc[c.doc_id] = by_doc.get(c.doc_id, 0) + 1

print(f"Total chunks: {len(chunks)}")
for doc_id, count in sorted(by_doc.items()):
    print(f"  {doc_id}: {count} chunks")

# --- Structural checks ---
failures = []

if set(by_doc.keys()) != set(DOC_METADATA.keys()):
    failures.append(f"Doc coverage mismatch: got {sorted(by_doc.keys())}, "
                     f"expected {sorted(DOC_METADATA.keys())}")

for c in chunks:
    if not c.text.strip():
        failures.append(f"{c.chunk_id}: empty chunk text")
    md = c.metadata()
    if any(v is None for v in md.values()):
        failures.append(f"{c.chunk_id}: metadata contains a None value — Chroma will reject this: {md}")
    if "supplier_name" in md and md["doc_type"] != "supplier_contract":
        failures.append(f"{c.chunk_id}: has supplier_name but doc_type is {md['doc_type']}")

# Section numbers referenced by the retrieval_eval test questions (built
# next) must actually exist, or those questions test nothing.
must_exist = {
    ("nile_fresh_produce", "4.2"),
    ("nile_fresh_produce", "1.2"),
    ("coastal_seafood_meats", "1.1"),
    ("delta_dairy_co", "2.2"),
    ("food_safety_storage_policy", "1.3"),
}
present = {(c.doc_id, c.section_number) for c in chunks}
missing = must_exist - present
if missing:
    failures.append(f"Expected sections missing from chunked output: {missing}")

print("\n--- Sample chunks (full text) ---")
for target in ["food_safety_storage_policy::3", "nile_fresh_produce::4.2"]:
    match = next((c for c in chunks if c.chunk_id == target), None)
    if match is None:
        failures.append(f"Sample chunk {target} not found")
        continue
    print(f"\n[{match.chunk_id}]  metadata={match.metadata()}")
    print(match.text)

print()
if failures:
    for f in failures:
        print(f"FAIL: {f}")
    raise SystemExit(1)
else:
    print(f"PASS: all {len(chunks)} chunks well-formed, Chroma-safe metadata, correct doc coverage.")
    print("PASS: section numbers needed for later citation-heavy retrieval tests are all present.")
    print("\n=== ALL TESTS PASSED ===")