"""
client.py - Client for the Copperleaf Kitchens MCP server.

Run:
    python agent/client.py --token <api_token>

--- Why this file has TWO demo paths ---
langchain-mcp-adapters (MultiServerMCPClient) opens a NEW MCP session for
EVERY tool call — this is documented behavior, not a bug we're working
around blindly (see get_tools()'s own docstring: "A new session will be
created for each tool call"). That has a real consequence, confirmed by
testing both paths directly against this server:

  - Elicitation still works fine through that ephemeral-session model,
    because ctx.elicit(...) is a synchronous request/response that
    completes WITHIN a single tool call, before that call's session closes.
  - tools/list_changed notifications do NOT reliably reach a client this
    way. The notification is a separate, asynchronous push — and testing
    confirmed the ephemeral session is already torn down (or never pumping
    its read loop long enough) by the time a client-side handler could act
    on it. A message_handler wired into that path never fired in testing,
    even though the server-side push genuinely happened.

So: PART 1 (demo_protocol_concerns) uses a single persistent raw
ClientSession — the only way to reliably demonstrate a live
tools/list_changed push and a client reacting to it, per the lab's Demo
Checklist. It also drives elicitation through real console input, so
running this script gives an actual human-in-the-loop confirmation, not a
canned auto-accept.

PART 2 (run_agent_demo) is the natural-language LangChain agent demo.
Elicitation is wired in the same way (real console prompt) and works
correctly there too. Notifications are not demonstrated through this path
for the reason above — expedite_reorder still becomes usable by the agent
once tools are refreshed, just not via a live push mid-conversation.
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import RateLimitError

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext
from mcp.types import ElicitRequestParams, ElicitResult, ServerNotification
# --- Session 3+ additions: memory + RAG, wired into the live agent loop ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "memory"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rag"))

from short_term import ShortTermMemory, Scratchpad
from router import PromoteOrDropRouter
from episodic import EpisodicStore
from semantic import SemanticStore
from consolidation import ConsolidationPass

from chunking import chunk_corpus
from vector_store import VectorStore
from bm25_store import BM25Store
import hybrid_rag
import self_rag

from langchain.tools import tool
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.callbacks import Callbacks, CallbackContext

load_dotenv()

# Repo root — used as the working directory for the server subprocess below,
# so `python -m mcp_server.server` can find the mcp_server package.
REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def _server_params(api_token: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        # Launched as a MODULE (-m mcp_server.server), not a script path.
        # Running it as a bare script (args=[".../mcp_server/server.py"])
        # puts mcp_server/'s own folder on sys.path instead of the repo
        # root above it, so `import mcp_server.auth` etc. inside server.py
        # would fail with "ModuleNotFoundError: No module named 'mcp_server'".
        # -m plus cwd=REPO_ROOT makes the package resolve correctly.
        args=["-m", "mcp_server.server"],
        cwd=REPO_ROOT,
        env={**os.environ, "COPPERLEAF_API_TOKEN": api_token},
    )


def _build_connections(api_token: str) -> dict:
    """Connection settings for the LangChain-facing MultiServerMCPClient."""
    return {
        "copperleaf": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_server.server"],
            "cwd": REPO_ROOT,
            "env": {**os.environ, "COPPERLEAF_API_TOKEN": api_token},
        }
    }


# ---------------------------------------------------------------------
# Shared elicitation handling — real console input, not an auto-accept.
# ---------------------------------------------------------------------

def _ask_console_yes_no(message: str) -> bool:
    """Blocking console prompt. Fine for a demo script — the person running
    it IS the manager being asked to confirm."""
    while True:
        print(f"\n  >>> MANAGER CONFIRMATION REQUIRED <<<\n  {message}\n  Approve? [y/n]: ", end="", flush=True)
        answer = input().strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")

async def raw_elicitation_callback(context: RequestContext, params: ElicitRequestParams) -> ElicitResult:
    """Used by the persistent-session demo (Part 1)."""
    approved = await asyncio.to_thread(_ask_console_yes_no, params.message)
    if approved:
        return ElicitResult(action="accept", content={"confirm": True})
    return ElicitResult(action="decline")


async def langchain_elicitation_callback(
    mcp_context: RequestContext, params: ElicitRequestParams, context: CallbackContext
) -> ElicitResult:
    """Used by the LangChain agent demo (Part 2) — same real prompt, just
    matching langchain-mcp-adapters' 3-argument callback shape."""
    approved = await asyncio.to_thread(_ask_console_yes_no, params.message)
    if approved:
        return ElicitResult(action="accept", content={"confirm": True})
    return ElicitResult(action="decline")


async def notification_message_handler(message) -> None:
    """Used by the persistent-session demo (Part 1) to print real
    notifications as they arrive, instead of silently swallowing them."""
    if isinstance(message, ServerNotification):
        print(f"\n  [notification received] {type(message.root).__name__} — tool list changed, re-checking...")


# ---------------------------------------------------------------------
# PART 1 — Persistent-session protocol demo.
# Proves every protocol concern actually fires, per the Demo Checklist.
# ---------------------------------------------------------------------

async def demo_protocol_concerns(api_token: str) -> None:
    print("=" * 70)
    print("PART 1 — PROTOCOL CONCERNS DEMO (persistent session)")
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
                print(f"  {r.uri} — {r.name}")
            if resources.resources:
                content = await session.read_resource(resources.resources[0].uri)
                print(f"  Content preview: {content.contents[0].text[:120]}...")

            print("\n--- PROMPTS ---")
            prompts = await session.list_prompts()
            for p in prompts.prompts:
                print(f"  {p.name} — {p.description}")
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
                print("  a low-stock item) — skipping the live-crossing demo below,")
                print("  since there's nothing left to cross.")
            else:
                import json
                inv_result = await session.call_tool("get_inventory", {"branch_id": 1})
                items = [json.loads(block.text) for block in inv_result.content]
                # Pick the item with the smallest positive margin above its
                # threshold, among ones cheap enough that writing off exactly
                # that margin stays under the elicitation threshold — keeps
                # this demo step isolated to ONLY the notification concern.
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
                    print(f"  expedite_reorder appeared: {'expedite_reorder' in names_after and 'expedite_reorder' not in names_before}")

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
                print("  This will pause and ask YOU to confirm below, as the connected manager.")
                result = await session.call_tool(
                    "write_off_inventory",
                    {"item_id": target["item_id"], "quantity": qty_for_200, "reason": "damaged_in_delivery"},
                )
                print(f"  Result: {result.content[0].text}")

    print("\n" + "=" * 70)
    print("PART 1 COMPLETE")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------
# PART 2 — LangChain conversational agent demo.
# ---------------------------------------------------------------------

async def demo_handshake(client: MultiServerMCPClient) -> None:
    print("=" * 70)
    print("PART 2 — LANGCHAIN AGENT DEMO — HANDSHAKE")
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

def _build_memory_and_rag_tools():
    """Builds the memory/RAG state + the two LangChain tools that expose
    them to the agent, plus the STM/router/consolidation objects the
    caller needs to drive the loop. Returns everything as one bundle so
    run_agent_demo can wire them into the actual conversation."""
    episodic_store = EpisodicStore()
    semantic_store = SemanticStore()
    router = PromoteOrDropRouter(episodic_store)
    stm = ShortTermMemory(max_turns=12, on_evict=router.handle_eviction)
    scratchpad = Scratchpad()
    consolidation = ConsolidationPass(episodic_store, semantic_store)

    chunks = chunk_corpus()
    vector_store = VectorStore()
    vector_store.reset()
    vector_store.add_chunks(chunks)
    bm25_store = BM25Store(chunks)

    @tool
    def search_knowledge_base(query: str) -> str:
        """Search food-safety storage policy and supplier contract
        documents for facts not available from inventory tools —
        temperature requirements, contract terms, delivery windows,
        return/remediation policy. Use this for policy/contract
        questions, never for live stock levels (use get_inventory)."""
        result = hybrid_rag.answer_question(vector_store, bm25_store, query, n_results=4)
        verification = self_rag.verify_answer(
            result.answer, result.retrieved_chunks, semantic_store=semantic_store
        )
        return verification.final_answer

    @tool
    def recall_related_history(topic: str) -> str:
        """Recall known facts about a supplier from prior sessions'
        memory — e.g. their delivery reliability pattern. Use this
        before concluding a delivery problem is new; it may already be
        a known, recurring issue."""
        lines = []
        for supplier in ("Nile Fresh Produce", "Delta Dairy Co.", "Coastal Seafood & Meats"):
            if supplier.lower() not in topic.lower():
                continue
            fact = semantic_store.current(supplier, "delivery_status")
            if fact is not None:
                lines.append(
                    f"{supplier}: delivery_status = {fact.value} "
                    f"(v{fact.version}, {len(fact.source_episode_contents)} supporting episode(s))"
                )
        return "\n".join(lines) if lines else "No prior memory found for that topic."

    return {
        "stm": stm,
        "scratchpad": scratchpad,
        "router": router,
        "episodic_store": episodic_store,
        "semantic_store": semantic_store,
        "consolidation": consolidation,
        "tools": [search_knowledge_base, recall_related_history],
    }
async def run_agent_demo(api_token: str) -> None:
    client = MultiServerMCPClient(
        _build_connections(api_token),
        callbacks=Callbacks(on_elicitation=langchain_elicitation_callback),
    )

    await demo_handshake(client)

    mcp_tools = await client.get_tools()

    memory_bundle = _build_memory_and_rag_tools()
    tools = mcp_tools + memory_bundle["tools"]
    print(f"LangChain agent has {len(tools)} tools available "
          f"({len(mcp_tools)} MCP + {len(memory_bundle['tools'])} memory/RAG).\n")
    print(f"LangChain agent has {len(tools)} tools available.\n")
    print("NOTE: this list was captured once, at startup. If a write-off during")
    print("this demo triggers a low-stock crossing, expedite_reorder becomes")
    print("callable on the server immediately, but this agent's tool list won't")
    print("refresh automatically mid-conversation (see module docstring for why —")
    print("langchain-mcp-adapters opens a fresh session per call, so the live")
    print("tools/list_changed push isn't observed here the way it is in Part 1).\n")

    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        temperature=0,
        max_tokens=1024,
        google_api_key=os.environ["GOOGLE_API_KEY"],
    )

    agent = create_agent(llm, tools)

    demo_queries = [
        "Is Roma Tomatoes running low on stock at branch 1?",
        "Write off 2kg of Roma Tomatoes at branch 1, they went bad — reason is spoiled_before_use.",
        "Generate a waste report for branch 1 from 2026-07-01 to 2026-07-31.",
        "Has Nile Fresh Produce been delivering on time lately? Also, what does their contract say about late deliveries?",
    ]

    for i, query in enumerate(demo_queries):
        print("=" * 70)
        print(f"USER: {query}")
        print("=" * 70)

        response = await _invoke_with_retry(agent, query)

        final_message = response["messages"][-1]

        print(f"AGENT: {final_message.content}\n")

        # Small courtesy pause between queries to stay under Groq's
        # free-tier rate limit — NOT the reason a single call is slow.
        # If a call gets rate-limited anyway, _invoke_with_retry handles
        # that separately by reading the real wait time Groq returns.
        if i < len(demo_queries) - 1:
            await asyncio.sleep(3)
    # --- NEW: periodic consolidation pass, run once at the end of the
    # session (never per-turn — see consolidation.py's docstring on why
    # that separation matters). ---
    print("=" * 70)
    print("MEMORY CONSOLIDATION (periodic pass, run once at end of session)")
    print("=" * 70)
    consolidation_log = memory_bundle["consolidation"].run()
    for line in consolidation_log:
        print(f"  {line}")
    if not consolidation_log:
        print("  No new consolidatable facts this session.")

async def _invoke_with_retry(agent, query: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await agent.ainvoke({"messages": query})

        except RateLimitError as e:
            wait_match = re.search(r"try again in ([\d.]+)s", str(e))

            wait_seconds = (
                float(wait_match.group(1)) + 2
                if wait_match
                else 30
            )

            print(
                f"  [rate limit] waiting {wait_seconds:.0f}s "
                f"before retry {attempt + 1}/{max_retries}..."
            )

            await asyncio.sleep(wait_seconds)

    raise RuntimeError(f"Still rate-limited after {max_retries} retries.")

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
        help="Run just the protocol-concerns demo, just the agent demo, or both (default).",
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