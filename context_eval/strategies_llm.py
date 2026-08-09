"""
context_eval/strategies_llm.py — Recursive summarization, the one context
management strategy that needs an actual model call.

Design: split the transcript into chunks of `compact_every` turns. Every
chunk EXCEPT the most recent gets folded into a running summary (each new
chunk is summarized together with the summary-so-far, so facts from chunk
1 have to survive being re-summarized again when chunk 2 arrives, and
again at chunk 3, etc — this is the real test of whether the strategy
actually holds up over a long conversation, not just once). The most
recent chunk is kept in full, unsummarized detail.

`summarize_fn` is injected rather than hardcoded, specifically so the
chunking/aggregation logic itself (the part that can go structurally
wrong — off-by-one chunk boundaries, losing the running summary, etc) can
be tested with a fast, free, deterministic fake — see test_strategies_llm.py.
The real Gemini-backed summarizer is `gemini_summarize` below.
"""
from transcript import TranscriptTurn


def _render(turns: list[TranscriptTurn]) -> str:
    return "\n".join(f"[{t.role}] {t.content}" for t in turns)


def recursive_summarization(
    transcript: list[TranscriptTurn],
    summarize_fn,
    compact_every: int = 10,
) -> tuple[str, str]:
    """Returns (final_context_text, final_running_summary). summarize_fn
    must have signature (previous_summary: str, new_chunk_text: str) -> str."""
    if not transcript:
        return "", ""

    chunks = [transcript[i:i + compact_every] for i in range(0, len(transcript), compact_every)]
    running_summary = ""

    # Every chunk except the last gets folded into the running summary.
    for chunk in chunks[:-1]:
        chunk_text = _render(chunk)
        running_summary = summarize_fn(running_summary, chunk_text)

    # The most recent chunk stays in full, unsummarized detail.
    last_chunk_text = _render(chunks[-1]) if chunks else ""

    final_context = (
        f"[SUMMARY OF EARLIER CONVERSATION]\n{running_summary}\n\n"
        f"[RECENT TURNS - FULL DETAIL]\n{last_chunk_text}"
    )
    return final_context, running_summary


def gemini_summarize(previous_summary: str, new_chunk_text: str) -> str:
    """The REAL summarizer, using Gemini via langchain_google_genai — same
    model/setup already used in agent/client.py. Requires GOOGLE_API_KEY
    in .env. This is the only part of this file that costs an API call."""
    import os
    from dotenv import load_dotenv
    from langchain_google_genai import ChatGoogleGenerativeAI

    load_dotenv()
    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0,
        max_tokens=400,
        google_api_key=os.environ["GOOGLE_API_KEY"],
    )

    prompt = (
        "You are compacting a long operational conversation for an inventory "
        "management assistant. Combine the PREVIOUS SUMMARY with the NEW "
        "TURNS below into one updated, concise summary.\n\n"
        "CRITICAL: preserve exact item names, supplier names, dates, and any "
        "flagged food-safety or quality issues VERBATIM — do not paraphrase "
        "specific facts into vague language (e.g. keep 'Prime Ribeye', not "
        "'an item'). Routine/repetitive inventory checks can be compressed "
        "heavily or dropped if they contain no notable finding.\n\n"
        f"PREVIOUS SUMMARY:\n{previous_summary or '(none yet)'}\n\n"
        f"NEW TURNS:\n{new_chunk_text}\n\n"
        "UPDATED SUMMARY:"
    )
    response = llm.invoke(prompt)
    return _extract_text(response.content)


def _extract_text(content) -> str:
    """Gemini's responses via langchain_google_genai can come back as a
    plain string OR as a list of content blocks (e.g.
    [{'type': 'text', 'text': '...'}]). Without this, the raw Python
    structure gets embedded as literal text in the summary -- a real bug
    caught from an actual live run, not a hypothetical one."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)