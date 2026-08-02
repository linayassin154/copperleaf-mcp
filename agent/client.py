"""
client.py - LangChain client for the Copperleaf Kitchens MCP server.

Run:
    python agent/client.py --token <api_token>
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER_PATH = str(
    Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
)


def _build_connections(api_token: str) -> dict:
    """Create the connection settings for the MCP server."""
    return {
        "copperleaf": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [SERVER_PATH],
            "env": {**os.environ, "COPPERLEAF_API_TOKEN": api_token},
        }
    }


async def demo_handshake(client: MultiServerMCPClient) -> None:
    """Display the server information and available tools."""
    print("=" * 70)
    print("MCP HANDSHAKE")
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
            print(
                f"  - {tool.name}: "
                f"required={required}, additionalProperties={additional}"
            )

    print("=" * 70)
    print()


async def run_demo(api_token: str) -> None:
    client = MultiServerMCPClient(_build_connections(api_token))

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
        "Write off 2kg of Roma Tomatoes at branch 1, they went bad — reason is spoiled_before_use.",
        "Generate a waste report for branch 1 from 2026-07-01 to 2026-07-31.",
    ]

    for query in demo_queries:
        print("=" * 70)
        print(f"USER: {query}")
        print("=" * 70)

        response = await agent.ainvoke({"messages": query})
        final_message = response["messages"][-1]

        print(f"AGENT: {final_message.content}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Copperleaf Kitchens MCP demo agent"
    )

    parser.add_argument(
        "--token",
        default=os.environ.get("COPPERLEAF_API_TOKEN"),
        help="API token used to authenticate the session.",
    )

    args = parser.parse_args()

    if not args.token:
        print(
            "ERROR: Pass --token or set COPPERLEAF_API_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(run_demo(args.token))
