"""
server.py — Copperleaf Kitchens MCP Server entrypoint.

Wires together auth.py (session identity), db.py (connections), tools.py
(business operations), validation.py (independent server-side checks),
resources.py (the waste policy document), and prompts.py (the
waste-explanation template) into a full FastMCP server.

--- Capability negotiation ---
FastMCP auto-declares server capabilities (tools, resources, prompts) based
on what's registered below — no manual code needed for that half. The half
this file makes VISIBLE and TESTABLE is checking the CLIENT's declared
capabilities before relying on them:
  - generate_waste_report checks sampling support before attempting a
    sampling call (unchanged from before).
  - write_off_inventory checks elicitation support before attempting to
    pause for manager confirmation on a high-cost write-off (new).
Neither assumes the connected client supports everything.

--- Notifications ---
expedite_reorder is NOT registered as a tool at server startup unless the
caller's branch already has a low-stock item. It gets registered — and a
real tools/list_changed notification fires — the moment a write-off drops
an item's stock at or below its reorder_threshold. This is a genuine
runtime change driven by inventory state, not a static permission table.

--- Elicitation ---
write_off_inventory computes the write-off's cost impact
(quantity * unit_cost) BEFORE performing it. Above WRITE_OFF_ELICIT_THRESHOLD,
it calls ctx.elicit(...) and pauses for explicit manager confirmation. Below
the threshold, it completes immediately, same as before. If the connected
client does not declare elicitation support, a high-cost write-off is
REJECTED rather than silently allowed through unconfirmed — this server
never bypasses the safety gate just because a client can't service it.

--- Session / transport note ---
stdio: one process = one client, so we resolve the session ONCE at process
startup, from an api_token passed via the COPPERLEAF_API_TOKEN env var.
See auth.py for the TODO covering the Streamable HTTP transition.
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

from mcp_server.auth import AuthError, Session, resolve_staff
from mcp_server.db import get_connection
from mcp_server.validation import ValidationError, validate_date_range
import mcp_server.tools as _tools
from mcp_server.tools import AuthorizationError, ToolError
import mcp_server.resources as _resources
import mcp_server.prompts as _prompts

mcp = FastMCP(
    "copperleaf-kitchens",
    instructions=(
        "Inventory management assistant for Copperleaf Kitchens. Staff can "
        "check stock, orders, and transaction history. Managers can "
        "additionally write off inventory and generate waste reports."
    ),
)

# Any single write-off with cost impact (quantity * unit_cost) at or above
# this amount requires explicit manager confirmation via elicitation.
# Mirrors the policy documented in resources.py's waste policy text — keep
# both in sync if this ever changes.
WRITE_OFF_ELICIT_THRESHOLD = 200.0

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
# Write tool — manager-only, branch-scoped, atomic, independently
# validated, AND gated by elicitation above a cost threshold.
# ---------------------------------------------------------------------

class WriteOffConfirmation(BaseModel):
    """Elicitation schema for a high-cost write-off. Only primitive fields
    are allowed by the MCP spec, so this is deliberately just a bool."""
    confirm: bool


@mcp.tool()
async def write_off_inventory(ctx: Context, item_id: int, quantity: float, reason: str) -> dict:
    """Write off spoiled, damaged, or lost inventory. Manager-only, and only
    for items belonging to the caller's own branch. reason must be one of:
    spoiled_before_use, past_expiry, damaged_in_delivery, prep_error, other.
    Rejected if quantity exceeds current stock or a safety ceiling. Write-offs
    with a cost impact at or above $200 require explicit manager confirmation."""
    if SESSION.role != "manager":
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' has role '{SESSION.role}' — only managers can write off inventory."
        ))

    # --- Look up cost impact BEFORE doing anything, to decide whether
    # this write-off needs a human sign-off. ---
    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, current_quantity, unit_cost, name, reorder_threshold "
            "FROM inventory_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        return _as_error(ToolError(f"No inventory item with item_id={item_id}."))

    # --- Branch authorization MUST run before elicitation. Confirming a
    # write-off that was always going to be rejected wastes the manager's
    # attention on a dialog that can't succeed. ---
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
                "The connected client does not support elicitation, so this server cannot "
                "obtain the required manager sign-off and will not proceed."
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
                f"(action={result.action}) — no changes made."
            ))

    # --- Perform the write-off (existing atomic, validated path). ---
    try:
        outcome = _tools.write_off_inventory(SESSION, item_id, quantity, reason)
    except (AuthorizationError, ToolError) as e:
        return _as_error(e)

    # --- Notifications: did this write-off just push the item at/below
    # its reorder threshold? If so, and expedite_reorder isn't already
    # visible, register it now and tell the client the tool list changed. ---
    await _maybe_expose_expedite_reorder(ctx, item_id)

    return outcome


# ---------------------------------------------------------------------

@mcp.tool()
def create_supplier_order(
    branch_id: int,
    item_id: int,
    supplier_id: int,
    quantity: float,
    expedited: bool = False
) -> dict:
    """Create a supplier order for an item.
    
    Pick which supplier to use. If expedited and supplier's at capacity today,
    this fails with an error. The planning agent can catch that and retry
    with a different supplier."""
    if SESSION.role != "manager":
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' has role '{SESSION.role}' — only managers can create orders."
        ))

    try:
        return _tools.create_supplier_order(
            SESSION,
            item_id=item_id,
            supplier_id=supplier_id,
            quantity=quantity,
            expedited=expedited
        )
    except (AuthorizationError, ToolError) as e:
        return _as_error(e)


# Notifications — expedite_reorder appears at runtime when an item drops
# at or below its reorder_threshold. Not registered at all otherwise,
# unless the caller's branch already has a low-stock item at startup.
# ---------------------------------------------------------------------

_EXPEDITE_REORDER_NAME = "expedite_reorder"
_expedite_reorder_visible = False


def _expedite_reorder_impl(item_id: int, quantity: float) -> dict:
    """Place an expedited supplier order for a low-stock item. Manager-only,
    and only for items belonging to the caller's own branch — same
    authorization shape as write_off_inventory."""
    if SESSION.role != "manager":
        return _as_error(AuthorizationError(
            f"'{SESSION.full_name}' has role '{SESSION.role}' — only managers can expedite reorders."
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
    """Add expedite_reorder to the live tool set and apply the same schema
    hardening every other tool gets."""
    global _expedite_reorder_visible
    tool = mcp._tool_manager.add_tool(
        _expedite_reorder_impl,
        name=_EXPEDITE_REORDER_NAME,
        description=(
            "Place an expedited supplier order for an item that has just "
            "dropped at or below its reorder threshold. Only available "
            "once that condition has been triggered for this session."
        ),
    )
    tool.parameters["additionalProperties"] = False
    _expedite_reorder_visible = True


async def _maybe_expose_expedite_reorder(ctx: Context, item_id: int) -> None:
    """Check whether item_id is now at/below its reorder threshold; if so
    and expedite_reorder isn't already visible, register it and push a real
    tools/list_changed notification."""
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
    """Startup check: if the authenticated session's branch already has a
    low-stock item (true for this seed data — Roma Tomatoes, Chicken Breast,
    Feta Cheese are below threshold from the start), expedite_reorder is
    already visible in the FIRST tools/list response. This is not a
    'changed' event since nothing changed after the client connected — it's
    just the correct starting state."""
    existing_low_stock = _tools.get_low_stock_items(SESSION, SESSION.branch_id)
    if existing_low_stock:
        _register_expedite_reorder()


_expose_expedite_reorder_if_already_low_stock()


# ---------------------------------------------------------------------
# Slow tool — progress tracking + sampling (unchanged)
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
# Resources — the waste policy, fetched instead of called.
# ---------------------------------------------------------------------

@mcp.resource(
    _resources.WASTE_POLICY_URI,
    name="Waste & Write-Off Policy",
    description=(
        "Copperleaf's policy for recognized write-off reasons, quantity "
        "limits, the manager sign-off cost threshold, and branch scoping "
        "rules."
    ),
    mime_type="text/plain",
)
def waste_policy() -> str:
    return _resources.WASTE_POLICY_TEXT


# ---------------------------------------------------------------------
# Prompts — reusable, parameterized waste-explanation template.
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# Schema hardening — FastMCP (mcp==1.10.0) does not set
# additionalProperties: false by default, and derives plain `str` fields
# as unconstrained strings even when the real domain is a fixed set of
# values. The lab requires real JSON Schema constraints, not just types,
# so this patches every registered tool's generated schema directly.
# expedite_reorder is intentionally excluded here — it's hardened at
# registration time in _register_expedite_reorder(), since it may not
# exist yet when this runs.
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


async def _run_stdio() -> None:
    """Replaces mcp.run() so we can declare listChanged=True for tools,
    resources, and prompts in the capabilities sent during initialize.

    FastMCP's default mcp.run() calls
    self._mcp_server.create_initialization_options() with no arguments,
    which always produces listChanged=False for everything — even though
    this server genuinely does send tools/list_changed (see
    _maybe_expose_expedite_reorder above). A client that correctly checks
    declared capabilities before relying on list_changed notifications
    would never expect one from this server as originally written. This
    is the other half of "capability negotiation, completed": the
    declaration has to match what the server actually does.
    """
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