"""
prompts.py - Reusable parameterized prompt templates.
"""

WASTE_EXPLANATION_PROMPT_NAME = "draft_waste_explanation"


def list_prompts() -> list[dict]:
    return [
        {
            "name": WASTE_EXPLANATION_PROMPT_NAME,
            "description": (
                "Draft a short, manager-readable explanation for a specific "
                "inventory write-off, given the item, quantity, and reason code."
            ),
            "arguments": [
                {"name": "item_name", "description": "Name of the item being written off.", "required": True},
                {"name": "quantity", "description": "Quantity written off, including unit (e.g. '2kg').", "required": True},
                {"name": "reason", "description": "The recognized reason code.", "required": True},
            ],
        }
    ]


def render_prompt(name: str, arguments: dict) -> str:
    if name != WASTE_EXPLANATION_PROMPT_NAME:
        raise ValueError(f"Unknown prompt: {name}")

    missing = [key for key in ("item_name", "quantity", "reason") if key not in arguments]
    if missing:
        raise ValueError(f"Missing required arguments: {missing}")

    return (
        f"Draft a short, manager-readable explanation for a waste write-off.\n\n"
        f"Item: {arguments['item_name']}\n"
        f"Quantity written off: {arguments['quantity']}\n"
        f"Reason code: {arguments['reason']}\n\n"
        "Write 2-3 sentences a branch manager could read at a glance: what "
        "happened, why this reason code applies, and whether this looks "
        "like an isolated event or something worth watching for a pattern."
    )
