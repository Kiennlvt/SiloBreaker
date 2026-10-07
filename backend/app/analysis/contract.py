"""What an extractor (model or offline rules) may propose, and how it is checked.

The extractor receives a BundleView: normalized evidence with chunk IDs and nothing else.
Its output is a proposal. Application code validates every citation before any of it is
scored or shown (FR-07), and computes all numbers itself (FR-08).
"""

from typing import Protocol

from pydantic import BaseModel, Field


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


def validate_citations(
    extraction: Extraction, view: BundleView
) -> tuple[list[ProposedArea], list[dict]]:
    """Keep only areas whose every reference resolves to stored evidence."""
    chunks = {c.id: c.text for it in view.items for c in it.chunks}
    refs = {it.ref for it in view.items}
    kept, rejected = [], []
    for area in extraction.areas:
        problems = []
        cites = list(area.citations)
        for ev in area.events:
            cites += ev.citations
            problems += [
                f"event {ev.key}: unknown record {r}" for r in ev.record_refs if r not in refs
            ]
        for doc in area.documents:
            cites += doc.citations
            if doc.record_ref not in refs:
                problems.append(f"unknown document {doc.record_ref}")
        problems += [f"unknown record {r}" for r in area.record_refs if r not in refs]
        for c in cites:
            if c.chunk_id not in chunks:
                problems.append(f"citation to unknown chunk {c.chunk_id}")
            elif c.quote not in chunks[c.chunk_id]:
                problems.append(f"quote not found in chunk {c.chunk_id}: {c.quote[:60]!r}")
        if problems:
            rejected.append({"area_key": area.key, "problems": problems})
        else:
            kept.append(area)
    return kept, rejected
