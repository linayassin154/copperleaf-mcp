"""
client.py - Client for the Copperleaf Kitchens MCP server.

Run:
    python agent/client.py --token <api_token>
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext
from mcp.types import ElicitRequestParams, ElicitResult, ServerNotification

from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.callbacks import Callbacks, CallbackContext

SERVER_PATH = str(
    Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
)


def _server_params(api_token: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[SERVER_PATH],
        env={**os.environ, "COPPERLEAF_API_TOKEN": api_token},
    )


def _build_connections(api_token: str) -> dict:
    return {
        "copperleaf": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [SERVER_PATH],
            "env": {**os.environ, "COPPERLEAF_API_TOKEN": api_token},
        }
    }


def _ask_console_yes_no(message: str) -> bool:
    while True:
        answer = input(f"\n  >>> MANAGER CONFIRMATION REQUIRED <<<\n  {message}\n  Approve? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")


async def raw_elicitation_callback(context: RequestContext, params: ElicitRequestParams) -> ElicitResult:
    approved = await asyncio.to_thread(_ask_console_yes_no, params.message)
    if approved:
        return ElicitResult(action="accept", content={"confirm": True})
    return ElicitResult(action="decline")


async def langchain_elicitation_callback(
    mcp_context: RequestContext, params: ElicitRequestParams, context: CallbackContext
) -> ElicitResult:
    approved = await asyncio.to_thread(_ask_console_yes_no, params.message)
    if approved:
        return ElicitResult(action="accept", content={"confirm": True})
    return ElicitResult(action="decline")


async def notification_message_handler(message) -> None:
    if isinstance(message, ServerNotification):
        print(f"\n  [notification received] {type(message.root).__name__} - tool list changed, re-checking...")


async def demo_protocol_concerns(api_token: str) -> None:
    print("=" * 70)
    print("PART 1 - PROTOCOL CONCERNS DEMO (persistent session)")
    print("=" * 70)

    async with stdio_client(_server_params(api_token)) as (read, write):
        async with ClientSession(
            read, write,
            elicitation_callback=raw_elicitation_callback,
            message_handler=notification_message_handler,
        ) as session:
            init_result = await session.initialize()
            print(f"\n[initialize] protocolVersion={init_result.protocolVersion}")
            print(f"[initialize] serverInfo={init_result.serverInfo}")
            print(f"[initialize] capabilities={init_result.capabilities}")

            tools_before = await session.list_tools()
            print(f"\n[tools/list] {[t.name for t in tools_before.tools]}")

            print("\n--- RESOURCES ---")
            resources = await session.list_resources()
            for r in resources.resources:
                print(f"  {r.uri} - {r.name}")
            if resources.resources:
                content = await session.read_resource(resources.resources[0].uri)
                print(f"  Content preview: {content.contents[0].text[:120]}...")

            print("\n--- PROMPTS ---")
            prompts = await session.list_prompts()
            for p in prompts.prompts:
                print(f"  {p.name} - {p.description}")
            if prompts.prompts:
                rendered = await session.get_prompt(
                    "draft_waste_explanation",
                    {"item_name": "Roma Tomatoes", "quantity": "2kg", "reason": "spoiled_before_use"},
                )
                print(f"  Rendered: {rendered.messages[0].content.text[:100]}...")

            print("\n--- NOTIFICATIONS ---")
            names_before = sorted(t.name for t in tools_before.tools)
            if "expedite_reorder" in names_before:
                print("  expedite_reorder is already visible (this branch already has")
                print("  a low-stock item) - skipping the live-crossing demo below.")
            else:
                import json
                inv_result = await session.call_tool("get_inventory", {"branch_id": 1})
                items = [json.loads(block.text) for block in inv_result.content]
                candidates = [
                    it for it in items
                    if it["current_quantity"] > it["reorder_threshold"]
                    and (it["current_quantity"] - it["reorder_threshold"]) * it["unit_cost"] < 200
                ]
                if not candidates:
                    print("  No safe candidate item found for a live crossing demo right now.")
                else:
                    target = min(candidates, key=lambda it: it["current_quantity"] - it["reorder_threshold"])
                    margin = round(target["current_quantity"] - target["reorder_threshold"], 2)
                    write_off_qty = margin if margin > 0 else 0.01
                    print(f"  Target: {target['name']} (item_id={target['item_id']}), "
                          f"stock={target['current_quantity']}, threshold={target['reorder_threshold']}")
                    print(f"  Writing off {write_off_qty} to push it at/below threshold...")
                    result = await session.call_tool(
                        "write_off_inventory",
                        {"item_id": target["item_id"], "quantity": write_off_qty, "reason": "spoiled_before_use"},
                    )
                    print(f"  Result: {result.content[0].text}")
                    await asyncio.sleep(0.2)
                    tools_after = await session.list_tools()
                    names_after = sorted(t.name for t in tools_after.tools)
                    print(f"  Tools now: {names_after}")

            print("\n--- ELICITATION ---")
            import json
            inv_result = await session.call_tool("get_inventory", {"branch_id": 1})
            items = [json.loads(block.text) for block in inv_result.content]
            high_cost_candidates = [
                it for it in items
                if it["current_quantity"] * it["unit_cost"] >= 200 and it["unit_cost"] > 0
            ]
            if not high_cost_candidates:
                print("  No item currently has enough stock*cost to demo the $200 threshold.")
            else:
                target = high_cost_candidates[0]
                qty_for_200 = round((200 / target["unit_cost"]) + 1, 2)
                qty_for_200 = min(qty_for_200, target["current_quantity"])
                print(f"  Writing off {qty_for_200} of {target['name']} "
                      f"(cost impact ~{qty_for_200 * target['unit_cost']:.2f}, over the $200 threshold)...")
                result = await session.call_tool(
                    "write_off_inventory",
                    {"item_id": target["item_id"], "quantity": qty_for_200, "reason": "damaged_in_delivery"},
                )
                print(f"  Result: {result.content[0].text}")

    print("\n" + "=" * 70)
    print("PART 1 COMPLETE")
    print("=" * 70 + "\n")


async def demo_handshake(client: MultiServerMCPClient) -> None:
    print("=" * 70)
    print("PART 2 - LANGCHAIN AGENT DEMO - HANDSHAKE")
    print("=" * 70)

    async with client.session("copperleaf") as session:
        init_result = await session.initialize()
        print(f"Protocol Version: {init_result.protocolVersion}")
        print(f"Server: {init_result.serverInfo}")
        print(f"Capabilities: {init_result.capabilities}")

        tools_result = await session.list_tools()
        print(f"\nAvailable Tools ({len(tools_result.tools)}):")
        for tool in tools_result.tools:
            required = tool.inputSchema.get("required", [])
            additional = tool.inputSchema.get("additionalProperties")
            print(f"  - {tool.name}: required={required}, additionalProperties={additional}")

    print("=" * 70)
    print()


async def run_agent_demo(api_token: str) -> None:
    client = MultiServerMCPClient(
        _build_connections(api_token),
        callbacks=Callbacks(on_elicitation=langchain_elicitation_callback),
    )

    await demo_handshake(client)

    tools = await client.get_tools()
    print(f"LangChain agent has {len(tools)} tools available.\n")

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=os.environ["GROQ_API_KEY"],
    )

    agent = create_agent(llm, tools)

    demo_queries = [
        "Is Roma Tomatoes running low on stock at branch 1?",
        "Write off 2kg of Roma Tomatoes at branch 1, they went bad - reason is spoiled_before_use.",
        "Generate a waste report for branch 1 from 2026-07-01 to 2026-07-31.",
    ]

    for query in demo_queries:
        print("=" * 70)
        print(f"USER: {query}")
        print("=" * 70)

        response = await agent.ainvoke({"messages": query})
        final_message = response["messages"][-1]

        print(f"AGENT: {final_message.content}\n")


async def run_demo(api_token: str) -> None:
    await demo_protocol_concerns(api_token)
    await run_agent_demo(api_token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copperleaf Kitchens MCP demo client")
    parser.add_argument(
        "--token",
        default=os.environ.get("COPPERLEAF_API_TOKEN"),
        help="API token used to authenticate the session.",
    )
    parser.add_argument(
        "--part",
        choices=["protocol", "agent", "both"],
        default="both",
    )
    args = parser.parse_args()

    if not args.token:
        print("ERROR: Pass --token or set COPPERLEAF_API_TOKEN.", file=sys.stderr)
        sys.exit(1)

    if args.part == "protocol":
        asyncio.run(demo_protocol_concerns(args.token))
    elif args.part == "agent":
        asyncio.run(run_agent_demo(args.token))
    else:
        asyncio.run(run_demo(args.token))
