"""Deterministic aggregate exercise outcome (docs/07 'Assessment'). Pure function.

| Condition                                              | Result          |
|--------------------------------------------------------|-----------------|
| any critical criterion clearly unmet                   | not_yet         |
| any uncertain judgment, or a critical one only partial | review_required |
| every criterion met                                    | demonstrated    |
| every critical met, some non-critical partial/unmet    | partial         |

Critical omissions win over uncertainty: an answer that clearly misses a stop condition
is not_yet even if another judgment is unclear.
"""

from app.verify.contract import Criterion, CriterionMatch

RESULTS = ("demonstrated", "partial", "not_yet", "review_required")


def aggregate(criteria: list[Criterion], matches: list[CriterionMatch]) -> str:
    verdict = {m.criterion_id: m.verdict for m in matches}
    if not criteria or set(verdict) != {c.id for c in criteria}:
        return "review_required"
    critical = [verdict[c.id] for c in criteria if c.critical]
    other = [verdict[c.id] for c in criteria if not c.critical]
    if "unmet" in critical:
        return "not_yet"
    if "uncertain" in verdict.values() or "partial" in critical:
        return "review_required"
    if all(v == "met" for v in other):
        return "demonstrated"
    return "partial"
