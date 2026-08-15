import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.tools import (
    create_supplier_order,
    AuthorizationError,
    ToolError,
)
from mcp_server.auth import Session
from mcp_server.db import get_write_connection


@pytest.fixture
def manager_session():
    return Session(staff_id=2, full_name="Alice Manager", role="manager", branch_id=2)


@pytest.fixture
def staff_session():
    return Session(staff_id=1, full_name="Bob Staff", role="staff", branch_id=2)


def clear_todays_orders():
    """Clear expedited orders from today so we can test capacity fresh."""
    with get_write_connection() as conn:
        conn.execute(
            "DELETE FROM supplier_orders WHERE expedited = 1 AND date(ordered_at) = date('now')"
        )


def test_standard_order_works(manager_session):
    """Manager can place a regular (non-expedited) order."""
    clear_todays_orders()

    # item_id=8 (Cucumbers) is branch 2 with supplier_id=1, matching this
    # branch-2 manager and the supplier_id already hardcoded below.
    # item_id=4 (the old value) is branch 1 — that's a different bug
    # entirely, not what this test is trying to exercise.
    result = create_supplier_order(
        session=manager_session,
        item_id=8,
        supplier_id=1,
        quantity=10.0,
        expedited=False,
    )

    assert result["status"] == "pending"
    assert result["expedited"] is False
    print(f"✓ Standard order created: {result['order_id']}")


def test_first_expedited_works(manager_session):
    """Manager can place the first expedited order of the day."""
    clear_todays_orders()

    result = create_supplier_order(
        session=manager_session,
        item_id=8,
        supplier_id=1,
        quantity=5.0,
        expedited=True,
    )

    assert result["expedited"] is True
    print(f"✓ First expedited order created: {result['order_id']}")


def test_expedite_capacity_fails(manager_session):
    """This is the KEY test. 3rd expedited order should FAIL because supplier is at capacity (2 max/day)."""
    clear_todays_orders()

    # Place 2 expedited orders (this is the limit)
    for i in range(2):
        result = create_supplier_order(
            session=manager_session,
            item_id=8,
            supplier_id=1,
            quantity=1.0,
            expedited=True,
        )
        print(f"  Expedited #{i+1} OK: order {result['order_id']}")

    # 3rd should fail - this is what makes dynamic decomposition replan
    with pytest.raises(ToolError) as exc:
        create_supplier_order(
            session=manager_session,
            item_id=8,
            supplier_id=1,
            quantity=5.0,
            expedited=True,
        )

    print(f"✓ 4th expedited REJECTED (as expected): {exc.value}")
    print("  → This is how dynamic decomposition sees the problem and retries")


def test_staff_cant_order(staff_session):
    """Only managers can create orders."""
    with pytest.raises(AuthorizationError):
        create_supplier_order(
            session=staff_session,
            item_id=8,
            supplier_id=1,
            quantity=10.0,
            expedited=False,
        )
    print("✓ Staff correctly denied")


def test_wrong_branch_denied(manager_session):
    """Manager can't order items from a different branch."""
    clear_todays_orders()

    # Item 1 is in branch 1, but manager is for branch 2
    with pytest.raises(AuthorizationError):
        create_supplier_order(
            session=manager_session,
            item_id=1,
            supplier_id=1,
            quantity=10.0,
            expedited=False,
        )
    print("✓ Cross-branch access denied")


def test_invalid_item(manager_session):
    """Can't order non-existent items."""
    with pytest.raises(ToolError):
        create_supplier_order(
            session=manager_session,
            item_id=9999,
            supplier_id=1,
            quantity=10.0,
            expedited=False,
        )
    print("✓ Invalid item rejected")


def test_bad_quantity(manager_session):
    """Quantity must be positive."""
    clear_todays_orders()

    with pytest.raises(ToolError):
        create_supplier_order(
            session=manager_session,
            item_id=8,
            supplier_id=1,
            quantity=-5.0,
            expedited=False,
        )
    print("✓ Negative quantity rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])