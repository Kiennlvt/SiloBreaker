"""Acceptance tests for Capture (report Table 3, rows 9 and 14; FR-12 to FR-16)."""

import pytest
from sqlalchemy import text

from app.db import get_session
from app.knowledge.okf import parse_okf
from tests.conftest import analyze, by_area, login_as, make_handoff


@pytest.fixture
def settlement(client):
    h = make_handoff(client)
    return by_area(analyze(client, h))["settlement"]


def review(client, f, action, reason="", actor="alice", revision=None):
    return login_as(client, actor).post(
        f"/api/findings/{f['id']}/review",
        json={
            "action": action,
            "reason": reason,
            "expected_revision": f["revision"] if revision is None else revision,
        },
    )


def capture(client, f, oracle, revision=None):
    content = oracle["expert_capture"]["content"]
    r = login_as(client, "alice").put(
        f"/api/findings/{f['id']}/draft",
        json={"content": content, "expected_revision": revision},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_full_capture_and_okf_export(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    draft = capture(client, f, oracle)
    assert client.get(f"/api/findings/{f['id']}").json()["versions"] == []  # saving != publishing
    r = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": draft["revision"],
        },
    )
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["version_no"] == 1 and v["approved_content"] == oracle["expert_capture"]["content"]

    md = client.get(f"/api/knowledge/{v['id']}/okf").text
    meta, body = parse_okf(md)
    assert meta["type"] == "Operational Playbook"
    assert meta["approved_by"] == "alice" and meta["silobreaker_version"] == 1
    assert {s["uri"] for s in meta["sources"]} >= {"silobreaker://evidence/PAY-321"}
    assert "Pause the retry worker" in body
    for leaked in ("rubric", "correct_paraphrase", "target_gap"):
        assert leaked not in md


def test_only_expert_can_review(client, settlement):
    r = review(client, settlement, "confirm", actor="bob")
    assert r.status_code == 403


def test_stale_review_revision_conflicts(client, settlement):
    assert review(client, settlement, "confirm").status_code == 200
    r = review(client, settlement, "reject", "no", revision=settlement["revision"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_revision"


def test_rejected_finding_cannot_publish(client, settlement, oracle):
    f = review(client, settlement, "reject", "Not a real gap").json()
    r = client.put(
        f"/api/findings/{f['id']}/draft",
        json={"content": oracle["expert_capture"]["content"]},
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": 1,
        },
    )
    assert r.status_code == 409


def test_reject_requires_reason(client, settlement):
    r = review(client, settlement, "reject", "")
    assert r.status_code == 422


def test_stale_draft_approval_conflicts(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    d1 = capture(client, f, oracle)
    capture(client, f, oracle, revision=d1["revision"])  # now at revision 2
    r = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": 1,
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_revision"


def test_new_version_supersedes_and_old_stays_readable(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    d1 = capture(client, f, oracle)
    body = {"expected_finding_revision": f["revision"]}
    v1 = client.post(f"/api/findings/{f['id']}/publish", json=body | {"draft_revision": 1}).json()
    dup = client.post(f"/api/findings/{f['id']}/publish", json=body | {"draft_revision": 1})
    assert dup.status_code == 409  # the same draft revision is never published twice
    d2 = capture(client, f, oracle, revision=d1["revision"])
    v2 = client.post(
        f"/api/findings/{f['id']}/publish", json=body | {"draft_revision": d2["revision"]}
    ).json()
    assert v2["version_no"] == 2 and v2["supersedes_version_id"] == v1["id"]
    assert client.get(f"/api/knowledge/{v1['id']}").json()["version_no"] == 1


def test_approved_version_is_immutable_in_database(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    capture(client, f, oracle)
    v = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": 1,
        },
    ).json()
    session = next(get_session())
    try:
        with pytest.raises(Exception, match="immutable"):
            session.execute(
                text("update knowledge_version set approved_by='mallory' where id=:i"),
                {"i": v["id"]},
            )
        session.rollback()
    finally:
        session.close()


def test_publish_idempotency(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    capture(client, f, oracle)
    body = {"expected_finding_revision": f["revision"], "draft_revision": 1}
    h = {"Idempotency-Key": "pub-1"}
    a = client.post(f"/api/findings/{f['id']}/publish", json=body, headers=h).json()
    b = client.post(f"/api/findings/{f['id']}/publish", json=body, headers=h).json()
    assert a["id"] == b["id"]


def test_structurer_uses_only_expert_words(client, settlement, oracle):
    answer = oracle["expert_capture"]["answer"]
    s = client.post(f"/api/findings/{settlement['id']}/structure", json={"answer": answer}).json()
    placed = s["prerequisites"] + s["steps"] + s["stop_and_escalate"] + s["success_checks"]
    assert all(sentence in answer for sentence in placed)
    assert s["stop_and_escalate"] and s["success_checks"]


# ---------- Phase 1: lifecycle and integrity regressions ----------


def publish_rev(client, f, draft_revision):
    r = login_as(client, "alice").post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": draft_revision,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def okf_meta(client, version_id):
    return parse_okf(client.get(f"/api/knowledge/{version_id}/okf").text)[0]


def test_okf_lifecycle_superseded_after_new_version(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    d1 = capture(client, f, oracle)
    v1 = publish_rev(client, f, d1["revision"])
    assert okf_meta(client, v1["id"])["lifecycle"]["status"] == "active"
    d2 = capture(client, f, oracle, revision=d1["revision"])
    v2 = publish_rev(client, f, d2["revision"])
    old, new = okf_meta(client, v1["id"]), okf_meta(client, v2["id"])
    assert old["lifecycle"]["status"] == "superseded"
    assert old["lifecycle"]["superseded_by"] == v2["id"]
    assert new["lifecycle"]["status"] == "active"
    assert new["lifecycle"]["supersedes"] == v1["id"]


def test_reject_after_publish_is_invalid_transition(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    publish_rev(client, f, capture(client, f, oracle)["revision"])
    r = review(client, f, "reject", "Changed my mind")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"
    assert "obsolete" in r.json()["error"]["detail"]


def test_obsolete_after_publish_retires_every_version(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    d1 = capture(client, f, oracle)
    v1 = publish_rev(client, f, d1["revision"])
    v2 = publish_rev(client, f, capture(client, f, oracle, revision=d1["revision"])["revision"])
    r = review(client, f, "obsolete", "Provider replaced by a new settlement API")
    assert r.status_code == 200, r.text
    for v in (v1, v2):
        assert okf_meta(client, v["id"])["lifecycle"]["status"] == "retired"
    session = next(get_session())
    try:
        actions = session.execute(
            text("select action, metadata from audit_event where target_id=:i"), {"i": f["id"]}
        ).all()
    finally:
        session.close()
    retired = [m for a, m in actions if a == "finding.obsolete"]
    assert retired and retired[0]["retired_versions"] == 2


def test_reanalysis_points_at_previously_approved_knowledge(client, oracle):
    h = make_handoff(client)
    first = by_area(analyze(client, h))["settlement"]
    f = review(client, first, "confirm").json()
    v1 = publish_rev(client, f, capture(client, f, oracle)["revision"])
    # A new analysis of the same handoff (no idempotency key: a genuinely new snapshot).
    again = by_area(analyze(client, h))["settlement"]
    assert again["id"] != first["id"]
    prior = again["prior_knowledge"]
    assert prior == {"finding_id": first["id"], "version_id": v1["id"], "version_no": 1}
    detail = client.get(f"/api/findings/{again['id']}").json()
    assert detail["prior_knowledge"]["version_id"] == v1["id"]
    assert by_area(analyze(client, h))["webhooks"]["prior_knowledge"] is None


def test_handoff_creation_is_audited(client):
    h = make_handoff(client)
    session = next(get_session())
    try:
        rows = session.execute(
            text("select action, actor_id from audit_event where target_id=:i"), {"i": h["id"]}
        ).all()
    finally:
        session.close()
    assert [r[0] for r in rows] == ["handoff.created"]


def test_scoring_version_has_one_source_of_truth(client):
    from app.config import Settings
    from app.scoring.rules import SCORING_VERSION

    assert "scoring_version" not in Settings.model_fields
    a = analyze(client, make_handoff(client))
    assert a["scoring_version"] == SCORING_VERSION
