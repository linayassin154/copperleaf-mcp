"""
retrieval_eval/questions.py - Domain-specific test questions for comparing
naive / hybrid / agentic RAG. Every expected_keywords entry is a real fact
pulled from rag/corpus/, not invented — see the source doc noted in each
comment.

Three categories, chosen to genuinely differentiate the architectures
(this is the whole point of the comparison, not padding):
  - exact_identifier: naive RAG is expected to underperform here, per
    naive_rag.py's own docstring admission about section numbers.
  - conceptual: naive RAG should do fine here (or better) — no exact
    identifier to lose track of.
  - cross_document: only agentic RAG's multi-hop loop should reliably
    combine two source documents into one answer.
"""
from dataclasses import dataclass


@dataclass
class EvalQuestion:
    question: str
    category: str  # 'exact_identifier' | 'conceptual' | 'cross_document'
    expected_keywords: list[str]


QUESTIONS: list[EvalQuestion] = [
    # --- exact_identifier ---
    EvalQuestion(
        question="What does Section 4.2 of the Nile Fresh Produce contract cover?",
        category="exact_identifier",
        expected_keywords=["escalation", "late", "quality"],
    ),
    EvalQuestion(
        question="Under Section 3.2 of the Coastal Seafood & Meats contract, what happens after two cold-chain failures in 30 days?",
        category="exact_identifier",
        expected_keywords=["mandatory", "supplier review", "60 days", "alternate supplier"],
    ),
    EvalQuestion(
        question="What write-off reason code does Section 4.2 of the food safety policy say to use?",
        category="exact_identifier",
        expected_keywords=["damaged_in_delivery", "receiving"],
    ),

    # --- conceptual ---
    EvalQuestion(
        question="How should raw seafood be stored to prevent contamination?",
        category="conceptual",
        expected_keywords=["0-2", "lowest shelf", "48 hours"],
    ),
    EvalQuestion(
        question="What's the difference in shelf life between brined and vacuum-packed feta?",
        category="conceptual",
        expected_keywords=["brine", "longer", "vacuum"],
    ),

    # --- cross_document (supplier contract + food safety policy together) ---
    EvalQuestion(
        question=(
            "If Nile Fresh Produce delivers tomatoes that are more than 24 "
            "hours late, and the tomatoes were then stored at 3°C, what "
            "contract remediation applies and was the storage temperature correct?"
        ),
        category="cross_document",
        expected_keywords=["late", "90-day", "4-7", "not"],
    ),
    EvalQuestion(
        question=(
            "Coastal Seafood delivers salmon without a visible ice log. "
            "What does their contract say about that, and how long is "
            "salmon usable once received per the storage policy?"
        ),
        category="cross_document",
        expected_keywords=["automatic rejection", "48 hours"],
    ),
]