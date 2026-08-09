"""
context_eval/test_strategies_llm.py — Tests the STRUCTURE of recursive
summarization (chunk boundaries, running-summary carry-forward) using a
fake, free, deterministic summarizer. This does NOT prove the real Gemini
summarizer preserves facts well — only that the chunking/aggregation
plumbing itself is correct. The real Gemini version must be run separately
(see run_recursive_summarization_live.py) since it needs an API key.

Run:  python context_eval/test_strategies_llm.py
"""
from transcript import build_long_context_transcript, critical_fact_marker
from strategies_llm import recursive_summarization


def fake_summarize(previous_summary: str, new_chunk_text: str) -> str:
    """Deterministic stand-in: just concatenates everything verbatim
    rather than actually compressing. This lets us verify the harness
    (chunk boundaries, running-summary threading across multiple rounds)
    without spending any API calls or depending on model quality."""
    if previous_summary:
        return previous_summary + " || " + new_chunk_text
    return new_chunk_text


def main() -> None:
    print("=== RECURSIVE SUMMARIZATION STRUCTURAL TEST (fake summarizer) ===\n")

    transcript = build_long_context_transcript(noise_turns=26)
    marker = critical_fact_marker()
    print(f"Transcript: {len(transcript)} turns, critical fact at index "
          f"{[i for i, t in enumerate(transcript) if t.is_critical]}\n")

    final_context, running_summary = recursive_summarization(
        transcript, summarize_fn=fake_summarize, compact_every=10
    )

    survived = marker in final_context
    print(f"Critical fact survived (fake summarizer, verbatim-concat): {survived}")
    assert survived, (
        "With a verbatim-concatenating fake summarizer, the fact MUST survive "
        "-- if it doesn't, the chunking/carry-forward logic itself is broken, "
        "not a summarization-quality issue."
    )

    # Confirm the running summary was actually threaded through multiple
    # rounds, not just built from the last chunk alone.
    num_chunks = -(-len(transcript) // 10)  # ceil division, compact_every=10
    print(f"Expected chunks: {num_chunks} (compact_every=10, {len(transcript)} turns)")
    separator_count = running_summary.count(" || ")
    print(f"Separator count in running summary: {separator_count} "
          f"(should be {num_chunks - 2}, since chunks[:-1] means {num_chunks - 1} "
          f"chunks get folded in, joined by {num_chunks - 2} separators)")
    assert separator_count == num_chunks - 2, "running summary wasn't threaded through the expected number of rounds"

    print("\nPASS: chunk boundaries and running-summary carry-forward are structurally correct.")
    print("NOTE: this does NOT test real summarization quality -- that requires")
    print("      the live Gemini run, which needs GOOGLE_API_KEY and costs real API calls.")
    print("\n=== ALL STRUCTURAL TESTS PASSED ===")


if __name__ == "__main__":
    main()