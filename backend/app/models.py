"""PostgreSQL schema, one class per table in docs/05_DATA_MODEL_POSTGRES.md."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundle"
    id: Mapped[uuid.UUID] = _id()
    project_key: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_inventory: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()

    items: Mapped[list["EvidenceItem"]] = relationship(back_populates="bundle")


class EvidenceItem(Base):
    __tablename__ = "evidence_item"
    __table_args__ = (
        UniqueConstraint("bundle_id", "source", "external_id"),
        Index("idx_evidence_item_bundle_source_time", "bundle_id", "source", "occurred_at"),
    )
    id: Mapped[uuid.UUID] = _id()
    bundle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_bundle.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str | None] = mapped_column(Text)
    author_display_name: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()

    bundle: Mapped[EvidenceBundle] = relationship(back_populates="items")
    chunks: Mapped[list["EvidenceChunk"]] = relationship(
        back_populates="item", order_by="EvidenceChunk.ordinal"
    )


class EvidenceChunk(Base):
    __tablename__ = "evidence_chunk"
    __table_args__ = (UniqueConstraint("evidence_item_id", "ordinal"),)
    id: Mapped[uuid.UUID] = _id()
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_item.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)

    item: Mapped[EvidenceItem] = relationship(back_populates="chunks")


class Handoff(Base):
    __tablename__ = "handoff"
    id: Mapped[uuid.UUID] = _id()
    project_key: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_bundle.id"), nullable=False)
    expert_id: Mapped[str] = mapped_column(Text, nullable=False)
    successor_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = _now()


class Analysis(Base):
    __tablename__ = "analysis"
    __table_args__ = (
        Index("idx_analysis_handoff_created", "handoff_id", "created_at"),
        CheckConstraint("status in ('pending','running','succeeded','failed')"),
    )
    id: Mapped[uuid.UUID] = _id()
    handoff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("handoff.id"), nullable=False)
    bundle_hash: Mapped[str] = mapped_column(Text, nullable=False)
    selected_engineer_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_version: Mapped[str] = mapped_column(Text, nullable=False)
    extraction: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = _now()

    findings: Mapped[list["Finding"]] = relationship(back_populates="analysis")


class Finding(Base):
    __tablename__ = "finding"
    __table_args__ = (
        CheckConstraint("status in ('candidate','confirmed','rejected','obsolete')"),
        CheckConstraint(
            "eligibility_status in "
            "('ranked','adequately_covered','not_prioritized','insufficient','review_required')"
        ),
        CheckConstraint("evidence_confidence in ('high','medium','low')"),
        CheckConstraint("review_priority is null or review_priority between 0 and 100"),
    )
    id: Mapped[uuid.UUID] = _id()
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis.id"), nullable=False)
    area_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    signal_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_priority: Mapped[int | None] = mapped_column(SmallInteger)
    evidence_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_status: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="candidate")
    status_reason: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    analysis: Mapped[Analysis] = relationship(back_populates="findings")


Index(
    "idx_finding_analysis_priority",
    Finding.analysis_id,
    Finding.eligibility_status,
    Finding.review_priority.desc().nulls_last(),
)


class KnowledgeDraft(Base):
    __tablename__ = "knowledge_draft"
    __table_args__ = (UniqueConstraint("finding_id"),)
    id: Mapped[uuid.UUID] = _id()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    author_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeVersion(Base):
    """Immutable. Rows are inserted, never updated (enforced by a trigger in the migration)."""

    __tablename__ = "knowledge_version"
    __table_args__ = (
        UniqueConstraint("finding_id", "version_no"),
        Index("idx_knowledge_version_finding_version", "finding_id", "version_no"),
    )
    id: Mapped[uuid.UUID] = _id()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False)
    expert_added_context: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approved_by: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = _now()
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_version.id")
    )


class Exercise(Base):
    __tablename__ = "exercise"
    __table_args__ = (CheckConstraint("status in ('draft','ready','obsolete')"),)
    id: Mapped[uuid.UUID] = _id()
    knowledge_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_version.id"), nullable=False
    )
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class Attempt(Base):
    __tablename__ = "attempt"
    __table_args__ = (
        Index("idx_attempt_exercise_created", "exercise_id", "created_at"),
        CheckConstraint("assessment_status in ('pending','succeeded','failed')"),
        CheckConstraint(
            "aggregate_result is null or aggregate_result in "
            "('demonstrated','partial','not_yet','review_required')"
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exercise.id"), nullable=False)
    successor_id: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    criterion_results: Mapped[list | None] = mapped_column(JSONB)
    aggregate_result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Operation(Base):
    __tablename__ = "operation"
    __table_args__ = (
        UniqueConstraint("kind", "idempotency_key"),
        Index("idx_operation_state_created", "state", "created_at"),
        CheckConstraint("state in ('pending','running','succeeded','failed','interrupted')"),
    )
    id: Mapped[uuid.UUID] = _id()
    handoff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("handoff.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    result_type: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    handoff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("handoff.id"))
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_revision: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _now()
