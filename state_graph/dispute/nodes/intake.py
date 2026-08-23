"""
state_graph/dispute/nodes/intake.py — dispute_opened -> awaiting_supplier_response.

dispute_opened grounds the run against the REAL supplier_orders +
inventory_items rows for order_id (never trusts the caller's opinion of
expected_quantity or unit_cost -- those come from the database, only
received_quantity is reported by the staff member who physically counted
the delivery).

awaiting_supplier_response is the genuine external wait this graph needs:
it can loop back to ITSELF. A supplier's first reply is often a partial
counter-offer ("we'll credit 2 of the 5 short units"), which needs
another round of back-and-forth before the graph can move on.

reply_round is capped (MAX_REPLY_ROUNDS) so an unresponsive or endlessly
noncommittal supplier can't keep this node interrupting forever without
ever reaching the ticket path -- see route_after_reply.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from langgraph.types import interrupt

from mcp_server.db import get_connection
from state import DisputeState

MAX_REPLY_ROUNDS = 3


def dispute_opened(state: DisputeState) -> DisputeState:
    """Entry point. Grounds item_id, supplier_id, expected_quantity, and
    unit_cost against the real order row -- these are facts, not
    something later nodes are allowed to reinterpret."""
    print("[node:dispute_opened] entered", flush=True)
    with get_connection() as conn:
        order = conn.execute(
            "SELECT item_id, supplier_id, quantity, branch_id FROM supplier_orders "
            "WHERE order_id = ? AND status = 'delivered'",
            (state["order_id"],),
        ).fetchone()

        if order is None:
            return {
                **state,
                "status": "dispute_opened",
                "intake_error": (
                    f"order_id={state['order_id']} does not exist or is not "
                    "status='delivered' -- a dispute can only be opened "
                    "against a delivered order."
                ),
            }

        item = conn.execute(
            "SELECT unit_cost FROM inventory_items WHERE item_id = ?",
            (order["item_id"],),
        ).fetchone()

    return {
        **state,
        "status": "dispute_opened",
        "item_id": order["item_id"],
        "supplier_id": order["supplier_id"],
        "expected_quantity": order["quantity"],
        "unit_cost": item["unit_cost"],
        "reply_round": 0,
        "intake_error": "",
    }


def route_after_intake(state: DisputeState) -> str:
    """A bad order_id is a real, unplanned failure -> ticket, not a crash
    and not something awaiting_supplier_response should ever have to
    handle."""
    return "ticket_open" if state.get("intake_error") else "awaiting_supplier_response"


def awaiting_supplier_response(state: DisputeState) -> DisputeState:
    """Genuine external wait. Pauses until something outside the model
    (a real supplier reply, relayed through the platform) resumes this
    node with reply text."""
    print("[node:awaiting_supplier_response] entered, round", state["reply_round"], flush=True)
    reply_text = interrupt(
        {
            "reason": "awaiting_supplier_response",
            "dispute_id": state["dispute_id"],
            "message": (
                f"Waiting on supplier reply for dispute {state['dispute_id']} "
                f"(order {state['order_id']}, round {state['reply_round'] + 1})."
            ),
        }
    )
    print("[node:awaiting_supplier_response] resumed with reply", flush=True)
    return {
        **state,
        "status": "awaiting_supplier_response",
        "supplier_reply": reply_text,
        "reply_round": state["reply_round"] + 1,
    }


def route_after_reply(state: DisputeState) -> str:
    """- Unparseable reply (empty/whitespace) at any round, OR round cap
      exceeded -> ticket_open.
    - A reply that itself says it's a partial/counter offer -> loop back
      to awaiting_supplier_response for another round.
    - Anything else usable -> investigate_discrepancy."""
    reply = (state.get("supplier_reply") or "").strip()
    if state["reply_round"] > MAX_REPLY_ROUNDS:
        return "ticket_open"
    if not reply:
        return "ticket_open"
    if "partial" in reply.lower() or "counter" in reply.lower():
        return "awaiting_supplier_response"
    return "investigate_discrepancy"