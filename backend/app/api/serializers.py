from app.models import (
    Analysis,
    EvidenceBundle,
    EvidenceChunk,
    EvidenceItem,
    Finding,
    Handoff,
    KnowledgeDraft,
    KnowledgeVersion,
)


def bundle_out(
    b: EvidenceBundle, people: list[dict] | None = None, item_count: int | None = None
) -> dict:
    return {
        "id": str(b.id),
        "project_key": b.project_key,
        "content_hash": b.content_hash,
        "schema_version": b.schema_version,
        "source_inventory": b.source_inventory,
        "coverage_start": b.coverage_start,
        "coverage_end": b.coverage_end,
        "import_complete": b.import_complete,
        "item_count": item_count,
        "people": people or [],
    }


def handoff_out(h: Handoff) -> dict:
    return {
        "id": str(h.id),
        "project_key": h.project_key,
        "bundle_id": str(h.bundle_id),
        "expert_id": h.expert_id,
        "successor_id": h.successor_id,
        "status": h.status,
        "created_at": h.created_at,
    }


def finding_out(f: Finding) -> dict:
    sv = f.signal_values
    return {
        "id": str(f.id),
        "analysis_id": str(f.analysis_id),
        "area_key": f.area_key,
        "title": f.title,
        "summary": f.summary,
        "question": f.question,
        "signals": sv["signals"],
        "counts": sv["counts"],
        "raw_score": sv["raw"],
        "reasons": sv["reasons"],
        "missing_facets": sv["missing_facets"],
        "top_candidate": sv.get("top_candidate", False),
        "review_priority": f.review_priority,
        "evidence_confidence": f.evidence_confidence,
        "eligibility_status": f.eligibility_status,
        "status": f.status,
        "status_reason": f.status_reason,
        "revision": f.revision,
        "evidence_refs": f.evidence_refs,
    }


def analysis_out(a: Analysis, findings: list[Finding]) -> dict:
    order = {
        "ranked": 0,
        "review_required": 1,
        "adequately_covered": 2,
        "not_prioritized": 3,
        "insufficient": 4,
    }
    findings = sorted(
        findings,
        key=lambda f: (order.get(f.eligibility_status, 9), -(f.review_priority or 0), f.area_key),
    )
    return {
        "id": str(a.id),
        "handoff_id": str(a.handoff_id),
        "bundle_hash": a.bundle_hash,
        "selected_engineer_id": a.selected_engineer_id,
        "model_id": a.model_id,
        "prompt_version": a.prompt_version,
        "schema_version": a.schema_version,
        "scoring_version": a.scoring_version,
        "status": a.status,
        "rejected_areas": a.extraction.get("rejected", []),
        "reused_extraction_from": a.extraction.get("reused_from_analysis"),
        "created_at": a.created_at,
        "findings": [finding_out(f) for f in findings],
    }


def chunk_out(c: EvidenceChunk, item: EvidenceItem) -> dict:
    return {
        "chunk_id": str(c.id),
        "ordinal": c.ordinal,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "text": c.text,
        "text_hash": c.text_hash,
        "item": item_out(item),
    }


def item_out(i: EvidenceItem) -> dict:
    return {
        "id": str(i.id),
        "source": i.source,
        "source_type": i.source_type,
        "external_id": i.external_id,
        "parent_external_id": i.parent_external_id,
        "author_id": i.author_id,
        "author_display_name": i.author_display_name,
        "occurred_at": i.occurred_at,
        "title": i.title,
        "text": i.normalized_text,
        "url": i.source_url,
    }


def draft_out(d: KnowledgeDraft | None) -> dict | None:
    if d is None:
        return None
    return {
        "id": str(d.id),
        "finding_id": str(d.finding_id),
        "revision": d.revision,
        "content": d.content,
        "author_id": d.author_id,
        "updated_at": d.updated_at,
    }


def version_out(v: KnowledgeVersion) -> dict:
    return {
        "id": str(v.id),
        "finding_id": str(v.finding_id),
        "version_no": v.version_no,
        "draft_revision": v.draft_revision,
        "approved_content": v.approved_content,
        "approved_by": v.approved_by,
        "approved_at": v.approved_at,
        "content_hash": v.content_hash,
        "supersedes_version_id": str(v.supersedes_version_id) if v.supersedes_version_id else None,
        "source_refs": v.source_refs,
    }
