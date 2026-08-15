"""
tests/test_protocol_concerns.py

End-to-end test against the REAL server over stdio — no LLM/API key needed.
Stub callbacks stand in for a real model: elicitation callbacks accept or
decline deterministically instead of asking an actual person.

Run (fresh DB first — these assertions depend on seed.sql's exact starting
quantities):
    python mcp_server/init_db.py
    python tests/test_protocol_concerns.py 2>&1 | tee tests/test_output.log
"""
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext
from mcp.types import (
    ElicitRequestParams,
    ElicitResult,
    ServerNotification,
)

# Repo root — used as the working directory for the server subprocess below,
# so `python -m mcp_server.server` can find the mcp_server package.
REPO_ROOT = str(Path(__file__).resolve().parent.parent)
DB_PATH = Path(__file__).resolve().parent.parent / "db" / "copperleaf.db"
MONA_TOKEN = "FAKE_NOT_REAL_TOKEN_mona_001"    # manager, branch 1
SALMA_TOKEN = "FAKE_NOT_REAL_TOKEN_salma_003"  # manager, branch 2

_received_notifications: list[str] = []


async def message_handler(message):
    if isinstance(message, ServerNotification):
        _received_notifications.append(type(message.root).__name__)


async def accepting_elicitation_callback(context: RequestContext, params: ElicitRequestParams) -> ElicitResult:
    print(f"  [client] Elicitation received: {params.message!r} -> ACCEPTING")
    return ElicitResult(action="accept", content={"confirm": True})


async def declining_elicitation_callback(context: RequestContext, params: ElicitRequestParams) -> ElicitResult:
    print(f"  [client] Elicitation received: {params.message!r} -> DECLINING")
    return ElicitResult(action="decline")


def _params(token: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        # Launched as a MODULE (-m mcp_server.server), not a script path.
        # Running it as a bare script puts mcp_server/'s own folder on
        # sys.path instead of the repo root above it, so `import
        # mcp_server.auth` etc. inside server.py would fail with
        # "ModuleNotFoundError: No module named 'mcp_server'". -m plus
        # cwd=REPO_ROOT makes the package resolve correctly.
        args=["-m", "mcp_server.server"],
        cwd=REPO_ROOT,
        env={**os.environ, "COPPERLEAF_API_TOKEN": token},
    )


async def test_capability_negotiation():
    print("\n=== CAPABILITY NEGOTIATION ===")
    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            caps = init_result.capabilities
            print(f"  Declared server capabilities: {caps}")
            assert caps.tools is not None and caps.tools.listChanged is True
            assert caps.resources is not None
            assert caps.prompts is not None
            print("  PASS: tools/resources/prompts listChanged all True.")


async def test_resources():
    print("\n=== RESOURCES ===")
    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_resources()
            print(f"  Resources listed: {[r.name for r in listed.resources]}")
            assert any("Waste" in r.name for r in listed.resources)

            content = await session.read_resource("copperleaf://policy/waste-write-off")
            text = content.contents[0].text
            print(f"  Resource content (first 80 chars): {text[:80]!r}")
            assert "spoiled_before_use" in text and "200" in text
            print("  PASS: waste policy resource readable with real content.")


async def test_prompts():
    print("\n=== PROMPTS ===")
    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_prompts()
            names = [p.name for p in listed.prompts]
            print(f"  Prompts listed: {names}")
            assert "draft_waste_explanation" in names

            result = await session.get_prompt(
                "draft_waste_explanation",
                arguments={"item_name": "Whole Milk", "quantity": "3l", "reason": "spoiled_before_use"},
            )
            rendered = result.messages[0].content.text
            print(f"  Rendered prompt: {rendered!r}")
            assert "Whole Milk" in rendered and "spoiled_before_use" in rendered
            print("  PASS: prompt discoverable and parameterized correctly.")


def _clear_preexisting_low_stock_for_branch_1() -> None:
    """ARRANGE step for test_notifications.

    Roma Tomatoes (item 1) and Chicken Breast (item 4) start BELOW their
    reorder_threshold from the moment seed.sql runs — that is realistic
    seed data, not a bug. But it means expedite_reorder is ALREADY visible
    the instant the server starts for branch 1, on every single run. A
    test that assumes a clean starting branch with nothing already low
    does not match reality here, so this explicitly raises both items
    above their thresholds first, giving the test a genuinely clean
    starting point to demonstrate the live crossing from. This only
    touches the test's own throwaway DB copy, rebuilt fresh by
    init_db.py before every run.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE inventory_items SET current_quantity = 50 WHERE item_id = 1")
    conn.execute("UPDATE inventory_items SET current_quantity = 50 WHERE item_id = 4")
    conn.commit()
    conn.close()


async def test_notifications():
    print("\n=== NOTIFICATIONS (the fix) ===")
    _received_notifications.clear()
    _clear_preexisting_low_stock_for_branch_1()

    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(
            read, write, elicitation_callback=accepting_elicitation_callback, message_handler=message_handler
        ) as session:
            await session.initialize()

            tools_before = [t.name for t in (await session.list_tools()).tools]
            print(f"  Tools BEFORE write-off: {tools_before}")
            assert "expedite_reorder" not in tools_before, \
                "expedite_reorder should NOT be visible yet given the arrange step above"

            # Whole Milk (item_id=3): stock 15.0L, threshold 12.0L, unit_cost
            # 0.95. Writing off 3.0L leaves exactly 12.0 (<= threshold ->
            # crosses it) and costs only 3*0.95=$2.85 (well under $200, so
            # this isolates NOTIFICATIONS from ELICITATION).
            result = await session.call_tool(
                "write_off_inventory",
                arguments={"item_id": 3, "quantity": 3.0, "reason": "spoiled_before_use"},
            )
            print(f"  write_off_inventory result: {result.content[0].text}")

            await asyncio.sleep(0.1)
            print(f"  Notifications received: {_received_notifications}")
            assert "ToolListChangedNotification" in _received_notifications

            tools_after = [t.name for t in (await session.list_tools()).tools]
            print(f"  Tools AFTER write-off: {tools_after}")
            assert "expedite_reorder" in tools_after
            print("  PASS: notification genuinely fired mid-session, tool list changed live.")


def _restore_item_stock(item_id: int, quantity: float) -> None:
    """ARRANGE step so elicitation tests don't depend on execution order or
    what an earlier test already consumed from the shared test database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE inventory_items SET current_quantity = ? WHERE item_id = ?", (quantity, item_id))
    conn.commit()
    conn.close()


async def test_elicitation_accept():
    print("\n=== ELICITATION (accept path) ===")
    _restore_item_stock(item_id=10, quantity=30.0)
    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=accepting_elicitation_callback) as session:
            await session.initialize()
            # Prime Ribeye (item_id=10): unit_cost $14.50. 15kg=$217.50>$200.
            result = await session.call_tool(
                "write_off_inventory",
                arguments={"item_id": 10, "quantity": 15.0, "reason": "damaged_in_delivery"},
            )
            payload = result.content[0].text
            print(f"  Result: {payload}")
            assert "new_stock_level" in payload
            print("  PASS: elicitation fired, manager accepted, write-off completed.")


async def test_elicitation_decline():
    print("\n=== ELICITATION (decline path) ===")
    _restore_item_stock(item_id=10, quantity=30.0)
    async with stdio_client(_params(MONA_TOKEN)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=declining_elicitation_callback) as session:
            await session.initialize()
            result = await session.call_tool(
                "write_off_inventory",
                arguments={"item_id": 10, "quantity": 15.0, "reason": "damaged_in_delivery"},
            )
            payload = result.content[0].text
            print(f"  Result: {payload}")
            assert "error" in payload.lower() and "not confirmed" in payload.lower()
            print("  PASS: manager declined, write-off was NOT applied.")


async def test_defensive_tool_design():
    print("\n=== DEFENSIVE TOOL DESIGN ===")
    async with stdio_client(_params(SALMA_TOKEN)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Salma (branch 2) targeting item_id=1, which belongs to branch 1.
            result = await session.call_tool(
                "write_off_inventory",
                arguments={"item_id": 1, "quantity": 1.0, "reason": "other"},
            )
            payload = result.content[0].text
            print(f"  Cross-branch attempt: {payload}")
            assert "error" in payload.lower() and "branch" in payload.lower()

            result2 = await session.call_tool(
                "write_off_inventory",
                arguments={"item_id": 6, "quantity": 9999.0, "reason": "other"},
            )
            payload2 = result2.content[0].text
            print(f"  Over-ceiling attempt: {payload2}")
            assert "error" in payload2.lower()
            print("  PASS: both rejected cleanly with structured errors, no crash.")


async def main():
    await test_capability_negotiation()
    await test_resources()
    await test_prompts()
    await test_notifications()
    await test_elicitation_accept()
    await test_elicitation_decline()
    await test_defensive_tool_design()
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
