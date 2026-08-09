"""
context_eval/strategies.py — Context window management strategies.

Strategy 4 (recursive summarization) lives in strategies_llm.py since it's
the only one that needs an actual model call — kept separate so these 3
can be tested fast and free, with no API dependency at all.

Token counting note: we use a documented word-based approximation
(~1.3 tokens per word, a commonly cited rule of thumb) rather than an
exact tokenizer. tiktoken is OpenAI's tokenizer, not Gemini's, so using it
here would actually be LESS accurate, not more — it would silently import
the wrong model's token boundaries. Since all 4 strategies are measured
with the same approximation, the RELATIVE comparison between them (which
is what the lab's comparison table needs) stays fair even though the
absolute numbers are estimates.
"""
from transcript import TranscriptTurn


def estimate_tokens(text: str) -> int:
    """Documented approximation, not an exact tokenizer — see module
    docstring for why. Consistent across all 4 strategies -> fair
    relative comparison."""
    word_count = len(text.split())
    return round(word_count * 1.3)


def _render(turns: list[TranscriptTurn]) -> str:
    """Turns a list of turns into the actual text that would be sent to
    the model as context."""
    return "\n".join(f"[{t.role}] {t.content}" for t in turns)


def sliding_window(transcript: list[TranscriptTurn], window_size: int = 10) -> str:
    """Keep only the last N turns. Simplest strategy, cheapest, and the
    one most likely to lose an early critical fact entirely — that's the
    point of including it in the comparison, not a flaw in the
    implementation."""
    kept = transcript[-window_size:]
    return _render(kept)


def observation_masking(transcript: list[TranscriptTurn], keep_last_tool_outputs: int = 3) -> str:
    """Keep every user/assistant turn in full (dialogue is usually small),
    but only keep the FULL content of the most recent N tool-role turns.
    Older tool outputs get replaced with a short placeholder — this
    targets the actual bloat source in Copperleaf's transcripts (large
    JSON tool results), not the dialogue around them."""
    tool_indices = [i for i, t in enumerate(transcript) if t.role == "tool"]
    tool_indices_to_keep_full = set(tool_indices[-keep_last_tool_outputs:]) if tool_indices else set()

    rendered_lines = []
    for i, t in enumerate(transcript):
        if t.role == "tool" and i not in tool_indices_to_keep_full:
            rendered_lines.append(f"[{t.role}] [older tool output masked, {len(t.content)} chars omitted]")
        else:
            rendered_lines.append(f"[{t.role}] {t.content}")
    return "\n".join(rendered_lines)


def zone_based_pruning(transcript: list[TranscriptTurn], num_zones: int = 4) -> str:
    """Splits the transcript into `num_zones` chronological zones. Older
    zones get truncated more aggressively; the most recent zone is kept
    in full. Unlike sliding_window, EVERY turn still appears (nothing is
    fully dropped) — just with less detail the older it is."""
    n = len(transcript)
    zone_size = max(1, n // num_zones)
    # Truncation length per zone, oldest -> newest (last zone = full length)
    truncation_by_zone = [60, 150, 300, None]  # None = keep full

    rendered_lines = []
    for i, t in enumerate(transcript):
        zone_index = min(i // zone_size, num_zones - 1)
        max_len = truncation_by_zone[min(zone_index, len(truncation_by_zone) - 1)]
        content = t.content if max_len is None or len(t.content) <= max_len else t.content[:max_len] + "...[truncated]"
        rendered_lines.append(f"[{t.role}] {content}")
    return "\n".join(rendered_lines)