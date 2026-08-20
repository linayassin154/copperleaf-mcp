"""
planning_eval/llm_counter.py — wraps a chat model to count real LLM calls,
tokens, and latency per run, so the comparison table (Session 4 rubric row:
"Cost and quality comparison across everything") reports actual measured
numbers, not estimates.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CallStats:
    calls: int = 0
    total_tokens: int = 0
    total_seconds: float = 0.0
    details: list[dict] = field(default_factory=list)

    def record(self, elapsed: float, tokens: int) -> None:
        self.calls += 1
        self.total_tokens += tokens
        self.total_seconds += elapsed
        self.details.append({"elapsed_s": round(elapsed, 3), "tokens": tokens})

    def reset(self) -> None:
        self.calls = 0
        self.total_tokens = 0
        self.total_seconds = 0.0
        self.details = []


def _extract_tokens(response) -> int:
    """Best-effort token extraction from a langchain AIMessage. Gemini
    responses carry usage_metadata with input/output token counts."""
    meta = getattr(response, "usage_metadata", None)
    if meta:
        return int(meta.get("total_tokens", 0) or 0)
    return 0
def _normalize_content(response) -> None:
    """Gemini occasionally returns response.content as a list of content
    blocks (e.g. [{"type": "text", "text": "..."}]) instead of a plain
    string. Every planning_lab algorithm's own defensive check
    (isinstance(x, str)) then correctly rejects it as unsupported. Flatten
    it in place here, once, so every downstream .content read just works."""
    content = response.content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        response.content = "".join(parts)

class CountingLLM:
    """Proxies .invoke() and .with_structured_output() on a real chat model,
    recording every call into a shared CallStats. Every planning_lab
    algorithm function only ever calls llm.invoke(...) or
    llm.with_structured_output(...).invoke(...) — proxying both covers
    every algorithm (PS, ToT, LATS, Reflexion, Self-Refine, decomposition).
    """

    def __init__(self, llm, stats: CallStats):
        self._llm = llm
        self._stats = stats

    def invoke(self, messages, **kwargs):
        start = time.perf_counter()
        response = self._llm.invoke(messages, **kwargs)
        _normalize_content(response)
        self._stats.record(time.perf_counter() - start, _extract_tokens(response))
        return response

    def with_structured_output(self, schema, **kwargs):
        # include_raw=True is the only way langchain-core exposes the raw
        # AIMessage (and its usage_metadata) from a structured-output call —
        # without it, .invoke() returns just the parsed Pydantic object with
        # no token info attached anywhere, which is exactly what was making
        # tokens show as 0 for decomposition-first, dynamic decomposition,
        # and part of Tree of Thoughts. _CountingStructured below unwraps
        # this back to the plain parsed object so every planning_lab caller
        # (decompose_goal, dynamic_decomposition, tree_of_thoughts, ...)
        # keeps working exactly as before — this is purely an accounting
        # change, not a behavior change for callers.
        kwargs.setdefault("include_raw", True)
        return _CountingStructured(self._llm.with_structured_output(schema, **kwargs), self._stats)


class _CountingStructured:
    def __init__(self, structured_runnable, stats: CallStats):
        self._runnable = structured_runnable
        self._stats = stats

    def invoke(self, messages, **kwargs):
        start = time.perf_counter()
        response = self._runnable.invoke(messages, **kwargs)
        elapsed = time.perf_counter() - start

        # With include_raw=True the runnable always returns a dict with
        # 'raw' (the AIMessage — usage_metadata lives here), 'parsed' (the
        # schema instance, or None if parsing failed), and 'parsing_error'.
        raw = response.get("raw") if isinstance(response, dict) else None
        tokens = _extract_tokens(raw) if raw is not None else 0
        self._stats.record(elapsed, tokens)

        if isinstance(response, dict) and "parsed" in response:
            parsing_error = response.get("parsing_error")
            if parsing_error is not None:
                # Match with_structured_output(include_raw=False)'s original
                # behavior of raising on a parse failure, instead of silently
                # handing callers a None they don't expect.
                raise parsing_error
            return response["parsed"]
        # Defensive fallback — shouldn't happen with include_raw=True, but
        # never silently swallow an unexpected shape.
        return response