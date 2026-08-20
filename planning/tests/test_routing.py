"""
planning/tests/test_routing.py — unit tests for routing.py's route_task()
shape heuristic. These are pure regex/graph-shape checks against a
hand-built Plan, so they run fully offline (no LLM/API calls, no MCP
server) and stay fast enough to run on every commit.

run_routed_task() itself (which actually calls plan_and_solve/
tree_of_thoughts/lats) is exercised end-to-end via
planning_eval/run_comparison.py's routed-case runs and
agent/planning_client.py's live run, both of which require a real
GOOGLE_API_KEY — that's integration coverage, not unit coverage, and is
deliberately not duplicated here.
"""
import pytest

from planning_lab.models import Plan, Task
from routing import route_task, run_routed_task


def _plan(*tasks: Task) -> Plan:
    return Plan(goal="test goal for routing", tasks=list(tasks))


def test_comparison_task_routes_to_tree_of_thoughts():
    plan = _plan(
        Task(id="t1", instruction="Rank the three lowest-stock items by urgency."),
    )
    assert route_task("t1", plan) == "tree_of_thoughts"


def test_terminal_consequential_task_routes_to_lats():
    plan = _plan(
        Task(id="t1", instruction="Check current stock of Roma Tomatoes."),
        Task(
            id="t2",
            instruction="Commit to placing the final expedited order for the supplier.",
            depends_on=["t1"],
        ),
    )
    # t2 is terminal (nothing depends on it) and mentions committing to an order
    assert route_task("t2", plan) == "lats"


def test_non_terminal_consequential_task_does_not_route_to_lats():
    plan = _plan(
        Task(id="t1", instruction="Place the standard reorder for the item."),
        Task(id="t2", instruction="Summarize the outcome of the order.", depends_on=["t1"]),
    )
    # t1 mentions "place... order" but is NOT terminal (t2 depends on it),
    # so it must not get routed to lats just because of the keyword match.
    assert route_task("t1", plan) == "plan_and_solve"


def test_plain_reasoning_task_routes_to_plan_and_solve():
    plan = _plan(
        Task(id="t1", instruction="Summarize the low-stock items into a written note."),
    )
    assert route_task("t1", plan) == "plan_and_solve"


def test_run_routed_task_lats_without_environment_raises():
    plan = _plan(
        Task(id="t1", instruction="Finalize the plan and commit to the supplier order."),
    )
    with pytest.raises(ValueError, match="no environment was supplied"):
        run_routed_task("t1", plan, llm=None)  # type: ignore[arg-type]