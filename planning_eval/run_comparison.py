"""
planning_eval/run_comparison.py — runs every applicable method against the
frozen test suite, saves a JSON artifact per run (extending the toolkit's
artifacts/ trace format), and prints a markdown comparison table.

Usage:
    python planning_eval/run_comparison.py --token <api_token>

Requires the MCP server's DB to be reachable the normal way (same as
agent/planning_client.py) and GOOGLE_API_KEY set via .env.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "planning"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from planning_lab.algorithms import (
    decompose_goal,
    dynamic_decomposition,
    execute_plan,
    final_output,
    plan_and_solve,
    reflect_and_refine,
    reflexion,
)
from planning_lab.algorithms.environment import CopperleafEnvironment
from planning_lab.algorithms.tree_of_thoughts import tree_of_thoughts
from planning_lab.algorithms.lats import lats

from llm_counter import CallStats, CountingLLM
from test_cases import TEST_CASES
import time as _time

from client import _build_connections  # noqa: E402

load_dotenv()

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


def _tool_descriptions(tools) -> str:
    return "\n".join(f"- {t.name}: {t.description}" for t in tools)


def _base_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0,
        google_api_key=os.environ["GOOGLE_API_KEY"],
    )


async def run_decomposition_pair(case: dict, tools_by_name: dict, descriptions: str) -> dict:
    """Run the same goal through decomposition-first AND dynamic
    decomposition, recording calls/tokens/latency/success for each."""
    results = {}

    for method_name, run_fn in [
        ("decomposition_first", _run_decomposition_first),
        ("dynamic", _run_dynamic),
    ]:
        stats = CallStats()
        llm = _base_llm()
        counting_llm = CountingLLM(llm, stats)
        start = time.perf_counter()
        try:
            output = await run_fn(case["goal"], counting_llm, tools_by_name, descriptions)
            success = bool(output) and "error" not in output.lower()
        except Exception as e:  # noqa: BLE001 — eval harness must not crash on one bad case
            output = f"ERROR: {e}"
            success = False
        elapsed = time.perf_counter() - start
        results[method_name] = {
            "output": output,
            "success": success,
            "llm_calls": stats.calls,
            "total_tokens": stats.total_tokens,
            "latency_s": round(elapsed, 3),
        }
        _save_artifact(case["id"], method_name, results[method_name])

    return results


async def _run_decomposition_first(goal, llm, tools_by_name, descriptions) -> str:
    plan = decompose_goal(goal, llm, tool_descriptions=descriptions)
    outputs = await execute_plan(plan, llm, tools=tools_by_name)
    return final_output(plan, outputs)


async def _run_dynamic(goal, llm, tools_by_name, descriptions) -> str:
    history = await dynamic_decomposition(
        goal, llm, tools=tools_by_name, tool_descriptions=descriptions
    )
    return history[-1][1] if history else ""


def run_planning_algorithm(case: dict, algorithm: str) -> dict:
    """Run one of PS / ToT / LATS directly on a reasoning task (no tools),
    used for the needs_lookahead and terminal-consequence cases."""
    stats = CallStats()
    llm = _base_llm()
    counting_llm = CountingLLM(llm, stats)
    start = time.perf_counter()
    try:
        if algorithm == "plan_and_solve":
            output = plan_and_solve(case["goal"], counting_llm)  # type: ignore[arg-type]
            success = bool(output)
        elif algorithm == "tree_of_thoughts":
            thoughts = tree_of_thoughts(case["goal"], counting_llm) # type: ignore[arg-type]
            best = max(thoughts, key=lambda t: t.score)
            output, success = best.state, True
        elif algorithm == "lats_ungrounded":
            from planning_lab.algorithms.environment import Environment
            result = lats(case["goal"], counting_llm, None, iterations=2, n_actions=2)  # type: ignore[arg-type]
            output, success = result.output, result.success 
     
        else:
            raise ValueError(algorithm)
    except Exception as e:  # noqa: BLE001
        output, success = f"ERROR: {e}", False
    elapsed = time.perf_counter() - start
    result = {
        "output": str(output)[:500],
        "success": success,
        "llm_calls": stats.calls,
        "total_tokens": stats.total_tokens,
        "latency_s": round(elapsed, 3),
    }
    _save_artifact(case["id"], algorithm, result)
    return result


def run_self_correction(case: dict) -> dict:
    """Self-Refine (cheap single retry) vs Reflexion (multi-trial, real
    grounded environment) on the same reflexion-category case."""
    results = {}

    # Self-Refine
    stats = CallStats()
    llm = _base_llm()
    counting_llm = CountingLLM(llm, stats)
    start = time.perf_counter()
    try:
        draft = plan_and_solve(case["goal"], counting_llm)  # type: ignore[arg-type]
        refined = reflect_and_refine(case["goal"], draft, counting_llm)  # type: ignore[arg-type]
        output, success = refined.revised[:500], True
    except Exception as e:  # noqa: BLE001 — one bad case must not kill the run
        output, success = f"ERROR: {e}", False
    elapsed = time.perf_counter() - start
    results["self_refine"] = {
        "output": output,
        "success": success,
        "llm_calls": stats.calls,
        "total_tokens": stats.total_tokens,
        "latency_s": round(elapsed, 3),
    }
    _save_artifact(case["id"], "self_refine", results["self_refine"])

    # Reflexion, grounded
    stats = CallStats()
    llm = _base_llm()
    counting_llm = CountingLLM(llm, stats)
    start = time.perf_counter()
    try:
        result = reflexion(case["goal"], counting_llm, CopperleafEnvironment(), max_trials=3, memory_size=2)  # type: ignore[arg-type]
        output = result.output[:500] if result.output else ""
        success, trials = result.success, len(result.trials)
    except Exception as e:  # noqa: BLE001
        output, success, trials = f"ERROR: {e}", False, 0
    elapsed = time.perf_counter() - start
    results["reflexion"] = {
        "output": output,
        "success": success,
        "trials": trials,
        "llm_calls": stats.calls,
        "total_tokens": stats.total_tokens,
        "latency_s": round(elapsed, 3),
    }
    _save_artifact(case["id"], "reflexion", results["reflexion"])

    return results


def _save_artifact(case_id: str, method: str, result: dict) -> None:
    path = ARTIFACTS_DIR / f"{case_id}__{method}.json"
    path.write_text(json.dumps(result, indent=2, default=str))


def _print_table(rows: list[dict]) -> None:
    print("\n| Case | Method | Success | LLM Calls | Tokens | Latency (s) |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['case']} | {r['method']} | {r['success']} | {r['llm_calls']} | {r['total_tokens']} | {r['latency_s']} |")


async def main(token: str) -> None:
    client = MultiServerMCPClient(_build_connections(token))
    mcp_tools = await client.get_tools()
    tools_by_name = {t.name: t for t in mcp_tools}
    descriptions = _tool_descriptions(mcp_tools)

    rows = []

    for case in [*cases_for("favors_decomposition_first"), *cases_for("favors_dynamic")]:
        pair = await run_decomposition_pair(case, tools_by_name, descriptions)
        for method, r in pair.items():
            rows.append({"case": case["id"], "method": method, **r})
        _time.sleep(5)

    for case in cases_for("needs_lookahead"):
        for algo in ["plan_and_solve", "tree_of_thoughts"]:
            r = run_planning_algorithm(case, algo)
            rows.append({"case": case["id"], "method": algo, **r})
            _time.sleep(5)

    for case in cases_for("needs_reflexion"):
        for algo in ["lats_ungrounded", "lats_grounded"]:
            r = run_planning_algorithm(case, algo)
            rows.append({"case": case["id"], "method": algo, **r})
            _time.sleep(5)
        sc = run_self_correction(case)
        for method, r in sc.items():
            rows.append({"case": case["id"], "method": method, **r})
        _time.sleep(5)

    _print_table(rows)
    (Path(__file__).resolve().parent / "comparison_results.json").write_text(
        json.dumps(rows, indent=2, default=str)
    )
    print(f"\nSaved {len(rows)} rows to planning_eval/comparison_results.json and {ARTIFACTS_DIR}/")


def cases_for(category: str) -> list[dict]:
    return [c for c in TEST_CASES if c["category"] == category]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True)
    args = p.parse_args()
    asyncio.run(main(args.token))