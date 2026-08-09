"""
rag/chunking.py - Section-level chunking for the Copperleaf RAG corpus.

Every document in corpus/ (the food-safety policy, three supplier contracts)
is structured around numbered subsections - "Section 4.2", "Section 3.2" -
that get cited directly, by number, in real questions ("what does Section
4.2 of the Nile Fresh contract say about late deliveries"). A fixed-size /
token-window splitter would cut through a subsection mid-sentence and throw
away the exact numbering hybrid search's keyword component is meant to
catch. So chunking here follows document structure instead: one chunk per
### subsection, with an H2-level fallback for the handful of sections that
have no subsections of their own (e.g. the shelf-life table), plus a small
preamble chunk for anything before the first heading.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"

# doc_id (filename stem) -> fixed facts about that document, used as
# retrieval metadata. Pulled from the documents themselves, not invented.
DOC_METADATA: dict[str, dict] = {
    "food_safety_storage_policy": {
        "doc_type": "food_safety_policy",
        "supplier_name": None,
        "supplier_id": None,
        "category": None,
    },
    "nile_fresh_produce": {
        "doc_type": "supplier_contract",
        "supplier_name": "Nile Fresh Produce",
        "supplier_id": 1,
        "category": "Produce",
    },
    "delta_dairy_co": {
        "doc_type": "supplier_contract",
        "supplier_name": "Delta Dairy Co.",
        "supplier_id": 2,
        "category": "Dairy",
    },
    "coastal_seafood_meats": {
        "doc_type": "supplier_contract",
        "supplier_name": "Coastal Seafood & Meats",
        "supplier_id": 3,
        "category": "Protein",
    },
}

_H1 = re.compile(r"^# (.+)$", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    doc_id: str
    doc_type: str
    doc_title: str
    section_number: str
    section_title: str
    supplier_name: str | None = None
    supplier_id: int | None = None
    category: str | None = None

    def metadata(self) -> dict:
        """Flat, Chroma-safe metadata payload. Chroma rejects None values
        outright, so a fact that doesn't apply to this doc (e.g. no
        supplier_name on the food-safety policy) is OMITTED, never stored
        as null — that distinction matters once we filter on these fields."""
        md = {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "doc_title": self.doc_title,
            "section_number": self.section_number,
            "section_title": self.section_title,
        }
        if self.supplier_name is not None:
            md["supplier_name"] = self.supplier_name
        if self.supplier_id is not None:
            md["supplier_id"] = self.supplier_id
        if self.category is not None:
            md["category"] = self.category
        return md


def _normalize(raw: str) -> str:
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _find_doc_title(text: str) -> str:
    m = _H1.search(text)
    return m.group(1).strip() if m else "Untitled"


def _headings(text: str) -> list[tuple[int, str, str, str]]:
    """Return [(start_offset, level, number, title), ...] in document order.
    level is 'H2' or 'H3'."""
    out = []
    for m in re.finditer(r"^(##|###) (.+)$", text, re.MULTILINE):
        marker, rest = m.group(1), m.group(2).strip()
        h3 = re.match(r"^(\d+\.\d+) (.+)$", rest)
        h2 = re.match(r"^Section (\d+) — (.+)$", rest)
        if marker == "###" and h3:
            out.append((m.start(), "H3", h3.group(1), h3.group(2)))
        elif marker == "##" and h2:
            out.append((m.start(), "H2", h2.group(1), h2.group(2)))
        # anything else (shouldn't occur in this corpus) is skipped, not
        # silently mis-chunked
    return out


def chunk_document(path: Path) -> list[Chunk]:
    raw = _normalize(path.read_text(encoding="utf-8"))
    doc_id = path.stem
    meta = DOC_METADATA.get(doc_id, {})
    doc_title = _find_doc_title(raw)
    headings = _headings(raw)

    chunks: list[Chunk] = []

    # --- Preamble: anything between the H1 title and the first heading
    # (document intro, or the "Supplier ID / Contact / Category" line on
    # contract docs). Skipped if there's nothing but whitespace there. ---
    h1 = _H1.search(raw)
    preamble_start = h1.end() if h1 else 0
    preamble_end = headings[0][0] if headings else len(raw)
    preamble_body = raw[preamble_start:preamble_end].strip()
    if preamble_body:
        chunks.append(Chunk(
            chunk_id=f"{doc_id}::0",
            text=f"{doc_title}\n\n{preamble_body}",
            doc_id=doc_id, doc_type=meta.get("doc_type", "unknown"),
            doc_title=doc_title, section_number="0", section_title="Overview",
            supplier_name=meta.get("supplier_name"), supplier_id=meta.get("supplier_id"),
            category=meta.get("category"),
        ))

    # --- Walk headings; each H3 is always its own chunk. An H2 becomes
    # its own chunk ONLY when it has no H3 content directly under it
    # (e.g. Section 3's shelf-life table, Section 5's closing note) - i.e.
    # when the text between it and the next heading is non-empty. ---
    for i, (start, level, number, title) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(raw)
        body = raw[start:end].strip()

        if level == "H2":
            # body always includes the heading line itself; real content
            # means there's more than just that line.
            heading_line_end = raw.index("\n", start)
            has_own_content = bool(raw[heading_line_end:end].strip())
            if not has_own_content:
                continue  # H3 children will carry this section instead
            section_number, section_title = number, title
            heading_context = f"{doc_title}\n\n"
        else:
            # closest H2 heading *before* this H3, not just the first H2
            # in the document — headings is in document order, so walk it
            # backwards and take the first H2 we hit.
            h2_title = next(
                (t for s, l, n, t in reversed(headings) if l == "H2" and s <= start), ""
            )
            section_number, section_title = number, title
            heading_context = f"{doc_title}" + (f" — {h2_title}" if h2_title else "") + "\n\n"

        chunks.append(Chunk(
            chunk_id=f"{doc_id}::{section_number}",
            text=heading_context + body,
            doc_id=doc_id, doc_type=meta.get("doc_type", "unknown"),
            doc_title=doc_title, section_number=section_number, section_title=section_title,
            supplier_name=meta.get("supplier_name"), supplier_id=meta.get("supplier_id"),
            category=meta.get("category"),
        ))

    return chunks


def chunk_corpus(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    """Chunk every .md file under corpus_dir (recursive), in a stable,
    sorted file order so chunk_id assignment is deterministic across runs."""
    all_chunks: list[Chunk] = []
    for path in sorted(corpus_dir.rglob("*.md")):
        all_chunks.extend(chunk_document(path))
    return all_chunks


if __name__ == "__main__":
    for c in chunk_corpus():
        print(f"{c.chunk_id:45s} | {len(c.text):4d} chars | {c.metadata()}")