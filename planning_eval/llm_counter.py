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
        self._stats.record(time.perf_counter() - start, _extract_tokens(response))
        return response

    def with_structured_output(self, schema, **kwargs):
        return _CountingStructured(self._llm.with_structured_output(schema, **kwargs), self._stats)


class _CountingStructured:
    def __init__(self, structured_runnable, stats: CallStats):
        self._runnable = structured_runnable
        self._stats = stats

    def invoke(self, messages, **kwargs):
        start = time.perf_counter()
        response = self._runnable.invoke(messages, **kwargs)
        # Structured outputs don't carry usage_metadata the same way;
        # record the call with 0 tokens rather than skipping it, so call
        # counts stay accurate even when token counts can't be.
        self._stats.record(time.perf_counter() - start, 0)
        return response