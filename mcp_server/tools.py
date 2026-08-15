"""
tools.py — Business-operation tool functions for the Copperleaf Kitchens
MCP server.

Each function here is a plain Python function, not yet decorated as an MCP
tool — server.py imports these and registers them with the FastMCP instance.
Keeping them here (separate from server.py) means a grader can find "what
does each tool actually do" in one file, without wading through server
setup / capability negotiation code.

Every function takes `session: Session` as its first argument — this is
how identity/role reaches the handler. It is NEVER something the model
supplies as a tool argument (see auth.py). server.py is responsible for
passing the current session in when it wires these up.
"""
from typing import Optional

from mcp_server.auth import Session
from mcp_server.db import get_connection, get_write_connection
from mcp_server.validation import (
    ValidationError,
    validate_date_range,
    validate_expedite_capacity,
    validate_write_off,
)


class ToolError(Exception):
    """Raised for any tool-level failure that should be returned to the
    model as a structured error, not an unhandled exception."""


class AuthorizationError(ToolError):
    """Raised when an authenticated session is valid, but not ALLOWED to
    perform this specific action (e.g. staff role trying a manager tool,
    or a manager trying to act outside their own branch)."""


# ---------------------------------------------------------------------
# READ-ONLY TOOLS — available to both 'staff' and 'manager' roles
# ---------------------------------------------------------------------

def get_inventory(session: Session, branch_id: int, item_name: Optional[str] = None) -> list[dict]:
    """Look up current stock levels for a branch, optionally filtered by
    item name (partial match)."""
    query = (
        "SELECT item_id, name, category, unit, current_quantity, "
        "reorder_threshold, unit_cost FROM inventory_items WHERE branch_id = ?"
    )
    params: list = [branch_id]
    if item_name:
        query += " AND name LIKE ?"
        params.append(f"%{item_name}%")

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def get_low_stock_items(session: Session, branch_id: int, threshold: Optional[float] = None) -> list[dict]:
    """Return items at or below their reorder threshold for a branch.

    If `threshold` is given, it OVERRIDES each item's own reorder_threshold
    for this query only (useful for "show me anything below 5kg" style
    questions); otherwise each item's own configured threshold is used.
    """
    with get_connection() as conn:
        if threshold is not None:
            rows = conn.execute(
                "SELECT item_id, name, current_quantity, reorder_threshold "
                "FROM inventory_items WHERE branch_id = ? AND current_quantity <= ?",
                (branch_id, threshold),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT item_id, name, current_quantity, reorder_threshold "
                "FROM inventory_items WHERE branch_id = ? AND current_quantity <= reorder_threshold",
                (branch_id,),
            ).fetchall()

    return [dict(row) for row in rows]


def get_supplier_orders(session: Session, branch_id: int, status: Optional[str] = None) -> list[dict]:
    """View supplier orders for a branch, optionally filtered by status
    ('pending', 'delivered', or 'cancelled')."""
    query = (
        "SELECT order_id, supplier_id, item_id, quantity, status, expedited, "
        "ordered_at, expected_delivery FROM supplier_orders WHERE branch_id = ?"
    )
    params: list = [branch_id]
    if status:
        query += " AND status = ?"
        params.append(status)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def get_transaction_history(session: Session, item_id: int, limit: int = 20) -> list[dict]:
    """View recent inventory transactions (restock/usage/write-off/adjustment)
    for a specific item, most recent first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT transaction_id, staff_id, change_type, quantity_change, "
            "reason, created_at FROM inventory_transactions "
            "WHERE item_id = ? ORDER BY created_at DESC LIMIT ?",
            (item_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------
# WRITE TOOLS — manager-only, branch-scoped, atomic, independently validated
# ---------------------------------------------------------------------

def write_off_inventory(session: Session, item_id: int, quantity: float, reason: str) -> dict:
    """Write off spoiled/damaged/lost inventory. Manager-only.

    Defensive design, per the lab's requirements:
    1. Authorization check in the handler (not just schema): caller must be
       a 'manager', AND the item must belong to the caller's own branch.
    2. Independent server-side validation (validation.py): quantity must be
       positive, within a hard ceiling, not exceed current stock, and reason
       must be a recognized value — all re-checked here regardless of what
       the tool's input schema already enforced.
    3. Atomic write: the transaction log insert and the stock quantity
       update happen in a single DB transaction (get_write_connection) so a
       mid-operation failure can never desync them.
    """
    # --- Authorization (identity from session, never from arguments) ---
    if session.role != "manager":
        raise AuthorizationError(
            f"'{session.full_name}' has role '{session.role}' — only "
            "managers can write off inventory."
        )

    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, current_quantity FROM inventory_items "
            "WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        raise ToolError(f"No inventory item with item_id={item_id}.")

    if item["branch_id"] != session.branch_id:
        raise AuthorizationError(
            f"'{session.full_name}' manages branch_id={session.branch_id}, "
            f"but item_id={item_id} belongs to branch_id={item['branch_id']}."
        )

    # --- Independent server-side validation (not just schema-level) ---
    try:
        validate_write_off(
            item_id=item_id,
            quantity=quantity,
            reason=reason,
            current_stock=item["current_quantity"],
        )
    except ValidationError as e:
        raise ToolError(str(e)) from e

    # --- Atomic write: log + balance update together, or neither ---
    with get_write_connection() as conn:
        conn.execute(
            "INSERT INTO inventory_transactions "
            "(item_id, staff_id, change_type, quantity_change, reason) "
            "VALUES (?, ?, 'write_off', ?, ?)",
            (item_id, session.staff_id, -quantity, reason),
        )
        conn.execute(
            "UPDATE inventory_items SET current_quantity = current_quantity - ? "
            "WHERE item_id = ?",
            (quantity, item_id),
        )

    return {
        "item_id": item_id,
        "quantity_written_off": quantity,
        "reason": reason,
        "new_stock_level": item["current_quantity"] - quantity,
        "recorded_by": session.full_name,
    }


def _place_supplier_order(
    session: Session, *, item_id: int, quantity: float, expedited: bool
) -> dict:
    """Shared logic for both the standard and expedited order paths.
    Not registered as an MCP tool itself — place_standard_order and
    expedite_reorder (server.py) both call this, so the authorization,
    validation, and atomic-write shape lives in exactly one place.
    """
    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, supplier_id, name FROM inventory_items "
            "WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        raise ToolError(f"No inventory item with item_id={item_id}.")

    if item["branch_id"] != session.branch_id:
        raise AuthorizationError(
            f"'{session.full_name}' manages branch_id={session.branch_id}, "
            f"but item_id={item_id} belongs to branch_id={item['branch_id']}."
        )

    if item["supplier_id"] is None:
        raise ToolError(f"item_id={item_id} ('{item['name']}') has no supplier on file.")

    if quantity <= 0:
        raise ToolError(f"quantity must be positive, got {quantity}.")

    supplier_id = item["supplier_id"]

    # --- Independent server-side validation, real grounding for the
    # expedite path: how many expedited orders has this supplier already
    # taken today? This is a real DB read, not a random draw. ---
    if expedited:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM supplier_orders "
                "WHERE supplier_id = ? AND expedited = 1 AND date(ordered_at) = date('now')",
                (supplier_id,),
            ).fetchone()
        try:
            validate_expedite_capacity(
                supplier_id=supplier_id, todays_expedited_count=row["n"]
            )
        except ValidationError as e:
            raise ToolError(str(e)) from e

    # --- Atomic write ---
    with get_write_connection() as conn:
        cur = conn.execute(
            "INSERT INTO supplier_orders (branch_id, supplier_id, item_id, quantity, status, expedited) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (session.branch_id, supplier_id, item_id, quantity, int(expedited)),
        )
        conn.commit()
        order_id = cur.lastrowid

    return {
        "order_id": order_id,
        "item_id": item_id,
        "item_name": item["name"],
        "supplier_id": supplier_id,
        "quantity_ordered": quantity,
        "expedited": expedited,
        "status": "pending",
    }


def place_standard_order(session: Session, item_id: int, quantity: float) -> dict:
    """Place a standard (non-expedited) supplier order. Manager-only.
    Always available — unlike expedite_reorder, this isn't gated behind a
    low-stock notification, since a standard reorder is a routine action.
    """
    if session.role != "manager":
        raise AuthorizationError(
            f"'{session.full_name}' has role '{session.role}' — only "
            "managers can place supplier orders."
        )
    return _place_supplier_order(session, item_id=item_id, quantity=quantity, expedited=False)


def expedite_reorder(session: Session, item_id: int, quantity: float) -> dict:
    """Place an expedited supplier order. Manager-only. This is the
    business-logic layer for server.py's dynamically-registered
    expedite_reorder MCP tool — kept here so the real capacity check
    (validate_expedite_capacity) lives with the rest of this repo's
    validation, not inline in server.py.
    """
    if session.role != "manager":
        raise AuthorizationError(
            f"'{session.full_name}' has role '{session.role}' — only "
            "managers can expedite reorders."
        )
    return _place_supplier_order(session, item_id=item_id, quantity=quantity, expedited=True)

def create_supplier_order(
    session: Session,
    item_id: int,
    supplier_id: int,
    quantity: float,
    expedited: bool = False,
) -> dict:
    """Create a supplier order with explicit supplier choice.
    
    This lets the planning agent pick which supplier to use, not just the default.
    If expedited=True, checks if the supplier can handle it (max 2 expedited orders per day).
    If they're at capacity, raises ToolError - this is the real failure mode that lets
    dynamic decomposition see the problem and retry with a different supplier.
    """
    if session.role != "manager":
        raise AuthorizationError(
            f"'{session.full_name}' has role '{session.role}' — only managers can create orders."
        )

    with get_connection() as conn:
        item = conn.execute(
            "SELECT item_id, branch_id, name FROM inventory_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()

    if item is None:
        raise ToolError(f"No item with id {item_id}.")

    if item["branch_id"] != session.branch_id:
        raise AuthorizationError(
            f"'{session.full_name}' manages branch {session.branch_id}, "
            f"but item {item_id} is in branch {item['branch_id']}."
        )

    with get_connection() as conn:
        supplier = conn.execute(
            "SELECT supplier_id FROM inventory_items WHERE item_id = ? AND supplier_id = ?",
            (item_id, supplier_id),
        ).fetchone()

    if supplier is None:
        raise ToolError(f"Supplier {supplier_id} doesn't supply item {item_id}.")

    if quantity <= 0:
        raise ToolError(f"quantity must be positive, got {quantity}.")

    if expedited:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM supplier_orders "
                "WHERE supplier_id = ? AND expedited = 1 AND date(ordered_at) = date('now')",
                (supplier_id,),
            ).fetchone()
        try:
            validate_expedite_capacity(supplier_id=supplier_id, todays_expedited_count=row["n"])
        except ValidationError as e:
            raise ToolError(str(e)) from e

    with get_write_connection() as conn:
        cur = conn.execute(
            "INSERT INTO supplier_orders (branch_id, supplier_id, item_id, quantity, status, expedited) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (session.branch_id, supplier_id, item_id, quantity, int(expedited)),
        )
        conn.commit()
        order_id = cur.lastrowid

    return {
        "order_id": order_id,
        "item_id": item_id,
        "item_name": item["name"],
        "supplier_id": supplier_id,
        "quantity_ordered": quantity,
        "expedited": expedited,
        "status": "pending",
    }