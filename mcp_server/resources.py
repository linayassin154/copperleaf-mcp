"""
resources.py - Static domain documents exposed as MCP resources.
"""

WASTE_POLICY_URI = "copperleaf://policy/waste-write-off"

WASTE_POLICY_TEXT = """\
Copperleaf Kitchens - Waste & Write-Off Policy
================================================

1. Recognized write-off reasons
--------------------------------
- spoiled_before_use   Item spoiled in storage before it could be used.
- past_expiry          Item passed its labeled expiry/use-by date.
- damaged_in_delivery   Item arrived damaged from the supplier.
- prep_error           Item was lost to a kitchen prep mistake.
- other                Anything not covered above. Use sparingly.

2. Quantity limits
-------------------
No single write-off may exceed 500 units in one call. Larger losses must be
split into multiple write-offs, or escalated to a branch manager manually.

3. Manager sign-off threshold
-------------------------------
Any single write-off with a cost impact (quantity x unit_cost) at or above
$200 requires explicit manager confirmation before it completes.

4. Branch scope
-----------------
A manager may only write off inventory belonging to their own branch.

5. Why this matters
----------------------
Every write-off is a real financial loss. The reason code lets a manager
notice a pattern before it becomes a recurring cost nobody caught.
"""


def list_resources() -> list[dict]:
    return [
        {
            "uri": WASTE_POLICY_URI,
            "name": "Waste & Write-Off Policy",
            "description": (
                "Copperleaf's policy for recognized write-off reasons, "
                "quantity limits, the manager sign-off cost threshold, and "
                "branch scoping rules."
            ),
            "mimeType": "text/plain",
        }
    ]


def read_resource(uri: str) -> str:
    if uri == WASTE_POLICY_URI:
        return WASTE_POLICY_TEXT
    raise ValueError(f"Unknown resource URI: {uri}")
