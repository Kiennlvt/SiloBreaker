"""What an extractor (model or offline rules) may propose, and how it is checked.

The extractor receives a BundleView: normalized evidence with chunk IDs and nothing else.
Its output is a proposal. Application code validates every citation before any of it is
scored or shown (FR-07), and computes all numbers itself (FR-08).
"""

from typing import Protocol

from pydantic import BaseModel, Field

from app.scoring.rules import REQUIRED_DOC_FACETS


class ChunkView(BaseModel):
    id: str
    ordinal: int
    text: str


class ItemView(BaseModel):
    ref: str  # "<source>:<external_id>", the only record identifier a proposal may use
    source: str
    source_type: str
    parent_ref: str | None
    author_id: str | None
    occurred_at: str | None
    title: str | None
    metadata: dict
    chunks: list[ChunkView]


class BundleView(BaseModel):
    project_key: str
    source_inventory: dict[str, str]
    items: list[ItemView]


class Citation(BaseModel):
    chunk_id: str
    quote: str = Field(min_length=3, max_length=400)


class ProposedEvent(BaseModel):
    key: str
    record_refs: list[str]
    resolver_id: str | None = None
    manual: bool = False
    citations: list[Citation] = Field(min_length=1)


class ProposedDocument(BaseModel):
    record_ref: str
    facets: list[str]
    citations: list[Citation] = Field(min_length=1)


class ProposedArea(BaseModel):
    key: str
    title: str
    record_refs: list[str]
    events: list[ProposedEvent] = []
    documents: list[ProposedDocument] = []
    contradiction: bool = False
    citations: list[Citation] = Field(min_length=1)


class Extraction(BaseModel):
    areas: list[ProposedArea]


class Extractor(Protocol):
    model_id: str

    def extract(self, view: BundleView) -> Extraction: ...


def _check(
    cites: list[Citation],
    scope: set[str],
    where: str,
    chunks: dict[str, str],
    chunk_owner: dict[str, str],
) -> list[str]:
    """Each quote must be stored text of a chunk owned by one of `scope`'s records."""
    problems = []
    for c in cites:
        if c.chunk_id not in chunks:
            problems.append(f"{where}: citation to unknown chunk {c.chunk_id}")
        elif c.quote not in chunks[c.chunk_id]:
            problems.append(f"{where}: quote not found in chunk {c.chunk_id}: {c.quote[:60]!r}")
        elif chunk_owner[c.chunk_id] not in scope:
            problems.append(f"{where}: citation to {chunk_owner[c.chunk_id]}, outside its records")
    return problems


def validate_citations(
    extraction: Extraction, view: BundleView
) -> tuple[list[ProposedArea], list[dict]]:
    """Keep only areas whose every reference resolves to stored evidence and is consistent.

    Beyond quote membership this rejects proposals that would distort the counts:
    a resolver who wrote nothing in the event, one record counted in two events, citations
    or records that fall outside the area/event/document they support, unknown facets.
    """
    chunks = {c.id: c.text for it in view.items for c in it.chunks}
    chunk_owner = {c.id: it.ref for it in view.items for c in it.chunks}
    authors = {it.ref: it.author_id for it in view.items}
    kept, rejected = [], []
    for area in extraction.areas:
        problems: list[str] = []
        area_refs = set(area.record_refs)
        problems += [f"unknown record {r}" for r in area.record_refs if r not in authors]

        problems += _check(area.citations, area_refs, f"area {area.key}", chunks, chunk_owner)
        seen_in: dict[str, str] = {}
        for ev in area.events:
            where = f"event {ev.key}"
            refs = set(ev.record_refs)
            for r in ev.record_refs:
                if r not in authors:
                    problems.append(f"{where}: unknown record {r}")
                elif r not in area_refs:
                    problems.append(f"{where}: record {r} not in area records")
                if r in seen_in and seen_in[r] != ev.key:
                    problems.append(
                        f"{where}: record {r} is in more than one event (also {seen_in[r]})"
                    )
                seen_in.setdefault(r, ev.key)
            if ev.resolver_id and ev.resolver_id not in {authors.get(r) for r in refs}:
                problems.append(f"{where}: resolver {ev.resolver_id} authored none of its records")
            problems += _check(ev.citations, refs, where, chunks, chunk_owner)
        for doc in area.documents:
            where = f"document {doc.record_ref}"
            if doc.record_ref not in authors:
                problems.append(f"unknown document {doc.record_ref}")
            elif doc.record_ref not in area_refs:
                problems.append(f"{where}: record not in area records")
            bad = [f for f in doc.facets if f not in REQUIRED_DOC_FACETS]
            if bad:
                problems.append(f"{where}: unknown facet(s) {', '.join(bad)}")
            problems += _check(doc.citations, {doc.record_ref}, where, chunks, chunk_owner)
        if problems:
            rejected.append({"area_key": area.key, "problems": problems})
        else:
            kept.append(area)
    return kept, rejected
