"""
context_eval/run_recursive_summarization_live.py — Runs recursive
summarization for REAL against Gemini (not the fake summarizer used in
test_strategies_llm.py). This is the actual evidence for the comparison
table's "recursive summarization" row. Costs real API calls (3, one per
folded chunk) and needs GOOGLE_API_KEY in .env.

Run:  python context_eval/run_recursive_summarization_live.py
"""
import time

from transcript import build_long_context_transcript, critical_fact_marker
from strategies_llm import recursive_summarization, gemini_summarize
from strategies import estimate_tokens


def main() -> None:
    print("=== RECURSIVE SUMMARIZATION -- LIVE GEMINI RUN ===\n")

    transcript = build_long_context_transcript(noise_turns=26)
    marker = critical_fact_marker()

    start = time.time()
    final_context, running_summary = recursive_summarization(
        transcript, summarize_fn=gemini_summarize, compact_every=10
    )
    elapsed = time.time() - start

    print("--- Final running summary (after 3 rounds of real Gemini compaction) ---")
    print(running_summary)
    print("\n--- Final context sent to the model (summary + most recent chunk) ---")
    print(final_context[:500] + ("..." if len(final_context) > 500 else ""))

    survived = marker in final_context
    tokens = estimate_tokens(final_context)

    print(f"\nCritical fact ({marker!r}) survived real Gemini summarization: {survived}")
    print(f"Final context size: ~{tokens} tokens")
    print(f"Latency: {elapsed:.2f}s for 3 summarization calls")

    if not survived:
        print(
            "\nNOTE: if this is False, Gemini paraphrased the specific detail "
            "away despite the prompt instruction to preserve it verbatim -- "
            "that's a genuine, useful finding for the comparison table (it "
            "means recursive summarization's real weakness here is fact "
            "drift across rounds), not a bug to hide."
        )

    print("\n=== LIVE RUN COMPLETE ===")


if __name__ == "__main__":
    main()