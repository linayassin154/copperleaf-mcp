"""
server.py — Copperleaf Kitchens MCP Server entrypoint.

Wires together auth.py (session identity), db.py (connections), tools.py
(business operations), and validation.py (independent server-side checks)
into an actual FastMCP server.

--- Capability negotiation ---
FastMCP handles the low-level initialize/initialized handshake and
automatically declares server capabilities (tools) based on what's
registered below. The concern this file makes VISIBLE and TESTABLE is the
other half of negotiation: before generate_waste_report ever attempts a
sampling call, it explicitly checks whether THIS client declared sampling
support (ctx.session.check_client_capability). If a connected client never
declared it, the server does not assume it — it falls back to a plain
report with no AI-generated summary. See generate_waste_report below.

--- Session / transport note ---
stdio: one process = one client, so we resolve the session ONCE at process
startup, from an api_token passed via the COPPERLEAF_API_TOKEN env var.
TODO before the Streamable HTTP transition: do NOT keep a single global
SESSION once one process can serve multiple concurrent clients — resolve
per-request from a request header instead. This is flagged in auth.py too.
"""
import os
import sys

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ClientCapabilities, SamplingCapability, SamplingMessage, TextContent

from auth import AuthError, Session, resolve_staff
from db import get_connection
from validation import ValidationError, validate_date_range
import tools as _tools
from tools import AuthorizationError, ToolError

mcp = FastMCP(
    "copperleaf-kitchens",
    instructions=(
        "Inventory management assistant for Copperleaf Kitchens. Staff can "
        "check stock, orders, and transaction history. Managers can "
        "additionally write off inventory and generate waste reports."
    ),
)

# --- Session resolution (stdio: once per process) ---
_API_TOKEN = os.environ.get("COPPERLEAF_API_TOKEN")
try:
    SESSION: Session = resolve_staff(_API_TOKEN)
    print(f"[copperleaf] Authenticated as {SESSION.full_name} ({SESSION.role}, branch {SESSION.branch_id})", file=sys.stderr)
except AuthError as e:
    print(f"[copperleaf] FATAL: could not authenticate session: {e}", file=sys.stderr)
    sys.exit(1)


def _as_error(exc: Exception) -> dict:
    """Turn any tool-level exception into a structured error dict returned
    to the model — never an unhandled traceback."""
    return {"error": str(exc)}


# ---------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------

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
    """Return items at or below their reorder threshold for a branch. If
    threshold is given, it overrides each item's own configured threshold
    for this query only."""
    try:
        return _tools.get_low_stock_items(SESSION, branch_id, threshold)
    except ToolError as e:
        return _as_error(e)


@mcp.tool()
def get_supplier_orders(branch_id: int, status: str | None = None) -> list[dict] | dict:
    """View supplier orders for a branch, optionally filtered by status
    ('pending', 'delivered', or 'cancelled')."""
    try:
        return _tools.get_supplier_orders(SESSION, branch_id, status)
    except ToolError as e:
        return _as_error(e)


@mcp.tool()
def get_transaction_history(item_id: int, limit: int = 20) -> list[dict] | dict:
    """View recent inventory transactions for a specific item, most recent
    first (restock, usage, write_off, or adjustment)."""
    try:
        return _tools.get_transaction_history(SESSION, item_id, limit)
    except ToolError as e:
        return _as_error(e)


# ---------------------------------------------------------------------
# Write tool — manager-only, branch-scoped, atomic, independently validated
# ---------------------------------------------------------------------

@mcp.tool()
def write_off_inventory(item_id: int, quantity: float, reason: str) -> dict:
    """Write off spoiled, damaged, or lost inventory. Manager-only, and only
    for items belonging to the caller's own branch. reason must be one of:
    spoiled_before_use, past_expiry, damaged_in_delivery, prep_error, other.
    Rejected if quantity exceeds current stock or a safety ceiling."""
    try:
        return _tools.write_off_inventory(SESSION, item_id, quantity, reason)
    except (AuthorizationError, ToolError) as e:
        return _as_error(e)


# ---------------------------------------------------------------------
# Slow tool — progress tracking + sampling
# ---------------------------------------------------------------------

@mcp.tool()
async def generate_waste_report(ctx: Context, branch_id: int, date_from: str, date_to: str) -> dict:
    """Generate a waste/write-off report for a branch over a date range:
    total cost impact, breakdown by reason, and an AI-generated summary of
    likely patterns (requires the connected client to support sampling).
    Reports real progress since it joins transactions with item costs."""
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

    # --- Capability negotiation in action: check before relying on it ---
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
            "Connected client does not declare sampling support — skipping "
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


# ---------------------------------------------------------------------
# Schema hardening — FastMCP (mcp==1.9.0) does not set
# additionalProperties: false by default, and derives plain `str` fields
# as unconstrained strings even when the real domain is a fixed set of
# values. The lab requires real JSON Schema constraints, not just types,
# so this patches every registered tool's generated schema directly.
# ---------------------------------------------------------------------
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


if __name__ == "__main__":
    mcp.run()
