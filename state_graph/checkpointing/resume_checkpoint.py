"""
Separate process — proves LangGraph resumes from the last real checkpoint
after a hard kill, without re-running step_one.
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict


class State(TypedDict):
    count: int
    log: list[str]


def step_one(state: State) -> State:
    print("Running step_one")
    return {"count": state["count"] + 1, "log": state["log"] + ["step_one done"]}


def step_two(state: State) -> State:
    print("Running step_two (this time it completes)")
    return {"count": state["count"] + 1, "log": state["log"] + ["step_two done"]}


def step_three(state: State) -> State:
    print("Running step_three")
    return {"count": state["count"] + 1, "log": state["log"] + ["step_three done"]}


builder = StateGraph(State)
builder.add_node("step_one", step_one)
builder.add_node("step_two", step_two)
builder.add_node("step_three", step_three)
builder.set_entry_point("step_one")
builder.add_edge("step_one", "step_two")
builder.add_edge("step_two", "step_three")
builder.add_edge("step_three", END)

with SqliteSaver.from_conn_string("state_graph/checkpointing/test_checkpoints.db") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)

    # SAME thread_id as before — this is what lets it pick up the same run
    config = {"configurable": {"thread_id": "test-run-1"}}

    print("Resuming graph from last checkpoint...")
    result = graph.invoke(None, config=config)  # None input = resume, don't restart
    print("Final state:", result)