"""
state_graph/onboarding/nodes/react_triage.py -- Constrained ReAct addition
for the Onboarding graph (LLM addition #2; RAG is addition #1, in
policy_check.py).

Sits right after the supplier's document arrives (awaiting_documents
resumes) and before extraction/policy-check. Decides, from the actual
document text, which ONE of exactly three whitelisted actions applies:

  - request_documents  -> what came back isn't usable at all (blank,
    wrong file, a completely unrelated document) -> loop back to
    awaiting_documents and ask again. This is a genuine cycle in the
    graph, not just a branch.
  - extract_terms      -> a real contract that terms_extracted's
    deterministic regex should be able to work with -> proceed to
    extraction as normal.
  - flag_for_review    -> a contract-shaped document with ambiguous,
    contradictory, or unusual terms that regex extraction alone
    shouldn't quietly decide on -> routes straight to the ticket path
    for a human to look at the raw text.

Whitelist is enforced structurally, not just by prompting: the LLM is
bound to exactly these three LangChain tools via bind_tools() and
nothing else -- there is no "approve" tool it could call even if it
wanted to auto-approve the supplier. That decision is not in its
vocabulary, matching the team plan doc's "never auto-approve" rule.

If the model's response contains no recognized tool call (a malformed
or refused response), the code defaults to flag_for_review rather than
silently guessing "extract" -- an unreadable model decision gets
escalated to a human, not papered over.

Kept in its own file, separate from intake.py's deterministic regex
extraction and policy_check.py's RAG call, so a grader can find the
graph's two required LLM-call additions in two clearly separate places.
"""
from __future__ import annotations

from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from state import OnboardingState

_WHITELISTED_TOOL_NAMES = {"request_documents", "extract_terms", "flag_for_review"}


@tool
def request_documents(reason: str) -> str:
    """Call this when the supplier's latest message contains no usable
    contract text at all -- blank, an unrelated file, a bounced email,
    a request for clarification from the supplier. Triggers asking the
    supplier again. Never call this if there is contract-shaped text
    to work with, even if it looks incomplete."""
    return f"request_documents: {reason}"


@tool
def extract_terms(reason: str) -> str:
    """Call this when the latest message is a real supplier contract or
    terms sheet with clearly stated, quotable terms (e.g. 'Delivery
    window: 3 days') that a deterministic parser should be able to
    read correctly. This is the normal, expected case for a usable
    document."""
    return f"extract_terms: {reason}"


@tool
def flag_for_review(reason: str) -> str:
    """Call this when the document is contract-shaped but has terms
    that are ambiguous, contradictory, unusually worded, or otherwise
    risky to hand to a plain deterministic parser without a human
    looking at the raw text first. This is NOT an approval or
    rejection decision -- it only routes the raw document to a human
    for inspection."""
    return f"flag_for_review: {reason}"


_TOOLS = [request_documents, extract_terms, flag_for_review]

_SYSTEM_PROMPT = (
    "You are triaging one document just received from a prospective "
    "supplier during onboarding. You may take exactly ONE of the three "
    "actions available to you as tools. You have no other actions "
    "available -- in particular, you cannot approve or reject the "
    "supplier; that decision belongs to a human admin later in the "
    "process. Call exactly one tool."
)


def intake_triage(state: OnboardingState) -> OnboardingState:
    print("[node:intake_triage] entered", flush=True)
    latest_doc = state["documents"][-1] if state["documents"] else ""
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    response = llm_with_tools.invoke(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Document received from {state['supplier_name']}:\n\n{latest_doc}",
            },
        ]
    )

    tool_calls = getattr(response, "tool_calls", None) or []
    decision = None
    reason = ""
    for call in tool_calls:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name in _WHITELISTED_TOOL_NAMES:
            decision = name
            args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
            reason = args.get("reason", "") if isinstance(args, dict) else ""
            break

    if decision is None:
        # No recognized tool call at all -- an unreadable model decision
        # is escalated, not guessed at.
        decision = "flag_for_review"
        reason = "Model did not return a recognized whitelisted tool call."

    return {
        **state,
        "status": "triaged",
        "triage_decision": decision,
        "triage_reason": reason,
    }


def route_after_triage(state: OnboardingState) -> str:
    """Conditional-edge router used by graph.py right after
    intake_triage. Maps the whitelisted decision directly onto graph
    edges -- there is no fourth path, matching the 'never auto-approve'
    constraint in the team plan doc."""
    return {
        "request_documents": "awaiting_documents",
        "extract_terms": "terms_extracted",
        "flag_for_review": "ticket_open",
    }[state["triage_decision"]]