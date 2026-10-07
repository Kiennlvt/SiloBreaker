"""Detect flow (docs/03 'Detect flow')."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.analysis.contract import (
    BundleView,
    ChunkView,
    Extraction,
    Extractor,
    ItemView,
    ProposedArea,
    validate_citations,
)
from app.analysis.offline import OfflineExtractor
from app.audit import audit
from app.config import get_settings
from app.errors import AppError
from app.models import Analysis, EvidenceBundle, EvidenceItem, Finding, Handoff
from app.scoring.rules import SCORING_VERSION, AreaObs, EventObs, ScoreResult, rank, score_area

FACET_QUESTIONS = {
    "preconditions": "what must be true before they start",
    "steps": "which steps they take and in what order",
    "stop_and_escalate": "when they must stop and escalate instead of continuing",
    "success_checks": "how they confirm the recovery actually succeeded",
}


def get_extractor() -> Extractor:
    provider = get_settings().ai_provider
    if provider == "offline":
        return OfflineExtractor()
    raise AppError(
        503, "provider_not_configured", f"AI provider '{provider}' is not configured in this build"
    )


def item_ref(item: EvidenceItem) -> str:
    return f"{item.source}:{item.external_id}"


def build_view(session: Session, bundle: EvidenceBundle) -> BundleView:
    """The complete model input. Contains evidence only: no labels, ranks or answers."""
    items = session.scalars(
        select(EvidenceItem)
        .where(EvidenceItem.bundle_id == bundle.id)
        .options(selectinload(EvidenceItem.chunks))
        .order_by(EvidenceItem.source, EvidenceItem.external_id)
    ).all()
    by_ext = {(i.source, i.external_id): i for i in items}
    return BundleView(
        project_key=bundle.project_key,
        source_inventory=bundle.source_inventory,
        items=[
            ItemView(
                ref=item_ref(i),
                source=i.source,
                source_type=i.source_type,
                parent_ref=item_ref(by_ext[(i.source, i.parent_external_id)])
                if (i.source, i.parent_external_id) in by_ext
                else None,
                author_id=i.author_id,
                occurred_at=i.occurred_at.isoformat() if i.occurred_at else None,
                title=i.title,
                metadata=i.metadata_,
                chunks=[ChunkView(id=str(c.id), ordinal=c.ordinal, text=c.text) for c in i.chunks],
            )
            for i in items
        ],
    )


def to_observation(area: ProposedArea, view: BundleView) -> AreaObs:
    sources = {it.ref: it.source for it in view.items}
    return AreaObs(
        key=area.key,
        title=area.title,
        events=tuple(
            EventObs(e.key, e.resolver_id, e.manual, tuple(e.record_refs)) for e in area.events
        ),
        doc_facets=tuple(frozenset(d.facets) for d in area.documents),
        docs_family_included=view.source_inventory.get("document") == "included",
        record_count=len(area.record_refs),
        source_families=frozenset(sources[r] for r in area.record_refs),
        contradiction=area.contradiction,
    )


def explain(area: ProposedArea, res: ScoreResult, selected: str) -> tuple[str, str | None]:
    c = res.counts
    keys = ", ".join(e.key for e in area.events) or "none"
    parts = [f"{c['distinct_events']} distinct event(s) in the supplied evidence ({keys})."]
    if c["participation_share"] is not None:
        parts.append(
            f"Recorded recovery activity: {selected} in {c['events_by_selected']} of "
            f"{c['attributable_events']} attributable event(s), others in "
            f"{c['events_by_others']}."
        )
    parts.append(f"{c['manual_events']} event(s) involved manual intervention.")
    if res.signals["D"] is None:
        parts.append("Documentation was not imported, so coverage is unknown.")
    elif c["relevant_documents"] == 0:
        parts.append("No relevant procedure was found in the supplied documentation.")
    elif res.missing_facets:
        parts.append(
            "The supplied runbook does not cover: "
            + ", ".join(f.replace("_", " ") for f in res.missing_facets)
            + "."
        )
    else:
        parts.append("The supplied runbook covers every required facet.")
    question = None
    if res.eligibility_status == "ranked" and res.missing_facets:
        asks = [FACET_QUESTIONS[f] for f in res.missing_facets]
        joined = asks[0] if len(asks) == 1 else ", ".join(asks[:-1]) + " and " + asks[-1]
        question = f"For {area.title.lower()}, what does on-call need to know about {joined}?"
    return " ".join(parts), question


def run_analysis(
    session: Session, handoff: Handoff, selected_engineer: str, extractor: Extractor | None = None
) -> Analysis:
    settings = get_settings()
    bundle = session.get(EvidenceBundle, handoff.bundle_id)
    assert bundle is not None
    extractor = extractor or get_extractor()
    view = build_view(session, bundle)

    # FR-10: an actor change reuses the frozen extraction instead of re-running the model.
    previous = session.scalar(
        select(Analysis)
        .where(
            Analysis.bundle_hash == bundle.content_hash,
            Analysis.model_id == extractor.model_id,
            Analysis.prompt_version == settings.prompt_version,
            Analysis.status == "succeeded",
        )
        .order_by(Analysis.created_at.desc())
    )
    if previous:
        proposal = Extraction.model_validate(previous.extraction["proposal"])
        reused_from = str(previous.id)
    else:
        try:
            proposal = extractor.extract(view)
        except Exception as exc:  # provider failure is a system error, never a finding
            raise AppError(502, "provider_error", f"Extraction failed: {exc}") from exc
        reused_from = None

    kept, rejected = validate_citations(proposal, view)
    analysis = Analysis(
        handoff_id=handoff.id,
        bundle_hash=bundle.content_hash,
        selected_engineer_id=selected_engineer,
        model_id=extractor.model_id,
        prompt_version=settings.prompt_version,
        schema_version=settings.schema_version,
        scoring_version=SCORING_VERSION,
        extraction={
            "proposal": proposal.model_dump(),
            "rejected": rejected,
            "reused_from_analysis": reused_from,
        },
        status="succeeded",
    )
    session.add(analysis)
    session.flush()

    results = {a.key: score_area(to_observation(a, view), selected_engineer) for a in kept}
    top = set(rank(results))
    for area in kept:
        res = results[area.key]
        summary, question = explain(area, res, selected_engineer)
        # Every area is stored for transparency; `top_candidate` marks the (at most 3)
        # ranked areas surfaced as candidates.
        status = res.eligibility_status
        refs = [c.model_dump() for c in area.citations]
        for e in area.events:
            refs += [c.model_dump() | {"event": e.key} for c in e.citations]
        for d in area.documents:
            refs += [c.model_dump() | {"document": d.record_ref} for c in d.citations]
        session.add(
            Finding(
                analysis_id=analysis.id,
                area_key=area.key,
                title=area.title,
                summary=summary,
                question=question,
                signal_values={
                    "signals": res.signals,
                    "counts": res.counts,
                    "raw": res.raw,
                    "reasons": res.reasons,
                    "missing_facets": res.missing_facets,
                    "top_candidate": area.key in top,
                },
                review_priority=res.review_priority,
                evidence_confidence=res.evidence_confidence,
                eligibility_status=status,
                evidence_refs=refs,
            )
        )
    audit(
        session,
        handoff.id,
        "system",
        "analysis.completed",
        "analysis",
        analysis.id,
        metadata={
            "selected_engineer": selected_engineer,
            "areas": len(kept),
            "rejected_areas": len(rejected),
        },
    )
    session.flush()
    return analysis
