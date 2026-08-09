"""
context_eval/test_strategies.py — Tests the 3 deterministic (non-LLM)
context management strategies against the long-context transcript. Run:

    python context_eval/test_strategies.py

Recursive summarization (the 4th strategy, needs Gemini) is tested
separately in test_strategies_llm.py, and the full 4-way comparison table
is produced by run_comparison.py — both come in the next batch.
"""
from transcript import build_long_context_transcript, critical_fact_marker
from strategies import sliding_window, observation_masking, zone_based_pruning, estimate_tokens


def main() -> None:
    print("=== CONTEXT STRATEGIES TEST (sliding window / obs. masking / zone pruning) ===\n")

    transcript = build_long_context_transcript(noise_turns=26)
    marker = critical_fact_marker()
    original_tokens = estimate_tokens(
        "\n".join(f"[{t.role}] {t.content}" for t in transcript)
    )
    print(f"Transcript: {len(transcript)} turns, ~{original_tokens} tokens unpruned\n")

    results = {}

    # --- Sliding window ---
    sw_output = sliding_window(transcript, window_size=10)
    sw_survived = marker in sw_output
    sw_tokens = estimate_tokens(sw_output)
    results["sliding_window"] = (sw_survived, sw_tokens)
    print(f"Sliding window (last 10 turns): critical fact survived = {sw_survived}, ~{sw_tokens} tokens")

    # --- Observation masking ---
    om_output = observation_masking(transcript, keep_last_tool_outputs=3)
    om_survived = marker in om_output
    om_tokens = estimate_tokens(om_output)
    results["observation_masking"] = (om_survived, om_tokens)
    print(f"Observation masking (last 3 tool outputs full): critical fact survived = {om_survived}, ~{om_tokens} tokens")

    # --- Zone-based pruning ---
    zb_output = zone_based_pruning(transcript, num_zones=4)
    zb_survived = marker in zb_output
    zb_tokens = estimate_tokens(zb_output)
    results["zone_based_pruning"] = (zb_survived, zb_tokens)
    print(f"Zone-based pruning (4 zones): critical fact survived = {zb_survived}, ~{zb_tokens} tokens")

    print()
    # Expected outcome, matching the lab's own worked example shape:
    # sliding window on a short window LOSES the early fact (it's outside
    # the last 10 turns), the other two strategies preserve it because
    # they don't fully discard early turns, just compress them.
    assert sw_survived is False, "sliding window with window_size=10 should NOT preserve a turn-2 fact in a 38-turn transcript"
    assert om_survived is True, "observation masking protects dialogue turns in full -- the critical fact lives in an assistant turn, so it should survive even though old TOOL outputs get masked"
    assert zb_survived is True, "zone-based pruning truncates but never fully drops a turn, so the fact should survive even if shortened"

    print("PASS: sliding window loses the early fact (expected — this is its known weakness).")
    print("PASS: observation masking and zone-based pruning both preserve it.")
    print(f"\nToken cost comparison: sliding_window={sw_tokens}, observation_masking={om_tokens}, zone_based_pruning={zb_tokens}")
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()