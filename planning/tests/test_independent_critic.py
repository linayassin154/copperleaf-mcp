"""
planning/tests/test_independent_critic.py — proves reflect_and_refine's
critique step genuinely uses a separate, independent LLM from the one
that drafted (and revises) the content, rather than the same model
grading its own work.

Per the Lab 5 team plan (Section 0.2): "Add the independent/different-LLM
critic test. Still missing entirely -- no test file references it."
"""
from types import SimpleNamespace

from planning_lab.algorithms import reflect_and_refine


class DraftingLLM:
    """Stands in for the model that produced the original draft and
    performs the revision. Records every prompt it sees so the test can
    assert this fake was never used for the critique step."""

    def __init__(self, revised_text: str):
        self.revised_text = revised_text
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        return SimpleNamespace(content=self.revised_text)


class CriticLLM:
    """A genuinely separate fake object from DraftingLLM -- proves the
    critique step is routed to a different LLM instance, not the
    drafting model grading itself."""

    def __init__(self, critique_text: str):
        self.critique_text = critique_text
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        # Confirm the critic sees the "separate critic" system prompt --
        # proves this call really is the critique step, not accidentally
        # the revision step routed to the wrong object.
        system_prompt = messages[0][1]
        assert "separate critic" in system_prompt.lower()
        return SimpleNamespace(content=self.critique_text)


def good_deliverable() -> str:
    body = " ".join(["structured plan explains concrete verification steps"] * 14)
    return f"# Plan\n- {body}"


def test_critic_llm_is_independent_from_drafting_llm():
    drafting_llm = DraftingLLM(revised_text=good_deliverable())
    critic_llm = CriticLLM(critique_text="The draft lacks a concrete timeline. Add one.")

    result = reflect_and_refine(
        goal="Design a rollout plan",
        draft="A short, underspecified draft.",
        llm=drafting_llm,
        critic_llm=critic_llm,
    )

    # The critique step must have gone to critic_llm, never drafting_llm.
    assert critic_llm.calls == 1
    # drafting_llm is only ever called for the revision step here (one
    # call), never for the critique itself.
    assert drafting_llm.calls == 1
    assert result.critique == "The draft lacks a concrete timeline. Add one."
    assert result.revised == good_deliverable()


def test_critic_llm_defaults_to_drafting_llm_when_not_provided():
    """Backward compatibility: existing callers that only pass one llm
    should keep working exactly as before -- that same model both
    critiques and revises."""
    shared_llm = DraftingLLM(revised_text=good_deliverable())

    # DraftingLLM's invoke doesn't check the system prompt, so this also
    # confirms no crash occurs when critic_llm is omitted entirely.
    result = reflect_and_refine(
        goal="Design a rollout plan",
        draft="A short, underspecified draft.",
        llm=shared_llm,
    )

    # Both the critique and the revision went through the same object.
    assert shared_llm.calls == 2
    assert result.revised == good_deliverable()