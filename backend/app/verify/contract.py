"""What an exercise generator or assessor (model or offline) may propose, and how code checks it.

A generator proposes a scenario and 3-5 criteria; every criterion must point at one item
of the approved knowledge version it is grounded in. An assessor proposes one verdict per
criterion with a quote from the answer. The aggregate result is computed by
app.verify.rules.aggregate, never by the proposer.
"""

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

GUIDANCE_FIELDS = ("prerequisites", "steps", "stop_and_escalate", "success_checks")
# Missing one of these makes an answer unsafe, so only they may carry critical=True.
CRITICAL_FIELDS = ("prerequisites", "stop_and_escalate", "success_checks")
MIN_CRITERIA, MAX_CRITERIA = 3, 5
PATH = re.compile(r"^(?P<field>[a-z_]+)\[(?P<index>\d+)\]$")

Verdict = Literal["met", "partial", "unmet", "uncertain"]


class Criterion(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=3, max_length=400)
    critical: bool = False
    source_path: str  # e.g. "stop_and_escalate[0]"


class ExerciseDraft(BaseModel):
    scenario: str = Field(min_length=20, max_length=2000)
    criteria: list[Criterion]


class CriterionMatch(BaseModel):
    criterion_id: str
    verdict: Verdict
    evidence_quote: str = ""


class Assessment(BaseModel):
    matches: list[CriterionMatch]


class ExerciseGenerator(Protocol):
    model_id: str

    def generate(self, title: str, content: dict) -> ExerciseDraft: ...


class Assessor(Protocol):
    model_id: str

    def assess(self, scenario: str, criteria: list[Criterion], answer: str) -> Assessment: ...


def resolve(content: dict, source_path: str) -> str | None:
    """The approved sentence a source path points to, or None."""
    m = PATH.match(source_path)
    if not m or m["field"] not in GUIDANCE_FIELDS:
        return None
    items = content.get(m["field"]) or []
    index = int(m["index"])
    return items[index] if index < len(items) else None


def validate_exercise(draft: ExerciseDraft, content: dict) -> list[str]:
    """Problems that make a draft ungrounded. Empty list means valid."""
    problems = []
    n = len(draft.criteria)
    if not MIN_CRITERIA <= n <= MAX_CRITERIA:
        problems.append(f"an exercise needs {MIN_CRITERIA}-{MAX_CRITERIA} criteria, not {n}")
    ids = [c.id for c in draft.criteria]
    if len(set(ids)) != len(ids):
        problems.append("criterion ids must be unique")
    for c in draft.criteria:
        if resolve(content, c.source_path) is None:
            problems.append(f"{c.id}: source_path {c.source_path!r} is not approved content")
        elif c.critical and PATH.match(c.source_path)["field"] not in CRITICAL_FIELDS:  # type: ignore[index]
            problems.append(f"{c.id}: only {', '.join(CRITICAL_FIELDS)} criteria may be critical")
    if draft.criteria and not any(c.critical for c in draft.criteria):
        problems.append("at least one criterion must be critical")
    return problems


def validate_matches(
    criteria: list[Criterion], proposal: Assessment, answer: str
) -> tuple[list[CriterionMatch], list[str]]:
    """One checked match per criterion, in rubric order.

    A missing, duplicated or unsupported judgment is not trusted: it becomes `uncertain`
    (which aggregates to review_required) and the reason is kept.
    """
    notes: list[str] = []
    known = {c.id for c in criteria}
    by_id: dict[str, CriterionMatch] = {}
    for m in proposal.matches:
        if m.criterion_id not in known:
            notes.append(f"ignored match for unknown criterion {m.criterion_id}")
        elif m.criterion_id in by_id:
            notes.append(f"{m.criterion_id}: duplicate match, judgment is uncertain")
            by_id[m.criterion_id] = CriterionMatch(criterion_id=m.criterion_id, verdict="uncertain")
        else:
            by_id[m.criterion_id] = m
    out = []
    for c in criteria:
        m = by_id.get(c.id)
        if m is None:
            notes.append(f"{c.id}: no judgment proposed")
            m = CriterionMatch(criterion_id=c.id, verdict="uncertain")
        elif m.evidence_quote and m.evidence_quote not in answer:
            notes.append(f"{c.id}: quote is not in the answer, judgment is uncertain")
            m = CriterionMatch(criterion_id=c.id, verdict="uncertain")
        elif m.verdict in ("met", "partial") and not m.evidence_quote.strip():
            notes.append(f"{c.id}: {m.verdict} without a quote from the answer")
            m = CriterionMatch(criterion_id=c.id, verdict="uncertain")
        out.append(m)
    return out, notes
