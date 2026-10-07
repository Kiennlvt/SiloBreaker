"""Exhaustive checks of the deterministic layer (report Section 4.2, Propositions 1 and 2)."""

import itertools

from app.scoring.rules import (
    CAP,
    AreaObs,
    EventObs,
    participation,
    raw_score,
    round_half_up,
    score_area,
    three_level,
)

LEVELS = (0.0, 0.5, 1.0)
CONFIGS = [dict(zip("ADOMB", v, strict=False)) for v in itertools.product(LEVELS, repeat=5)]


def gated(s):
    if s["D"] == 0:
        return "adequately_covered", None
    if s["O"] == 0:
        return "not_prioritized", None
    raw = raw_score(s)
    capped = s["O"] < 1 or s["B"] == 0
    return ("ranked_capped" if capped else "ranked"), min(raw, CAP) if capped else raw


def test_raw_score_lattice_and_range():
    raws = {raw_score(s) for s in CONFIGS}
    assert len(CONFIGS) == 243
    assert len(raws) == 37
    assert min(raws) == 0 and max(raws) == 100
    assert all((r / 2.5).is_integer() for r in raws)


def test_gates_and_caps_band_membership():
    outcome = [gated(s) for s in CONFIGS]
    counts = {
        k: sum(1 for o, _ in outcome if o == k)
        for k in ("adequately_covered", "not_prioritized", "ranked_capped", "ranked")
    }
    assert counts == {
        "adequately_covered": 81,
        "not_prioritized": 54,
        "ranked_capped": 72,
        "ranked": 36,
    }
    raw_in_band = sum(1 for s in CONFIGS if raw_score(s) >= 75)
    after = sum(1 for _, p in outcome if p is not None and p >= 75)
    assert (raw_in_band, after) == (26, 14)


def test_duplicate_counting_inflates_by_twenty():
    affected = [s for s in CONFIGS if s["D"] > 0 and s["O"] > 0 and s["A"] == 0.5 and s["M"] == 0.5]
    assert len(affected) == 12
    linked = sum(1 for s in affected if raw_score(s) >= 75)
    inflated = sum(1 for s in affected if raw_score({**s, "A": 1.0, "M": 1.0}) >= 75)
    assert all(raw_score({**s, "A": 1.0, "M": 1.0}) - raw_score(s) == 20 for s in affected)
    assert (linked, inflated) == (1, 9)


def test_three_level_and_rounding():
    assert [three_level(n) for n in (0, 1, 2, 7)] == [0, 0.5, 1, 1]
    assert round_half_up(87.5) == 88


def test_participation_unknown_below_minimum():
    o, b, counts = participation((EventObs("E1", "alice", False),), "alice")
    assert o is None and b is None and counts["attributable_events"] == 1


def test_name_mention_without_resolver_is_not_participation():
    events = (EventObs("E1", None, True), EventObs("E2", None, True))
    area = AreaObs("x", "X", events, (), True, 6, frozenset({"jira", "slack", "github"}))
    assert score_area(area, "alice").eligibility_status == "insufficient"


def test_missing_documentation_import_is_unknown_not_a_gap():
    events = tuple(EventObs(f"E{i}", "alice", True) for i in range(3))
    area = AreaObs("x", "X", events, (), False, 6, frozenset({"jira", "slack", "github"}))
    res = score_area(area, "alice")
    assert res.signals["D"] is None and res.eligibility_status == "insufficient"


def test_contradiction_requires_review():
    events = tuple(EventObs(f"E{i}", "alice", True) for i in range(3))
    area = AreaObs(
        "x", "X", events, (), True, 6, frozenset({"jira", "slack", "github"}), contradiction=True
    )
    assert score_area(area, "alice").eligibility_status == "review_required"
