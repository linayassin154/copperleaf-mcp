"""
agent/planning_client.py - Entry point for Copperleaf's decomposition/planning
agent. Separate from agent/client.py (the memory/RAG agent) — shares the same
mcp_server/ connection pattern and staff auth, but a different code path
entirely, per the lab's requirement not to touch the memory/RAG agent.
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "planning"))
from planning_lab.algorithms import decompose_goal, execute_plan, final_output, reflect_and_refine

# Reuse the exact same connection builder agent/client.py already uses —
# import it directly rather than duplicating connection logic.
from client import _build_connections  # same mcp_server/ connection as Session 3's agent

load_dotenv()


def _tool_descriptions(tools) -> str:
    return "\n".join(f"- {t.name}: {t.description}" for t in tools)


async def run_planning_demo(api_token: str, goal: str) -> None:
    client = MultiServerMCPClient(_build_connections(api_token))
    mcp_tools = await client.get_tools()
    tools_by_name = {t.name: t for t in mcp_tools}
    descriptions = _tool_descriptions(mcp_tools)

    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0,
        google_api_key=os.environ["GOOGLE_API_KEY"],
    )

    print(f"Planning agent has {len(mcp_tools)} real MCP tools available:\n{descriptions}\n")

    plan = decompose_goal(goal, llm, tool_descriptions=descriptions)
    print("Execution batches:", plan.execution_batches())

    # execute_plan is async (it awaits tool.ainvoke(...) for real MCP tool
    # calls), so it must be awaited here, not called directly.
    outputs = await execute_plan(plan, llm, tools=tools_by_name)
    draft = final_output(plan, outputs)
    reflection = reflect_and_refine(goal, draft, llm)

    print("\n=== TASK OUTPUTS ===")
    for task_id, output in outputs.items():
        print(f"[{task_id}] {output}\n")

    print("=== FINAL RESULT ===")
    print(reflection.revised)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True)
    p.add_argument(
        "--goal",
        default="Branch 2 got a large catering order needing 15kg of Roma Tomatoes and 8kg of Feta by Thursday. Figure out how to cover it.",
    )
    args = p.parse_args()
    asyncio.run(run_planning_demo(args.token, args.goal))