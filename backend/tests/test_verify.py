"""Acceptance tests for Verify (FR-17 to FR-22; docs/09 verification matrix)."""

import uuid

import pytest
from sqlalchemy import text

from app.db import get_session
from app.errors import AppError
from app.verify import service as V
from app.verify.contract import (
    Assessment,
    Criterion,
    CriterionMatch,
    ExerciseDraft,
    validate_exercise,
    validate_matches,
)
from app.verify.offline import OfflineAssessor
from app.verify.rules import aggregate
from tests.conftest import analyze, by_area, make_handoff

EXPERT, SUCCESSOR = "alice", "bob"


# ---------- helpers ----------


def publish_settlement(client, oracle):
    f = by_area(analyze(client, make_handoff(client)))["settlement"]
    f = client.post(
        f"/api/findings/{f['id']}/review",
        json={"action": "confirm", "actor_id": EXPERT, "expected_revision": f["revision"]},
    ).json()
    d = client.put(
        f"/api/findings/{f['id']}/draft",
        json={"content": oracle["expert_capture"]["content"], "author_id": EXPERT},
    ).json()
    v = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": d["revision"],
            "approver_id": EXPERT,
        },
    ).json()
    return f, d, v


def generate(client, version_id, actor=EXPERT):
    return client.post(f"/api/knowledge/{version_id}/exercises", json={"actor_id": actor})


def release(client, ex):
    r = client.post(
        f"/api/exercises/{ex['id']}/approve",
        json={"expected_revision": ex["revision"], "actor_id": EXPERT},
    )
    assert r.status_code == 200, r.text
    return r.json()


def submit(client, ex_id, answer, key=None, actor=SUCCESSOR):
    return client.post(
        f"/api/exercises/{ex_id}/attempts",
        json={"actor_id": actor, "answer": answer},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


@pytest.fixture
def ready(client, oracle):
    f, d, v = publish_settlement(client, oracle)
    r = generate(client, v["id"])
    assert r.status_code == 201, r.text
    return {"finding": f, "draft": d, "version": v, "exercise": release(client, r.json())}


# ---------- generation and review ----------


def test_generated_criteria_map_to_approved_content(client, oracle):
    _, _, v = publish_settlement(client, oracle)
    ex = generate(client, v["id"]).json()
    assert ex["status"] == "draft" and 3 <= len(ex["criteria"]) <= 5
    content = v["approved_content"]
    for c in ex["criteria"]:
        field, idx = c["source_path"].rstrip("]").split("[")
        assert content[field][int(idx)] == c["text"]
        if c["critical"]:
            assert field in ("stop_and_escalate", "prerequisites", "success_checks")
    assert any(c["critical"] for c in ex["criteria"])


def test_only_expert_generates_edits_and_releases(client, oracle):
    _, _, v = publish_settlement(client, oracle)
    assert generate(client, v["id"], actor=SUCCESSOR).status_code == 403
    ex = generate(client, v["id"]).json()
    r = client.post(
        f"/api/exercises/{ex['id']}/approve",
        json={"expected_revision": ex["revision"], "actor_id": SUCCESSOR},
    )
    assert r.status_code == 403


def test_expert_edit_is_validated_and_revision_checked(client, oracle):
    _, _, v = publish_settlement(client, oracle)
    ex = generate(client, v["id"]).json()
    body = {
        "scenario": ex["scenario"] + " Assume it is a weekend.",
        "criteria": ex["criteria"],
        "expected_revision": ex["revision"],
        "actor_id": EXPERT,
    }
    edited = client.put(f"/api/exercises/{ex['id']}/draft", json=body)
    assert edited.status_code == 200 and edited.json()["revision"] == ex["revision"] + 1
    stale = client.put(f"/api/exercises/{ex['id']}/draft", json=body)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_revision"
    bad = [{**ex["criteria"][0], "source_path": "steps[99]"}, *ex["criteria"][1:]]
    r = client.put(
        f"/api/exercises/{ex['id']}/draft",
        json=body | {"criteria": bad, "expected_revision": edited.json()["revision"]},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_exercise"


def test_successor_cannot_see_or_answer_unreleased_exercise(client, oracle):
    _, _, v = publish_settlement(client, oracle)
    ex = generate(client, v["id"]).json()
    r = client.get(f"/api/exercises/{ex['id']}", params={"viewer_id": SUCCESSOR})
    assert r.status_code == 403
    r = submit(client, ex["id"], "anything")
    assert r.status_code == 409 and r.json()["error"]["code"] == "exercise_not_ready"


def test_exercise_from_obsolete_or_rejected_finding_conflicts(client, oracle):
    f, _, v = publish_settlement(client, oracle)
    r = client.post(
        f"/api/findings/{f['id']}/review",
        json={
            "action": "obsolete",
            "reason": "Provider replaced",
            "actor_id": EXPERT,
            "expected_revision": f["revision"],
        },
    )
    assert r.status_code == 200, r.text
    r = generate(client, v["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_exercise_from_rejected_finding_conflicts(client, oracle):
    f, _, v = publish_settlement(client, oracle)
    # The API forbids reject after publication, so force the state to test the guard itself.
    session = next(get_session())
    try:
        session.execute(text("update finding set status='rejected' where id=:i"), {"i": f["id"]})
        session.commit()
    finally:
        session.close()
    r = generate(client, v["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


# ---------- assessment ----------


def test_unsafe_answer_is_not_yet(client, ready, oracle):
    r = submit(client, ready["exercise"]["id"], oracle["successor_answers"]["unsafe"])
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["assessment_status"] == "succeeded" and a["aggregate_result"] == "not_yet"
    expert = client.get(f"/api/attempts/{a['id']}", params={"viewer_id": EXPERT}).json()
    unmet_critical = [x for x in expert["results"] if x["critical"] and x["verdict"] == "unmet"]
    assert unmet_critical


def test_correct_paraphrase_is_demonstrated(client, ready, oracle):
    answer = oracle["successor_answers"]["correct_paraphrase"]
    a = submit(client, ready["exercise"]["id"], answer).json()
    assert a["aggregate_result"] == "demonstrated"
    assert all(x["verdict"] == "met" for x in a["results"])
    assert all(x["evidence_quote"] in answer for x in a["results"])


def test_answer_without_success_check_is_partial(client, ready, oracle):
    answer = oracle["successor_answers"]["correct_paraphrase"].rsplit(" I'm done", 1)[0]
    a = submit(client, ready["exercise"]["id"], answer).json()
    assert a["aggregate_result"] == "partial"


def test_retry_creates_new_attempt_and_old_stays_immutable(client, ready, oracle):
    ex_id = ready["exercise"]["id"]
    first = submit(client, ex_id, oracle["successor_answers"]["unsafe"]).json()
    second = submit(client, ex_id, oracle["successor_answers"]["correct_paraphrase"]).json()
    assert first["id"] != second["id"]
    again = client.get(f"/api/attempts/{first['id']}", params={"viewer_id": SUCCESSOR}).json()
    assert again["answer"] == oracle["successor_answers"]["unsafe"]
    assert again["aggregate_result"] == "not_yet"
    session = next(get_session())
    try:
        with pytest.raises(Exception, match="immutable"):
            session.execute(
                text("update attempt set answer='edited' where id=:i"), {"i": first["id"]}
            )
        session.rollback()
        with pytest.raises(Exception, match="immutable"):
            session.execute(
                text("update attempt set aggregate_result='demonstrated' where id=:i"),
                {"i": first["id"]},
            )
        session.rollback()
    finally:
        session.close()


def test_attempt_idempotency(client, ready, oracle):
    ex_id = ready["exercise"]["id"]
    answer = oracle["successor_answers"]["unsafe"]
    a = submit(client, ex_id, answer, key="att-1").json()
    b = submit(client, ex_id, answer, key="att-1").json()
    assert a["id"] == b["id"]
    r = submit(client, ex_id, "a different answer", key="att-1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reused"
    r = client.post(
        f"/api/exercises/{ex_id}/attempts", json={"actor_id": SUCCESSOR, "answer": answer}
    )
    assert r.status_code == 422


def test_only_successor_submits(client, ready, oracle):
    r = submit(client, ready["exercise"]["id"], "answer", actor=EXPERT)
    assert r.status_code == 403


def test_new_version_keeps_old_attempts_on_old_version(client, ready, oracle):
    a = submit(client, ready["exercise"]["id"], oracle["successor_answers"]["unsafe"]).json()
    f, d = ready["finding"], ready["draft"]
    d2 = client.put(
        f"/api/findings/{f['id']}/draft",
        json={
            "content": oracle["expert_capture"]["content"] | {"limitations": ["Only for AcmePay"]},
            "expected_revision": d["revision"],
            "author_id": EXPERT,
        },
    ).json()
    v2 = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": d2["revision"],
            "approver_id": EXPERT,
        },
    ).json()
    assert v2["version_no"] == 2
    old = client.get(f"/api/attempts/{a['id']}", params={"viewer_id": SUCCESSOR}).json()
    assert old["knowledge_version_id"] == ready["version"]["id"]
    assert old["knowledge_version_no"] == 1
    # The superseded version no longer grounds new exercises; the new one does.
    assert generate(client, ready["version"]["id"]).status_code == 409
    assert generate(client, v2["id"]).status_code == 201


# ---------- rubric privacy ----------


def test_successor_never_sees_rubric_before_assessment(client, ready, oracle):
    ex = ready["exercise"]
    criteria_text = [c["text"] for c in ex["criteria"]]

    def assert_private(payload: str):
        for word in ("rubric", "critical", "source_path", "criteria"):
            assert word not in payload, word
        for t in criteria_text:
            assert t not in payload

    view = client.get(f"/api/exercises/{ex['id']}", params={"viewer_id": SUCCESSOR})
    assert view.status_code == 200 and view.json()["scenario"]
    assert_private(view.text)
    listing = client.get(
        f"/api/knowledge/{ready['version']['id']}/exercises", params={"viewer_id": SUCCESSOR}
    )
    assert_private(listing.text)

    # A failed assessment is "before assessment" too: still nothing about the rubric.
    def boom(*_):
        raise AppError(502, "provider_error", "down")

    original = V.get_assessor
    V.get_assessor = lambda: type("Broken", (), {"model_id": "broken", "assess": boom})()
    try:
        r = submit(client, ex["id"], oracle["successor_answers"]["unsafe"])
    finally:
        V.get_assessor = original
    attempt_id = r.json()["error"]["attempt_id"]
    pending = client.get(f"/api/attempts/{attempt_id}", params={"viewer_id": SUCCESSOR})
    assert_private(pending.text)

    # After assessment only per-criterion results are returned; no critical flags.
    done = submit(client, ex["id"], oracle["successor_answers"]["unsafe"])
    assert "critical" not in done.text and "rubric" not in done.text
    assert {x["criterion_id"] for x in done.json()["results"]} == {c["id"] for c in ex["criteria"]}


def test_outsider_sees_nothing(client, ready):
    r = client.get(f"/api/exercises/{ready['exercise']['id']}", params={"viewer_id": "carol"})
    assert r.status_code == 403


# ---------- provider failure ----------


class _FailingAssessor:
    model_id = "failing/1"

    def __init__(self, status=502, code="provider_error"):
        self.status, self.code = status, code

    def assess(self, *_):
        raise AppError(self.status, self.code, "provider unavailable")


def test_provider_error_is_502_and_never_not_yet(client, ready, oracle, monkeypatch):
    monkeypatch.setattr(V, "get_assessor", lambda: _FailingAssessor())
    r = submit(client, ready["exercise"]["id"], oracle["successor_answers"]["unsafe"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"
    attempt_id = r.json()["error"]["attempt_id"]
    a = client.get(f"/api/attempts/{attempt_id}", params={"viewer_id": SUCCESSOR}).json()
    assert a["answer"] == oracle["successor_answers"]["unsafe"]  # stored before assessment
    assert a["assessment_status"] == "failed" and a["aggregate_result"] is None
    assert a["results"] is None
    op = client.get(f"/api/operations/{r.json()['error']['operation_id']}").json()
    assert op["state"] == "failed" and op["error_code"] == "provider_error"

    monkeypatch.setattr(V, "get_assessor", lambda: OfflineAssessor())
    re = client.post(f"/api/attempts/{attempt_id}/reassess", json={"actor_id": SUCCESSOR})
    assert re.status_code == 200, re.text
    assert re.json()["assessment_status"] == "succeeded"
    assert re.json()["aggregate_result"] == "not_yet"
    again = client.post(f"/api/attempts/{attempt_id}/reassess", json={"actor_id": SUCCESSOR})
    assert again.status_code == 409


def test_provider_timeout_is_504(client, ready, oracle, monkeypatch):
    monkeypatch.setattr(V, "get_assessor", lambda: _FailingAssessor(504, "provider_timeout"))
    r = submit(client, ready["exercise"]["id"], oracle["successor_answers"]["correct_paraphrase"])
    assert r.status_code == 504 and r.json()["error"]["code"] == "provider_timeout"


def test_database_forbids_a_result_on_a_failed_attempt(client, ready, oracle, monkeypatch):
    monkeypatch.setattr(V, "get_assessor", lambda: _FailingAssessor())
    attempt_id = submit(client, ready["exercise"]["id"], "x y z").json()["error"]["attempt_id"]
    session = next(get_session())
    try:
        with pytest.raises(Exception, match="ck_attempt_result_only_when_succeeded"):
            session.execute(
                text("update attempt set aggregate_result='not_yet' where id=:i"),
                {"i": attempt_id},
            )
        session.rollback()
    finally:
        session.close()


# ---------- pure rules ----------


def _crit(i, critical):
    return Criterion(id=f"C{i}", text=f"criterion {i}", critical=critical, source_path="steps[0]")


CRITERIA = [_crit(1, True), _crit(2, True), _crit(3, False)]


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        (("met", "met", "met"), "demonstrated"),
        (("met", "met", "partial"), "partial"),
        (("met", "met", "unmet"), "partial"),
        (("unmet", "met", "met"), "not_yet"),
        (("unmet", "uncertain", "met"), "not_yet"),
        (("met", "met", "uncertain"), "review_required"),
        (("partial", "met", "met"), "review_required"),
    ],
)
def test_aggregate_table(verdicts, expected):
    matches = [
        CriterionMatch(criterion_id=c.id, verdict=v)
        for c, v in zip(CRITERIA, verdicts, strict=True)
    ]
    assert aggregate(CRITERIA, matches) == expected


def test_aggregate_with_missing_match_requires_review():
    assert aggregate(CRITERIA, [CriterionMatch(criterion_id="C1", verdict="met")]) == (
        "review_required"
    )


def test_unsupported_quote_becomes_uncertain():
    proposal = Assessment(
        matches=[
            CriterionMatch(criterion_id=c.id, verdict="met", evidence_quote="never written")
            for c in CRITERIA
        ]
    )
    matches, notes = validate_matches(CRITERIA, proposal, "my real answer")
    assert {m.verdict for m in matches} == {"uncertain"} and len(notes) == 3
    assert aggregate(CRITERIA, matches) == "review_required"


def test_exercise_validation_rules(oracle):
    content = oracle["expert_capture"]["content"]

    def draft(*crits):
        return ExerciseDraft(scenario="A realistic on-call scenario text.", criteria=list(crits))

    ok = [
        Criterion(id="C1", text="first", critical=True, source_path="stop_and_escalate[0]"),
        Criterion(id="C2", text="second", source_path="steps[0]"),
        Criterion(id="C3", text="third", source_path="success_checks[0]"),
    ]
    assert validate_exercise(draft(*ok), content) == []
    assert validate_exercise(draft(*ok[:2]), content)  # too few
    bad_crit = Criterion(id="C2", text="second", critical=True, source_path="steps[0]")
    assert any("critical" in p for p in validate_exercise(draft(ok[0], bad_crit, ok[2]), content))
    no_crit = [c.model_copy(update={"critical": False}) for c in ok]
    assert validate_exercise(draft(*no_crit), content)
    unknown = Criterion(id="C3", text="third", source_path="unresolved[0]")
    assert validate_exercise(draft(ok[0], ok[1], unknown), content)
