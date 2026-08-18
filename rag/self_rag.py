"""
rag/self_rag.py - Self-RAG-style verification: checks a generated RAG
answer against BOTH (A) the retrieved context it's supposed to be
grounded in, and (B) current semantic memory, since the two can genuinely
disagree — a supplier contract PROMISES on-time delivery while semantic
memory has OBSERVED that supplier being late repeatedly. Missing either
check leaves a real failure mode uncaught: Check A alone still lets a
technically-grounded-but-outdated document answer go out unflagged;
Check B alone still lets a hallucinated document claim go out unflagged.

This is a simplified, prompt-based version of the Self-RAG paper's
reflection-token idea (ISREL/ISSUP), not a fine-tuned reflection model —
stated explicitly so it's clear this is a deliberate scope choice for a
prompted system, not a misunderstanding of the original approach.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain_google_genai import ChatGoogleGenerativeAI

from rag.naive_rag import GENERATION_MODEL, _extract_text
from memory.consolidation import _KNOWN_SUPPLIERS  # reuse, don't reinvent
from memory.semantic import SemanticStore
GROUNDEDNESS_PROMPT = (
    "You are checking whether an answer is fully supported by retrieved "
    "context, with no unsupported claims added.\n\n"
    "Retrieved context:\n{context}\n\n"
    "Answer to check:\n{answer}\n\n"
    "Respond with ONLY JSON, no markdown fences:\n"
    '{{"grounded": true|false, "reasoning": "<one sentence>"}}'
)


@dataclass
class VerificationResult:
    grounded: bool
    grounding_reasoning: str
    memory_consistent: bool
    memory_conflicts: list[str] = field(default_factory=list)
    final_answer: str = ""


def _check_groundedness(answer: str, chunks: list[dict], llm: ChatGoogleGenerativeAI) -> tuple[bool, str]:
    context = "\n\n".join(c["text"] for c in chunks) or "(no context retrieved)"
    prompt = GROUNDEDNESS_PROMPT.format(context=context, answer=answer)
    response = llm.invoke([{"role": "user", "content": prompt}])
    raw = _extract_text(response).strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
        return bool(parsed.get("grounded", False)), parsed.get("reasoning", "")
    except json.JSONDecodeError:
        # Fail closed: an unparseable verification response counts as
        # ungrounded rather than silently passing the answer through.
        return False, "groundedness check response could not be parsed"


def _check_memory_consistency(answer: str, semantic_store: SemanticStore | None) -> tuple[bool, list[str]]:
    if semantic_store is None:
        return True, []

    answer_lower = answer.lower()
    conflicts: list[str] = []

    for supplier in _KNOWN_SUPPLIERS:
        if supplier.lower() not in answer_lower:
            continue
        fact = semantic_store.current(supplier, "delivery_status")
        if fact is None:
            continue
        claims_on_time = any(p in answer_lower for p in ("on time", "on-time", "reliable"))
        claims_late = any(p in answer_lower for p in ("late", "delayed", "unreliable"))
        if fact.value == "late" and claims_on_time and not claims_late:
            conflicts.append(
                f"Answer implies {supplier} delivers on time, but semantic memory's "
                f"current fact (v{fact.version}) is 'late', backed by "
                f"{len(fact.source_episode_contents)} corroborating episode(s)."
            )
        elif fact.value == "on_time" and claims_late and not claims_on_time:
            conflicts.append(
                f"Answer implies {supplier} delivers late, but semantic memory's "
                f"current fact (v{fact.version}) is 'on_time'."
            )

    return (len(conflicts) == 0), conflicts


def verify_answer(
    answer: str,
    chunks: list[dict],
    semantic_store: SemanticStore | None = None,
    llm: ChatGoogleGenerativeAI | None = None,
) -> VerificationResult:
    if llm is None:
        llm = ChatGoogleGenerativeAI(model=GENERATION_MODEL, temperature=0, max_tokens=256)

    grounded, grounding_reasoning = _check_groundedness(answer, chunks, llm)
    memory_consistent, memory_conflicts = _check_memory_consistency(answer, semantic_store)

    if grounded and memory_consistent:
        final_answer = answer
    else:
        flags = []
        if not grounded:
            flags.append(f"UNGROUNDED: {grounding_reasoning}")
        if not memory_consistent:
            flags.extend(f"MEMORY CONFLICT: {c}" for c in memory_conflicts)
        final_answer = answer + "\n\n[unverified — " + " | ".join(flags) + "]"

    return VerificationResult(
        grounded=grounded,
        grounding_reasoning=grounding_reasoning,
        memory_consistent=memory_consistent,
        memory_conflicts=memory_conflicts,
        final_answer=final_answer,
    )