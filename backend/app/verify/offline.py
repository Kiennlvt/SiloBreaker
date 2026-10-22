"""Deterministic offline exercise generator and assessor (no API key needed).

The generator only copies approved sentences into criteria; it invents no commands,
thresholds or roles. The assessor is a lexical matcher with a small synonym table, so an
answer in different words can still meet a criterion. It is a stand-in for the model
assessor with the same interface and goes through the same validation and aggregation.
"""

import re

from app.verify.contract import Assessment, Criterion, CriterionMatch, ExerciseDraft

# (field, how many items, critical) in priority order; the rubric is capped at 5.
# Stop/escalate conditions are what make a blind retry unsafe, so they are critical.
PLAN = (
    ("stop_and_escalate", 2, True),
    ("success_checks", 1, False),
    ("steps", 2, False),
    ("prerequisites", 1, True),
)
MAX_CRITERIA = 5

STOPWORDS = set(
    """a an the and or of to for in on at by with from as is are be been it its this that
    these those i i'd i'll i'm we our ours you your they their them he she his her if when
    then than so just also any all can could would should will shall do does did done has
    have had there here what which who whom how why where up out into about over more most
    very only first before after again via one's report reports say says shows show exactly
    use using already ensure make sure must""".split()
)
SYNONYMS = {
    "acmepay": "provider",
    "confirm": "check",
    "verify": "check",
    "look": "check",
    "inspect": "check",
    "settlement": "settle",
    "settled": "settle",
    "accepted": "accept",
    "pause": "stop",
    "halt": "stop",
    "raise": "escalate",
    "escalation": "escalate",
    "unclear": "unknown",
    "contradictory": "unknown",
    "contradicts": "unknown",
    "ambiguous": "unknown",
    "single": "one",
    "create": "submit",
    "trigger": "submit",
    "new": "another",
    "original": "existing",
    "status": "state",
    "happened": "state",
    "located": "locate",
    "find": "locate",
    "reconciled": "reconcile",
}
NEGATIONS = {"not", "never", "no", "without"}
MET, PARTIAL = 0.6, 0.34


def _tokens(text: str) -> set[str]:
    text = text.lower().replace("won't", "will not").replace("n't", " not")
    out = set()
    for w in re.findall(r"[a-z0-9]+", text):
        if w in NEGATIONS:
            out.add("NOT")
            continue
        if w in STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(SYNONYMS.get(w, w))
    return out


def _sentences(answer: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if s.strip()]


class OfflineGenerator:
    model_id = "offline-exercise/1"

    def generate(self, title: str, content: dict) -> ExerciseDraft:
        criteria: list[Criterion] = []
        for field, limit, critical in PLAN:
            for i, text in enumerate((content.get(field) or [])[:limit]):
                if len(criteria) == MAX_CRITERIA:
                    break
                criteria.append(
                    Criterion(
                        id=f"C{len(criteria) + 1}",
                        text=text,
                        critical=critical,
                        source_path=f"{field}[{i}]",
                    )
                )
        scenario = (
            f"You are on call for {title.lower()} ({content['applicability']}). "
            "An alert says this flow needs recovery and nobody who handled it before is "
            "available. Describe what you check first, what you do and in what order, when "
            "you would stop and escalate instead of continuing, and how you confirm the "
            "recovery succeeded."
        )
        return ExerciseDraft(scenario=scenario, criteria=criteria)


class OfflineAssessor:
    model_id = "offline-assessor/1"

    def assess(self, scenario: str, criteria: list[Criterion], answer: str) -> Assessment:
        sentences = _sentences(answer)
        matches = []
        for c in criteria:
            want = _tokens(c.text)
            negated = "NOT" in want
            want.discard("NOT")
            best, quote, best_has_not = 0.0, "", False
            for s in sentences:
                got = _tokens(s)
                cover = len(want & got) / len(want) if want else 0.0
                if cover > best:
                    best, quote, best_has_not = cover, s, "NOT" in got
            if best >= MET and negated and not best_has_not:
                # The answer describes the forbidden action without the prohibition.
                verdict = "unmet"
            elif best >= MET:
                verdict = "met"
            elif best >= PARTIAL:
                verdict = "partial"
            else:
                verdict, quote = "unmet", ""
            matches.append(CriterionMatch(criterion_id=c.id, verdict=verdict, evidence_quote=quote))
        return Assessment(matches=matches)
