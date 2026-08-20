"""
planning_eval/smoke_test_token_counting.py — isolated live check for the
Fix #7 token-counting change in llm_counter.py.

Does NOT run the full comparison suite (no MCP server connection needed,
no db). Makes exactly 2 real Gemini calls: one plain .invoke() (via
plan_and_solve, to prove the pre-existing path still works — a regression
check) and one .with_structured_output().invoke() (via decompose_goal, the
actual path Fix #7 changed). Asserts tokens are real non-zero numbers on
both, and specifically catches the "still 0" bug the fix was written for.

Run directly, from the repo root, with the venv active:
    python planning_eval/smoke_test_token_counting.py

Requires GOOGLE_API_KEY in .env (same as every other planning script).
Costs ~2 small Gemini calls — nowhere near your daily quota.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "planning"))

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from llm_counter import CallStats, CountingLLM
from planning_lab.algorithms import decompose_goal, plan_and_solve

load_dotenv()


def _llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0,
        google_api_key=os.environ["GOOGLE_API_KEY"],
    )


def check_plain_invoke() -> None:
    """Regression check — plain .invoke() already worked before Fix #7 and
    must keep working exactly the same."""
    stats = CallStats()
    counting_llm = CountingLLM(_llm(), stats)

    output = plan_and_solve("What is 12 + 30?", counting_llm)  # type: ignore[arg-type]

    print(f"\n[plain .invoke() via plan_and_solve]")
    print(f"  output (truncated): {output[:80]!r}")
    print(f"  calls={stats.calls} tokens={stats.total_tokens} elapsed={stats.total_seconds:.2f}s")

    assert stats.calls == 1, f"expected 1 call, got {stats.calls}"
    assert stats.total_tokens > 0, (
        "REGRESSION: plain .invoke() token counting broke — this path worked "
        "before Fix #7 and must still work identically."
    )
    print("  PASS: plain .invoke() token counting still works")


def check_structured_output() -> None:
    """The actual thing Fix #7 changed — .with_structured_output().invoke()
    via decompose_goal, the real production call site."""
    stats = CallStats()
    counting_llm = CountingLLM(_llm(), stats)

    plan = decompose_goal(
        "Check current stock of Roma Tomatoes and report if it's low.",
        counting_llm,  # type: ignore[arg-type]
        tool_descriptions="",
    )

    print(f"\n[.with_structured_output().invoke() via decompose_goal]")
    print(f"  parsed plan goal: {plan.goal!r}")
    print(f"  task ids: {[t.id for t in plan.tasks]}")
    print(f"  calls={stats.calls} tokens={stats.total_tokens} elapsed={stats.total_seconds:.2f}s")

    assert stats.calls == 1, f"expected 1 call, got {stats.calls}"
    assert stats.total_tokens > 0, (
        "FIX #7 DID NOT WORK: structured-output call still reports 0 tokens. "
        "Check that include_raw=True is actually reaching the real "
        "ChatGoogleGenerativeAI.with_structured_output() call, and that "
        "response['raw'].usage_metadata is populated for this model/version."
    )
    print("  PASS: structured-output call now reports real tokens (Fix #7 works)")


if __name__ == "__main__":
    print("Running Fix #7 smoke test (2 real Gemini calls)...")
    check_plain_invoke()
    check_structured_output()
    print("\nALL CHECKS PASSED — safe to merge fix-token-counting.")