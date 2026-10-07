"""Acceptance tests for Capture (report Table 3, rows 9 and 14; FR-12 to FR-16)."""

import pytest
from sqlalchemy import text

from app.db import get_session
from app.knowledge.okf import parse_okf
from tests.conftest import analyze, by_area, make_handoff


@pytest.fixture
def settlement(client):
    h = make_handoff(client)
    return by_area(analyze(client, h))["settlement"]


def review(client, f, action, reason="", actor="alice", revision=None):
    return client.post(
        f"/api/findings/{f['id']}/review",
        json={
            "action": action,
            "reason": reason,
            "actor_id": actor,
            "expected_revision": f["revision"] if revision is None else revision,
        },
    )


def capture(client, f, oracle, revision=None):
    content = oracle["expert_capture"]["content"]
    r = client.put(
        f"/api/findings/{f['id']}/draft",
        json={"content": content, "expected_revision": revision, "author_id": "alice"},
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
            "approver_id": "alice",
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
        json={"content": oracle["expert_capture"]["content"], "author_id": "alice"},
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/findings/{f['id']}/publish",
        json={
            "expected_finding_revision": f["revision"],
            "draft_revision": 1,
            "approver_id": "alice",
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
            "approver_id": "alice",
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_revision"


def test_new_version_supersedes_and_old_stays_readable(client, settlement, oracle):
    f = review(client, settlement, "confirm").json()
    d1 = capture(client, f, oracle)
    body = {"expected_finding_revision": f["revision"], "approver_id": "alice"}
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
            "approver_id": "alice",
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
    body = {"expected_finding_revision": f["revision"], "draft_revision": 1, "approver_id": "alice"}
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
