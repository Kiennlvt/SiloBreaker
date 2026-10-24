"""Fair successor selection among 2-4 candidates of one handoff.

Every rule here is application code: the assessor only proposes criterion verdicts, the
group of a candidate comes from app.verify.rules.aggregate over (verdicts + expert review
overrides), and only the admin selects. Context from the evidence (incidents a candidate
recovered) is shown next to the result but is never scored.
"""

import random
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.errors import AppError
from app.models import (
    Analysis,
    AppUser,
    Attempt,
    AttemptReview,
    Exercise,
    Finding,
    Handoff,
    HandoffCandidate,
    KnowledgeVersion,
    SuccessorSelection,
)
from app.verify.contract import Criterion, CriterionMatch
from app.verify.rules import aggregate

MIN_CANDIDATES, MAX_CANDIDATES = 2, 4
ALIASES = ("Candidate A", "Candidate B", "Candidate C", "Candidate D")
OVERRIDE_VERDICTS = ("met", "partial", "unmet")

# Best attempt first: a result that still needs review beats a clear not_yet.
RESULT_ORDER = {"demonstrated": 3, "partial": 2, "review_required": 1, "not_yet": 0}
GROUPS = {"demonstrated": "ready", "partial": "ready_with_support", "not_yet": "not_yet"}
GROUP_LABELS = {
    "ready": "Ready",
    "ready_with_support": "Ready with support",
    "not_yet": "Not yet",
    "pending": "Pending",
}
GROUP_RANK = {"ready": 3, "ready_with_support": 2, "not_yet": 1}


# ---------- pure rules ----------


def assign_aliases(person_ids: list[str], seed: str) -> dict[str, str]:
    """A seeded shuffle of the pool. Sorting first means the order the admin typed the
    candidates in does not leak into who becomes Candidate A."""
    order = sorted(person_ids)
    random.Random(f"{seed}:{','.join(order)}").shuffle(order)
    return {pid: ALIASES[i] for i, pid in enumerate(order)}


def effective_matches(
    criterion_results: list[dict], overrides: dict[str, str] | None
) -> list[CriterionMatch]:
    """The assessor's verdicts with the expert's review overrides applied."""
    overrides = overrides or {}
    return [
        CriterionMatch.model_validate(
            m | {"verdict": overrides.get(m["criterion_id"], m["verdict"])}
        )
        for m in criterion_results
    ]


def group_of(result: str | None) -> str:
    return GROUPS.get(result or "", "pending")


def recommend(groups: dict[str, str]) -> list[str]:
    """Everyone in the highest group anyone reached; pending is not a group to rank."""
    ranked = {pid: GROUP_RANK[g] for pid, g in groups.items() if g in GROUP_RANK}
    if not ranked:
        return []
    top = max(ranked.values())
    return sorted(pid for pid, r in ranked.items() if r == top)


# ---------- reads ----------


def handoff_exercises(session: Session, handoff: Handoff) -> list[Exercise]:
    return list(
        session.scalars(
            select(Exercise)
            .join(KnowledgeVersion, Exercise.knowledge_version_id == KnowledgeVersion.id)
            .join(Finding, KnowledgeVersion.finding_id == Finding.id)
            .join(Analysis, Finding.analysis_id == Analysis.id)
            .where(Analysis.handoff_id == handoff.id)
        ).all()
    )


def current_exercise(session: Session, handoff: Handoff) -> Exercise | None:
    """The most recently released exercise of the handoff: the one candidates are compared on."""
    ready = [e for e in handoff_exercises(session, handoff) if e.status == "ready"]
    return max(ready, key=lambda e: e.approved_at, default=None)


def review_of(session: Session, attempt: Attempt) -> AttemptReview | None:
    return session.scalar(select(AttemptReview).where(AttemptReview.attempt_id == attempt.id))


def effective_result(
    attempt: Attempt, exercise: Exercise, review: AttemptReview | None
) -> str | None:
    """The attempt's result after an expert review, recomputed by aggregate()."""
    if attempt.assessment_status != "succeeded":
        return None
    if review is None or review.reviewed_at is None:
        return attempt.aggregate_result
    criteria = [Criterion.model_validate(c) for c in exercise.rubric]
    return aggregate(criteria, effective_matches(attempt.criterion_results, review.overrides))


def attempts_used(session: Session, exercise_id, person_id: str) -> int:
    """Attempts that count toward the limit. A failed one (a system error) never counts."""
    return session.scalar(
        select(func.count()).where(
            Attempt.exercise_id == exercise_id,
            Attempt.successor_id == person_id,
            Attempt.assessment_status != "failed",
        )
    )


# ---------- candidate rules for attempts ----------


def check_can_attempt(session: Session, handoff: Handoff, exercise: Exercise, actor: str) -> None:
    """Candidates must open the study material first and get max_attempts results."""
    candidate = handoff.candidate(actor)
    if candidate is None:
        return
    if candidate.study_opened_at is None:
        raise AppError(409, "study_required", "open the study material before answering")
    if attempts_used(session, exercise.id, actor) >= handoff.max_attempts:
        raise AppError(
            409, "attempt_limit", f"each candidate has {handoff.max_attempts} assessed attempts"
        )


def check_can_reassess(session: Session, handoff: Handoff, attempt: Attempt) -> None:
    """Reassessing a failed attempt must not give a candidate one result too many."""
    if handoff.candidate(attempt.successor_id) is None:
        return
    if attempts_used(session, attempt.exercise_id, attempt.successor_id) >= handoff.max_attempts:
        raise AppError(
            409, "attempt_limit", f"each candidate has {handoff.max_attempts} assessed attempts"
        )


def open_study(session: Session, handoff: Handoff, actor: str) -> HandoffCandidate:
    candidate = handoff.candidate(actor)
    if candidate is None:
        raise AppError(403, "not_candidate", "only a candidate of a selecting handoff may do this")
    if candidate.study_opened_at is None:
        candidate.study_opened_at = datetime.now(UTC)
        session.flush()
        audit(session, handoff.id, actor, "study.opened", "handoff_candidate", candidate.id)
    return candidate


# ---------- review (phúc khảo) ----------


def request_review(
    session: Session, attempt: Attempt, handoff: Handoff, actor: str
) -> AttemptReview:
    if attempt.successor_id != actor:
        raise AppError(403, "not_owner", "this attempt belongs to someone else")
    if attempt.assessment_status != "succeeded":
        raise AppError(409, "not_assessed", "only an assessed attempt can be reviewed")
    if review_of(session, attempt) is not None:
        raise AppError(409, "review_already_requested", "a review was already requested")
    review = AttemptReview(attempt_id=attempt.id, requested_at=datetime.now(UTC))
    session.add(review)
    session.flush()
    audit(session, handoff.id, actor, "attempt.review_requested", "attempt", attempt.id)
    return review


def review_attempt(
    session: Session,
    attempt: Attempt,
    exercise: Exercise,
    handoff: Handoff,
    overrides: dict[str, str],
    reason: str,
    actor: str,
) -> AttemptReview:
    if not reason.strip():
        raise AppError(422, "reason_required", "a review needs a reason")
    known = {c["id"] for c in exercise.rubric}
    if not overrides:
        raise AppError(422, "invalid_overrides", "a review changes at least one criterion")
    for cid, verdict in overrides.items():
        if cid not in known:
            raise AppError(422, "invalid_overrides", f"unknown criterion {cid}")
        if verdict not in OVERRIDE_VERDICTS:
            raise AppError(
                422, "invalid_overrides", f"{cid}: verdict must be one of met, partial, unmet"
            )
    review = review_of(session, attempt)
    if review is None:
        raise AppError(409, "review_not_requested", "the learner has not requested a review")
    if review.reviewed_at is not None:
        raise AppError(409, "already_reviewed", "this attempt was already reviewed")
    review.overrides = dict(overrides)
    review.reason = reason.strip()
    review.reviewed_by = actor
    review.reviewed_at = datetime.now(UTC)
    session.flush()
    audit(
        session,
        handoff.id,
        actor,
        "attempt.reviewed",
        "attempt",
        attempt.id,
        metadata={
            "overrides": review.overrides,
            "original_result": attempt.aggregate_result,
            "effective_result": effective_result(attempt, exercise, review),
        },
    )
    return review


# ---------- readiness and selection ----------


def candidate_context(session: Session, handoff: Handoff) -> dict[str, dict]:
    """Incidents each person recovered in the handoff's areas, from the stored extraction
    of the latest analysis. Shown for context only: it is never part of the group."""
    analysis = session.scalar(
        select(Analysis)
        .where(Analysis.handoff_id == handoff.id, Analysis.status == "succeeded")
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    by_person: dict[str, dict[str, set]] = {}
    if analysis is not None:
        keys = set(
            session.scalars(select(Finding.area_key).where(Finding.analysis_id == analysis.id))
        )
        for area in analysis.extraction.get("proposal", {}).get("areas", []):
            if area["key"] not in keys:
                continue
            for e in area.get("events", []):
                if e.get("resolver_id"):
                    by_person.setdefault(e["resolver_id"], {}).setdefault(area["key"], set()).add(
                        e["key"]
                    )
    out = {}
    for c in handoff.candidates:
        areas = {k: len(v) for k, v in sorted(by_person.get(c.person_id, {}).items())}
        out[c.person_id] = {
            "recovered_incidents": sum(areas.values()),
            "by_area": areas,
            "analysis_id": str(analysis.id) if analysis else None,
            "scored": False,
            "note": "context only; not part of the group or the recommendation",
        }
    return out


def readiness(session: Session, handoff: Handoff) -> dict:
    if not handoff.candidates:
        raise AppError(409, "no_candidates", "this handoff was created with a single successor")
    exercise = current_exercise(session, handoff)
    context = candidate_context(session, handoff)
    names = dict(
        session.execute(
            select(AppUser.person_id, AppUser.display_name).where(
                AppUser.person_id.in_([c.person_id for c in handoff.candidates])
            )
        ).all()
    )
    rows, warnings, groups = [], [], {}
    for c in handoff.candidates:
        best, used, review_open = None, 0, False
        if exercise is not None:
            attempts = session.scalars(
                select(Attempt)
                .where(Attempt.exercise_id == exercise.id, Attempt.successor_id == c.person_id)
                .order_by(Attempt.created_at)
            ).all()
            used = sum(a.assessment_status != "failed" for a in attempts)
            scored = []
            for a in attempts:
                review = review_of(session, a)
                review_open = review_open or (review is not None and review.reviewed_at is None)
                result = effective_result(a, exercise, review)
                if result is not None:
                    scored.append((a, result, review))
            # Highest result wins; among equals, the earliest attempt (max keeps the first).
            best = max(scored, key=lambda s: RESULT_ORDER[s[1]], default=None)
        group = group_of(best[1] if best else None)
        groups[c.person_id] = group
        criteria = None
        if best is not None:
            a, _, review = best
            overrides = (review.overrides or {}) if review and review.reviewed_at else {}
            criteria = [
                {
                    "criterion_id": m.criterion_id,
                    "verdict": m.verdict,
                    "overridden": m.criterion_id in overrides,
                }
                for m in effective_matches(a.criterion_results, overrides)
            ]
        rows.append(
            {
                "person_id": c.person_id,
                "display_name": names.get(c.person_id),
                "alias": c.alias,
                "group": group,
                "group_label": GROUP_LABELS[group],
                "best_attempt_id": str(best[0].id) if best else None,
                "best_result": best[1] if best else None,
                "criteria": criteria,
                "attempts_used": used,
                "max_attempts": handoff.max_attempts,
                "study_opened": c.study_opened_at is not None,
                "review_pending": review_open,
                "context": context[c.person_id],
            }
        )
        if best is None:
            warnings.append({"person_id": c.person_id, "code": "no_result"})
        elif group == "pending":
            warnings.append({"person_id": c.person_id, "code": "pending"})
        if review_open:
            warnings.append({"person_id": c.person_id, "code": "review_pending"})
    if exercise is None:
        warnings.insert(0, {"person_id": None, "code": "no_released_exercise"})
    return {
        "handoff_id": str(handoff.id),
        "status": handoff.status,
        "exercise_id": str(exercise.id) if exercise else None,
        "candidates": rows,
        "recommended": recommend(groups),
        "warnings": warnings,
    }


def select_successor(
    session: Session, handoff: Handoff, person_id: str, reason: str | None, actor: str
) -> SuccessorSelection:
    if (
        session.scalar(
            select(SuccessorSelection).where(SuccessorSelection.handoff_id == handoff.id)
        )
        is not None
        or handoff.status != "selecting"
    ):
        raise AppError(409, "already_selected", "a successor has already been selected")
    if handoff.candidate(person_id) is None:
        raise AppError(422, "not_candidate", f"'{person_id}' is not a candidate of this handoff")
    recommended = readiness(session, handoff)["recommended"]
    in_recommended = person_id in recommended
    reason = (reason or "").strip() or None
    if not in_recommended and reason is None:
        raise AppError(
            422, "reason_required", "selecting someone outside the recommendation needs a reason"
        )
    selection = SuccessorSelection(
        handoff_id=handoff.id,
        selected_person_id=person_id,
        recommended=recommended,
        in_recommended=in_recommended,
        reason=reason,
        decided_by=actor,
        decided_at=datetime.now(UTC),
    )
    session.add(selection)
    handoff.successor_id = person_id
    handoff.status = "active"
    session.flush()
    audit(
        session,
        handoff.id,
        actor,
        "successor.selected",
        "handoff",
        handoff.id,
        metadata={
            "selected_person_id": person_id,
            "recommended": recommended,
            "in_recommended": in_recommended,
            "reason": reason,
        },
    )
    return selection
