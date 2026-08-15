"""
planning/routing.py — decides which planning algorithm handles a given
sub-task inside the decomposed DAG.

--- routing: routing.py ---

Shape heuristic (used by route_task below):
  - tool_name already set on the task -> not routed here at all. execute_plan
    calls the real MCP tool directly; this module never sees those tasks.
  - Task instruction contains a comparison/ranking verb (compare, rank,
    prioritize, which, choose between, decide between) -> tree_of_thoughts.
    These tasks have several valid candidate answers that need to be
    generated and weighed against each other before committing to one.
  - Task is the plan's terminal/synthesis node (no other task depends on
    it) AND has a real-world consequence (references placing/expediting an
    order, committing to a supplier, or finalizing a covering plan) ->
    lats, routed through CopperleafEnvironment so the search is graded
    against a real check, not the model's own opinion of itself.
  - Everything else (a single deterministic reasoning task with one
    correct-shaped answer, e.g. "summarize the low-stock items into a
    written note") -> plan_and_solve, since there's nothing to branch on.

This file is Copperleaf-specific and is NOT vendored from the toolkit —
it only imports the toolkit's existing plan_and_solve / tree_of_thoughts /
lats functions and decides which one to call, per task.
"""
from __future__ import annotations

import re
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from planning_lab.algorithms import lats, plan_and_solve, tree_of_thoughts
from planning_lab.algorithms.environment import Environment
from planning_lab.models import Plan

Algorithm = Literal["plan_and_solve", "tree_of_thoughts", "lats"]

_COMPARISON_PATTERN = re.compile(
    r"\b(compare|rank|prioriti[sz]e|which\b|choose between|decide between|"
    r"best (option|choice|supplier|approach)|evaluate .*(options|candidates))\b",
    re.IGNORECASE,
)

_CONSEQUENTIAL_PATTERN = re.compile(
    r"\b(place|expedite|commit to|finaliz(e|ing)|submit) .*"
    r"(order|reorder|supplier|plan)\b",
    re.IGNORECASE,
)


def route_task(task_id: str, plan: Plan) -> Algorithm:
    """Decide which planning algorithm should handle this reasoning-only
    sub-task. Only meaningful for tasks with no tool_name set — callers
    should check task.tool_name first and skip routing entirely for
    tool-shaped tasks, since execute_plan already handles those directly.
    """
    task = plan.task(task_id)
    instruction = task.instruction
    is_terminal = task_id in plan.terminal_tasks()

    if is_terminal and _CONSEQUENTIAL_PATTERN.search(instruction):
        return "lats"
    if _COMPARISON_PATTERN.search(instruction):
        return "tree_of_thoughts"
    return "plan_and_solve"


def run_routed_task(
    task_id: str,
    plan: Plan,
    llm: BaseChatModel,
    environment: Environment | None = None,
) -> tuple[Algorithm, str]:
    """Route the task and actually run it, returning (algorithm_used, output).
    environment is required when the router picks lats; callers that never
    expect a lats-routed task in their plan may omit it, but a real run
    against a plan with a consequential terminal task must supply a real
    (grounded) Environment — never the toolkit's default random one.
    """
    algorithm = route_task(task_id, plan)
    task = plan.task(task_id)

    if algorithm == "plan_and_solve":
        return algorithm, plan_and_solve(task.instruction, llm)

    if algorithm == "tree_of_thoughts":
        thoughts = tree_of_thoughts(task.instruction, llm)
        best = max(thoughts, key=lambda t: t.score)
        return algorithm, best.state

    # algorithm == "lats"
    if environment is None:
        raise ValueError(
            f"Task {task_id!r} routed to lats but no environment was supplied. "
            "Pass a real (grounded) Environment — never leave this as the "
            "toolkit's default random evaluator for a task with real "
            "consequences."
        )
    result = lats(task.instruction, llm, environment)
    return algorithm, result.output
