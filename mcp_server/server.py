"""
server.py - Copperleaf Kitchens MCP Server entrypoint.
"""
import os
import sys

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import (
    ClientCapabilities,
    SamplingCapability,
    SamplingMessage,
    TextContent,
    ElicitationCapability,
)

from auth import AuthError, Session, resolve_staff
from db import get_connection
from validation import ValidationError, validate_date_range
import tools as _tools
from tools import AuthorizationError, ToolError
import resources as _resources
import prompts as _prompts

mcp = FastMCP(
    "copperleaf-kitchens",
    instructions=(
        "Inventory management assistant for Copperleaf Kitchens. Staff can "
        "check stock, orders, and transaction history. Managers can "
        "additionally write off inventory and generate waste reports."
    ),
)

WRITE_OFF_ELICIT_THRESHOLD = 200.0

_API_TOKEN = os.environ.get("COPPERLEAF_API_TOKEN")
try:
    SESSION: Session = resolve_staff(_API_TOKEN)
    print(f"[copperleaf] Authenticated as {SESSION.full_name} ({SESSION.role}, branch {SESSION.branch_id})", file=sys.stderr)
except AuthError as e:
    print(f"[copperleaf] FATAL: could not authenticate session: {e}", file=sys.stderr)
    sys.exit(1)


def _as_error(exc: Exception) -> dict:
    return {"error": str(exc)}


@mcp.tool()
def get_inventory(branch_id: int, item_name: str | None = None) -> list[dict] | dict:
    """Look up current stock levels for a branch, optionally filtered by
    item name (partial match). Available to any authenticated staff member."""
    try:
        return _tools.get_inventory(SESSION, branch_id, item_name)
    except ToolError as e:
        return _as_error(e)


@mcp.tool()
def get_low_stock_items(branch_id: int, threshold: float | None = None) -> list[dict] | dict:
    """Return items at or below their reorder threshold for a branch."""
    try:
        return _tools.get_low_stock_items(SESSION, branch_id, threshold)
    except ToolError as e:
        return _as_error(e)


@mcp.tool()
def get_supplier_orders(branch_id: int, status: str | None = None) -> list[dict] | dict:
    """View supplier orders for a branch, optionally filtered by status."""
    try:
        return _tools.get_supplier_orders(SESSION, branch_id, status)
    except ToolError as e:
        return _as_error(e)


@mcp.tool()
def get_transaction_history(item_id: int, limit: int = 20) -> list[dict] | dict:
    """View recent inventory transactions for a specific item."""
    try:
        return _tools.get_transaction_history(SESSION, item_id, limit)
    except ToolError as e:
        return _as_error(e)


class WriteOffConfirmation(BaseModel):
    confirm: bool


@mcp.tool()
async def write_off_inventory(ctx: Context, item_id: int, quantity: float, reason: str) -> dict:
    """Write off spoiled, damaged, or lost inventory. Manager-only, and only
    for items belonging to the caller's own branch. reason must be one of:
    spoiled_before_use, past_expiry, damaged_in_delivery, prep_error, other.
    Write-offs with a cost impact at or above $200 require confirmation."""
    if SESSION.role != "manager":
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' has role '{SESSION.role}' - only managers can write off inventory."
        ))

    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, current_quantity, unit_cost, name, reorder_threshold "
            "FROM inventory_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        return _as_error(ToolError(f"No inventory item with item_id={item_id}."))

    if item["branch_id"] != SESSION.branch_id:
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' manages branch_id={SESSION.branch_id}, "
            f"but item_id={item_id} belongs to branch_id={item['branch_id']}."
        ))

    estimated_cost = quantity * item["unit_cost"]

    if estimated_cost >= WRITE_OFF_ELICIT_THRESHOLD:
        supports_elicitation = ctx.session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )
        if not supports_elicitation:
            return _as_error(ToolError(
                f"This write-off has an estimated cost impact of {estimated_cost:.2f}, "
                f"at or above the {WRITE_OFF_ELICIT_THRESHOLD:.2f} confirmation threshold. "
                "The connected client does not support elicitation."
            ))

        result = await ctx.elicit(
            message=(
                f"Confirm write-off of {quantity} {item['name']} "
                f"(estimated cost impact: {estimated_cost:.2f}). Proceed?"
            ),
            schema=WriteOffConfirmation,
        )

        if result.action != "accept" or not result.data.confirm:
            return _as_error(ToolError(
                f"Write-off of {quantity} {item['name']} was not confirmed "
                f"(action={result.action}) - no changes made."
            ))

    try:
        outcome = _tools.write_off_inventory(SESSION, item_id, quantity, reason)
    except (AuthorizationError, ToolError) as e:
        return _as_error(e)

    await _maybe_expose_expedite_reorder(ctx, item_id)

    return outcome


_EXPEDITE_REORDER_NAME = "expedite_reorder"
_expedite_reorder_visible = False


def _expedite_reorder_impl(item_id: int, quantity: float) -> dict:
    """Place an expedited supplier order for a low-stock item. Manager-only,
    and only for items belonging to the caller's own branch."""
    if SESSION.role != "manager":
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' has role '{SESSION.role}' - only managers can expedite reorders."
        ))

    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, supplier_id, name FROM inventory_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        return _as_error(ToolError(f"No inventory item with item_id={item_id}."))

    if item["branch_id"] != SESSION.branch_id:
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' manages branch_id={SESSION.branch_id}, "
            f"but item_id={item_id} belongs to branch_id={item['branch_id']}."
        ))

    if quantity <= 0:
        return _as_error(ToolError(f"quantity must be positive, got {quantity}."))

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO supplier_orders (branch_id, supplier_id, item_id, quantity, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (SESSION.branch_id, item["supplier_id"], item_id, quantity),
        )
        conn.commit()
        order_id = cur.lastrowid

    return {
        "order_id": order_id,
        "item_id": item_id,
        "item_name": item["name"],
        "quantity_ordered": quantity,
        "status": "pending",
    }


def _register_expedite_reorder() -> None:
    global _expedite_reorder_visible
    tool = mcp._tool_manager.add_tool(
        _expedite_reorder_impl,
        name=_EXPEDITE_REORDER_NAME,
        description=(
            "Place an expedited supplier order for an item that has just "
            "dropped at or below its reorder threshold."
        ),
    )
    tool.parameters["additionalProperties"] = False
    _expedite_reorder_visible = True


async def _maybe_expose_expedite_reorder(ctx: Context, item_id: int) -> None:
    global _expedite_reorder_visible
    if _expedite_reorder_visible:
        return

    with get_connection() as conn:
        row = conn.execute(
            "SELECT current_quantity, reorder_threshold FROM inventory_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if row is not None and row["current_quantity"] <= row["reorder_threshold"]:
        _register_expedite_reorder()
        await ctx.session.send_tool_list_changed()


def _expose_expedite_reorder_if_already_low_stock() -> None:
    existing_low_stock = _tools.get_low_stock_items(SESSION, SESSION.branch_id)
    if existing_low_stock:
        _register_expedite_reorder()


_expose_expedite_reorder_if_already_low_stock()


@mcp.tool()
async def generate_waste_report(ctx: Context, branch_id: int, date_from: str, date_to: str) -> dict:
    """Generate a waste/write-off report for a branch over a date range."""
    try:
        validate_date_range(date_from, date_to)
    except ValidationError as e:
        return _as_error(e)

    await ctx.report_progress(progress=0, total=100, message="Querying write-off transactions...")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT it.name, it.category, it.unit_cost, t.quantity_change, "
            "t.reason, t.created_at FROM inventory_transactions t "
            "JOIN inventory_items it ON it.item_id = t.item_id "
            "WHERE it.branch_id = ? AND t.change_type = 'write_off' "
            "AND date(t.created_at) BETWEEN date(?) AND date(?) "
            "ORDER BY t.created_at",
            (branch_id, date_from, date_to),
        ).fetchall()

    await ctx.report_progress(progress=40, total=100, message=f"Found {len(rows)} write-off records, computing costs...")

    total_cost = 0.0
    by_reason: dict[str, float] = {}
    lines = []
    for r in rows:
        qty = abs(r["quantity_change"])
        cost = qty * r["unit_cost"]
        total_cost += cost
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0.0) + cost
        lines.append(f"- {r['name']} ({r['category']}): {qty} units, reason={r['reason']}, cost={cost:.2f}")

    await ctx.report_progress(progress=75, total=100, message="Checking sampling support...")

    supports_sampling = ctx.session.check_client_capability(
        ClientCapabilities(sampling=SamplingCapability())
    )

    if not rows:
        summary = "No write-offs recorded in this date range."
    elif supports_sampling:
        await ctx.report_progress(progress=85, total=100, message="Requesting AI summary via sampling...")
        prompt = (
            f"Inventory write-offs for branch {branch_id} between {date_from} "
            f"and {date_to}:\n" + "\n".join(lines) +
            "\n\nIn 2-3 sentences, summarize the likely causes and flag any "
            "pattern a manager should look into."
        )
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=200,
        )
        summary = result.content.text if hasattr(result.content, "text") else str(result.content)
    else:
        summary = (
            "Connected client does not declare sampling support - skipping "
            "AI-generated summary. Raw totals below are still accurate."
        )

    await ctx.report_progress(progress=100, total=100, message="Report complete.")

    return {
        "branch_id": branch_id,
        "date_from": date_from,
        "date_to": date_to,
        "total_write_off_events": len(rows),
        "total_cost_impact": round(total_cost, 2),
        "cost_by_reason": {k: round(v, 2) for k, v in by_reason.items()},
        "ai_summary": summary,
    }


@mcp.resource(
    _resources.WASTE_POLICY_URI,
    name="Waste & Write-Off Policy",
    description=(
        "Copperleaf's policy for recognized write-off reasons, quantity "
        "limits, the manager sign-off cost threshold, and branch scoping rules."
    ),
    mime_type="text/plain",
)
def waste_policy() -> str:
    return _resources.WASTE_POLICY_TEXT


@mcp.prompt(
    name=_prompts.WASTE_EXPLANATION_PROMPT_NAME,
    description=(
        "Draft a short, manager-readable explanation for a specific "
        "inventory write-off, given the item, quantity, and reason code."
    ),
)
def draft_waste_explanation(item_name: str, quantity: str, reason: str) -> str:
    return _prompts.render_prompt(
        _prompts.WASTE_EXPLANATION_PROMPT_NAME,
        {"item_name": item_name, "quantity": quantity, "reason": reason},
    )


_ENUM_CONSTRAINTS = {
    "get_supplier_orders": {"status": ["pending", "delivered", "cancelled"]},
    "write_off_inventory": {
        "reason": ["spoiled_before_use", "past_expiry", "damaged_in_delivery", "prep_error", "other"]
    },
}
_ALL_TOOL_NAMES = (
    "get_inventory", "get_low_stock_items", "get_supplier_orders",
    "get_transaction_history", "write_off_inventory", "generate_waste_report",
)


def _harden_tool_schemas() -> None:
    for tool_name, field_enums in _ENUM_CONSTRAINTS.items():
        tool = mcp._tool_manager.get_tool(tool_name)
        if tool is None:
            continue
        for field, enum_values in field_enums.items():
            if field in tool.parameters.get("properties", {}):
                tool.parameters["properties"][field]["enum"] = enum_values

    for tool_name in _ALL_TOOL_NAMES:
        tool = mcp._tool_manager.get_tool(tool_name)
        if tool is not None:
            tool.parameters["additionalProperties"] = False


_harden_tool_schemas()


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server
    from mcp.server.lowlevel.server import NotificationOptions

    init_options = mcp._mcp_server.create_initialization_options(
        notification_options=NotificationOptions(
            tools_changed=True,
            resources_changed=True,
            prompts_changed=True,
        )
    )
    async with stdio_server() as (read_stream, write_stream):
        await mcp._mcp_server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import anyio
    anyio.run(_run_stdio)
