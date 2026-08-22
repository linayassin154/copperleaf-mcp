from langchain_core.language_models.chat_models import BaseChatModel


def _normalize_content(content):
    """Gemini occasionally returns response.content as a list of blocks
    (e.g. [{"type": "text", "text": "..."}]) instead of a plain string.
    Flatten it before validating — same fix applied in decomposition.py,
    self_refine.py, and llm_counter.py's CountingLLM."""
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
        )
    return content


def plan_and_solve(question: str, llm: BaseChatModel) -> str:
    response = llm.invoke([
        ("system", "You use Plan-and-Solve prompting. Clearly separate PLAN from SOLUTION."),
        ("human", f"""{question}
First understand the problem and devise a plan to solve it. Then carry out the
plan step by step. Check calculations and common-sense assumptions."""),
    ], temperature=0.2)
    content = _normalize_content(response.content)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The chat model returned an empty or unsupported response")
    return content.strip()
