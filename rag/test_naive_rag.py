"""
rag/test_naive_rag.py - Structural tests for naive_rag.py. Uses FAKE
embeddings (same approach as test_vector_store.py) for retrieve(), and a
FAKE/mock LLM for generate() — proves retrieval correctness and prompt
grounding without spending a real Gemini call. Real generation quality is
what retrieval_eval/ (real corpus, real Gemini) is for.
"""
import random
import shutil
from pathlib import Path

import embeddings
import vector_store
from chunking import chunk_corpus
from vector_store import VectorStore

print("=== NAIVE RAG TEST (fake embeddings + mock LLM — no API calls) ===\n")


def _fake_vector(text: str) -> list[float]:
    random.seed(hash(text) % (2**32))
    return [random.random() for _ in range(16)]


embeddings.embed_documents = lambda texts: [_fake_vector(t) for t in texts]
embeddings.embed_query = lambda text: _fake_vector(text)
vector_store.embed_documents = embeddings.embed_documents
vector_store.embed_query = embeddings.embed_query

import naive_rag  # noqa: E402  (import after monkeypatch so it picks up the fakes)

TEST_STORE_DIR = Path(__file__).parent / ".chroma_test_naive_rag"
shutil.rmtree(TEST_STORE_DIR, ignore_errors=True)

chunks = chunk_corpus()
store = VectorStore(persist_dir=TEST_STORE_DIR)
store.reset()
store.add_chunks(chunks)
print(f"Indexed {store.count()} chunks for the test store.\n")

failures = []

# --- retrieve() correctness ---
target = next(c for c in chunks if c.chunk_id == "delta_dairy_co::2.2")
results = naive_rag.retrieve(store, target.text, n_results=3)
print(f"retrieve() self-match test: top result = {results[0]['chunk_id']}")
if results[0]["chunk_id"] != target.chunk_id:
    failures.append(f"retrieve() self-match failed: got {results[0]['chunk_id']}")

# --- retrieve() respects where= filtering, same as the vector store test ---
filtered = naive_rag.retrieve(store, "delivery terms", n_results=5, where={"supplier_name": "Nile Fresh Produce"})
print(f"retrieve() with where= filter: {len(filtered)} results, all Nile Fresh: "
      f"{all(r['metadata'].get('supplier_name') == 'Nile Fresh Produce' for r in filtered)}")
if any(r["metadata"].get("supplier_name") != "Nile Fresh Produce" for r in filtered):
    failures.append("retrieve() where= filter leaked a chunk from a different supplier")


# --- generate() prompt assembly, with a mock LLM instead of a real call ---
class _CapturingFakeLLM:
    """Stands in for ChatGoogleGenerativeAI. Records exactly what prompt it
    was called with, so the test can assert the retrieved chunk text
    actually made it into the prompt sent to the model — proving grounding
    without spending a real generation call."""
    def __init__(self):
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        class _FakeResponse:
            content = "FAKE ANSWER — this is a mock response, not a real Gemini call."
        return _FakeResponse()


fake_llm = _CapturingFakeLLM()
test_chunks = naive_rag.retrieve(store, target.text, n_results=2)
answer = naive_rag.generate("What is the storage temperature for feta?", test_chunks, llm=fake_llm)

print(f"\ngenerate() returned: {answer!r}")
user_prompt = fake_llm.last_messages[1]["content"]
print(f"Prompt sent to LLM includes retrieved chunk text: "
      f"{target.text[:40] in user_prompt if test_chunks and test_chunks[0]['chunk_id'] == target.chunk_id else 'N/A (different top chunk, checking generically)'}")

# Generic grounding check: EVERY retrieved chunk's text must appear in the prompt.
missing_from_prompt = [c["chunk_id"] for c in test_chunks if c["text"] not in user_prompt]
if missing_from_prompt:
    failures.append(f"generate() prompt is missing retrieved chunk text for: {missing_from_prompt}")
else:
    print("PASS: every retrieved chunk's full text is present in the prompt sent to the LLM.")

if answer != "FAKE ANSWER — this is a mock response, not a real Gemini call.":
    failures.append("generate() did not return the mock LLM's response — llm= injection isn't working")
else:
    print("PASS: generate() correctly used the injected mock LLM instead of constructing a real one.")

# --- empty-retrieval edge case: no chunks found ---
empty_answer_prompt = naive_rag._build_prompt("unanswerable question", [])
if "(no chunks retrieved)" not in empty_answer_prompt:
    failures.append("_build_prompt does not handle the empty-chunks case explicitly")
else:
    print("PASS: empty retrieval is handled explicitly, not silently.")

print()
if failures:
    for f in failures:
        print(f"FAIL: {f}")
    raise SystemExit(1)
else:
    print("=== ALL TESTS PASSED ===")