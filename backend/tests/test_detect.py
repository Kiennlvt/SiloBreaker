"""Acceptance tests for Detect (report Table 3, rows 1 to 8)."""

import json

from app.analysis.contract import Citation, Extraction, ProposedArea
from app.analysis.offline import OfflineExtractor
from app.analysis.service import build_view, run_analysis
from app.db import get_session
from app.models import EvidenceBundle, Handoff
from tests.conftest import ORACLE, analyze, by_area, make_handoff

FORBIDDEN = [
    "target_gap",
    "expected",
    "expert_capture",
    "successor_answers",
    "correct_paraphrase",
    "review_priority",
    "eligibility_status",
    "oracle",
]


def _view(client):
    session = next(get_session())
    try:
        bundle = session.get(EvidenceBundle, __import__("uuid").UUID(client.bundle["id"]))
        return build_view(session, bundle)
    finally:
        session.close()


def test_label_isolation(client):
    payload = _view(client).model_dump_json()
    for word in FORBIDDEN:
        assert word not in payload, f"model input contains '{word}'"
    oracle_text = " ".join(p.read_text() for p in ORACLE.glob("*.json"))
    for answer in json.loads((ORACLE / "successor_answers.json").read_text()).values():
        assert answer not in payload
    assert "correct_paraphrase" in oracle_text  # sanity: the oracle is really there


def test_multiple_areas_and_designed_outcomes_for_alice(client, oracle):
    a = by_area(analyze(client, make_handoff(client)))
    exp = oracle["expected_findings"]["expected"]
    assert set(a) == set(exp)
    for key, e in exp.items():
        assert a[key]["eligibility_status"] == e["eligibility_status"], key
        assert a[key]["review_priority"] == e["review_priority"], key
        if "signals" in e:
            assert a[key]["signals"] == {k: float(v) for k, v in e["signals"].items()}, key
            assert a[key]["raw_score"] == e["raw"], key


def test_primary_finding_ranked_above_controls_with_question(client):
    analysis = analyze(client, make_handoff(client))
    ranked = [f for f in analysis["findings"] if f["top_candidate"]]
    assert ranked[0]["area_key"] == "settlement"
    assert ranked[0]["evidence_confidence"] == "high"
    assert "stop and escalate" in ranked[0]["question"]
    capped = by_area(analysis)["webhooks"]
    assert capped["review_priority"] == 60 and len(capped["reasons"]) == 2


def test_duplicate_event_representation_counts_once(client, oracle):
    s = by_area(analyze(client, make_handoff(client)))["settlement"]
    assert (
        s["counts"]["distinct_events"] == oracle["expected_findings"]["settlement_distinct_events"]
    )
    assert s["counts"]["linked_records"] > s["counts"]["distinct_events"] * 3


def test_actor_change_reuses_extraction(client, oracle):
    h = make_handoff(client)
    first = analyze(client, h, "alice")
    second = analyze(client, h, "bob")
    assert second["reused_extraction_from"] == first["id"]
    exp = oracle["expected_findings"]["bob_selected"]["settlement"]
    s = by_area(second)["settlement"]
    assert s["eligibility_status"] == exp["eligibility_status"]
    assert s["raw_score"] == exp["raw"]


def test_prompt_injection_in_evidence_has_no_effect(client):
    fx = by_area(analyze(client, make_handoff(client)))["fx-rates"]
    assert fx["eligibility_status"] == "insufficient" and fx["review_priority"] is None


def test_every_displayed_citation_resolves(client):
    for f in analyze(client, make_handoff(client))["findings"]:
        assert f["evidence_refs"]
        for ref in f["evidence_refs"]:
            r = client.get(f"/api/chunks/{ref['chunk_id']}")
            assert r.status_code == 200
            assert ref["quote"] in r.json()["text"]


class _LyingExtractor(OfflineExtractor):
    model_id = "lying/1"

    def extract(self, view):
        good = super().extract(view)
        chunk = view.items[0].chunks[0].id
        bad = ProposedArea(
            key="invented",
            title="Invented",
            record_refs=[],
            citations=[Citation(chunk_id=chunk, quote="this text was never written")],
        )
        return Extraction(areas=[*good.areas, bad])


def test_invalid_citation_is_rejected_not_displayed(client):
    h = make_handoff(client)
    session = next(get_session())
    try:
        handoff = session.get(Handoff, __import__("uuid").UUID(h["id"]))
        analysis = run_analysis(session, handoff, "alice", extractor=_LyingExtractor())
        session.commit()
        aid = str(analysis.id)
    finally:
        session.close()
    out = client.get(f"/api/analyses/{aid}").json()
    assert "invented" not in by_area(out)
    assert out["rejected_areas"][0]["area_key"] == "invented"


def test_analysis_idempotency(client):
    h = make_handoff(client)
    a1 = analyze(client, h, "alice", key="k-1")
    a2 = analyze(client, h, "alice", key="k-1")
    assert a1["id"] == a2["id"]
    r = client.post(
        f"/api/handoffs/{h['id']}/analyses",
        json={"selected_engineer_id": "bob"},
        headers={"Idempotency-Key": "k-1"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reused"


def test_source_coverage_inventory(client):
    inv = client.bundle["source_inventory"]
    assert inv == {
        "jira": "included",
        "slack": "included",
        "github": "included",
        "document": "included",
    }
    assert client.bundle["item_count"] == 34
