"""validate_citations must reject structurally dishonest proposals (FR-07, docs/07).

Each case starts from the valid offline extraction of the fixture bundle and breaks one rule.
"""

import uuid

import pytest

from app.analysis.contract import Citation, Extraction, validate_citations
from app.analysis.offline import OfflineExtractor
from app.analysis.service import build_view
from app.db import get_session
from app.models import EvidenceBundle


@pytest.fixture
def view(client):
    session = next(get_session())
    try:
        return build_view(session, session.get(EvidenceBundle, uuid.UUID(client.bundle["id"])))
    finally:
        session.close()


@pytest.fixture
def extraction(view):
    return OfflineExtractor().extract(view)


def _area(extraction: Extraction, key: str):
    return next(a for a in extraction.areas if a.key == key)


def _problems(extraction, view, key="settlement"):
    kept, rejected = validate_citations(extraction, view)
    assert key not in {a.key for a in kept}
    return next(r["problems"] for r in rejected if r["area_key"] == key)


def _chunk_outside(view, refs: set[str]):
    item = next(it for it in view.items if it.ref not in refs)
    chunk = item.chunks[0]
    return Citation(chunk_id=chunk.id, quote=chunk.text[:20])


def test_offline_extraction_is_fully_valid(extraction, view):
    kept, rejected = validate_citations(extraction, view)
    assert rejected == []
    assert {a.key for a in kept} == {a.key for a in extraction.areas}


def test_resolver_must_author_a_record_of_the_event(extraction, view):
    ev = _area(extraction, "settlement").events[0]
    ev.resolver_id = "dan"  # dan wrote nothing in this event
    assert any("resolver" in p for p in _problems(extraction, view))


def test_same_record_in_two_events_is_double_counting(extraction, view):
    area = _area(extraction, "settlement")
    first, second = area.events[0], area.events[1]
    second.record_refs = [*second.record_refs, first.record_refs[0]]
    assert any("more than one event" in p for p in _problems(extraction, view))


def test_area_citation_outside_area_records(extraction, view):
    area = _area(extraction, "settlement")
    area.citations = [_chunk_outside(view, set(area.record_refs))]
    assert any("outside" in p for p in _problems(extraction, view))


def test_event_citation_outside_event_records(extraction, view):
    area = _area(extraction, "settlement")
    ev = area.events[0]
    other = area.events[1]
    # A real chunk of the same area, but from a different event's records.
    item = next(it for it in view.items if it.ref == other.record_refs[0])
    ev.citations = [Citation(chunk_id=item.chunks[0].id, quote=item.chunks[0].text[:20])]
    assert any("outside" in p for p in _problems(extraction, view))


def test_document_citation_outside_document(extraction, view):
    area = _area(extraction, "settlement")
    doc = area.documents[0]
    doc.citations = [_chunk_outside(view, {doc.record_ref})]
    assert any("outside" in p for p in _problems(extraction, view))


def test_event_records_must_belong_to_area(extraction, view):
    area = _area(extraction, "settlement")
    outsider = next(it.ref for it in view.items if it.ref not in area.record_refs)
    area.events[0].record_refs = [*area.events[0].record_refs, outsider]
    assert any("not in area" in p for p in _problems(extraction, view))


def test_document_record_must_belong_to_area(extraction, view):
    area = _area(extraction, "settlement")
    doc = area.documents[0]
    area.record_refs = [r for r in area.record_refs if r != doc.record_ref]
    assert any("not in area" in p for p in _problems(extraction, view))


def test_unknown_document_facet(extraction, view):
    _area(extraction, "settlement").documents[0].facets.append("vibes")
    assert any("facet" in p for p in _problems(extraction, view))
