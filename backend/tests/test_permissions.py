"""Server-side authorization: who may call what, and the actor always comes from the session."""

import uuid

import pytest

from app.scoring.rules import CAP, WEIGHTS
from tests.conftest import analyze, by_area, create_member, login_as, make_handoff

# ---------- helpers ----------


def confirmed_settlement(client, oracle, expert="alice", successor="bob"):
    """Handoff -> analysis -> confirm -> draft -> publish, all by the expert."""
    h = make_handoff(client, expert, successor)
    f = by_area(analyze(client, h))["settlement"]
    f = (
        login_as(client, expert)
        .post(
            f"/api/findings/{f['id']}/review",
            json={"action": "confirm", "expected_revision": f["revision"]},
        )
        .json()
    )
    d = client.put(
        f"/api/findings/{f['id']}/draft", json={"content": oracle["expert_capture"]["content"]}
    ).json()
    v = client.post(
        f"/api/findings/{f['id']}/publish",
        json={"expected_finding_revision": f["revision"], "draft_revision": d["revision"]},
    ).json()
    return h, f, d, v


def released_exercise(client, oracle, expert="alice", successor="bob"):
    h, _, _, v = confirmed_settlement(client, oracle, expert, successor)
    ex = login_as(client, expert).post(f"/api/knowledge/{v['id']}/exercises").json()
    ex = client.post(
        f"/api/exercises/{ex['id']}/approve", json={"expected_revision": ex["revision"]}
    ).json()
    return h, v, ex


def submit(client, ex_id, answer, as_user="bob", **extra):
    return login_as(client, as_user).post(
        f"/api/exercises/{ex_id}/attempts",
        json={"answer": answer, **extra},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


# ---------- authentication ----------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/bundles/{bundle}"),
        ("get", "/api/handoffs"),
        ("post", "/api/handoffs"),
        ("post", f"/api/findings/{uuid.uuid4()}/review"),
        ("get", f"/api/knowledge/{uuid.uuid4()}"),
        ("get", "/api/library"),
        ("get", f"/api/exercises/{uuid.uuid4()}"),
        ("post", f"/api/exercises/{uuid.uuid4()}/attempts"),
        ("get", "/api/me/exercises"),
        ("get", "/api/admin/users"),
        ("get", "/api/admin/audit"),
        ("post", "/api/demo/reset"),
        ("get", "/api/auth/me"),
    ],
)
def test_no_session_is_401(client, method, path):
    client.cookies.clear()
    r = getattr(client, method)(path.format(bundle=client.bundle["id"]))
    assert r.status_code == 401, (path, r.text)
    assert r.json()["error"]["code"] == "not_authenticated"


def test_health_and_login_are_public(client):
    client.cookies.clear()
    assert client.get("/api/health").status_code == 200
    r = client.post("/api/auth/login", json={"username": "bob", "password": "Bob@123"})
    assert r.status_code == 200


# ---------- admin area ----------


def test_member_cannot_use_admin_api(client):
    admin_id = login_as(client, "admin").get("/api/auth/me").json()["user"]["id"]
    login_as(client, "bob")
    calls = [
        client.get("/api/admin/users"),
        client.post(
            "/api/admin/users",
            json={"username": "eve", "role": "admin", "password": "Password1"},
        ),
        client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False}),
        client.get("/api/admin/audit"),
        client.post("/api/demo/reset"),
        client.post("/api/bundles/import"),
        client.post(
            "/api/handoffs",
            json={"bundle_id": client.bundle["id"], "expert_id": "alice", "successor_id": "bob"},
        ),
    ]
    for r in calls:
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "not_admin"


def test_user_search_and_pagination(client):
    for i in range(5):
        create_member(client, f"tester{i}", display_name=f"QA Tester {i}")
    page1 = client.get("/api/admin/users", params={"q": "tester", "size": 2, "page": 1}).json()
    page3 = client.get("/api/admin/users", params={"q": "tester", "size": 2, "page": 3}).json()
    assert page1["total"] == 5 and [u["username"] for u in page1["items"]] == [
        "tester0",
        "tester1",
    ]
    assert [u["username"] for u in page3["items"]] == ["tester4"]
    by_display = client.get("/api/admin/users", params={"q": "qa tester 3"}).json()
    assert [u["username"] for u in by_display["items"]] == ["tester3"]
    admins = client.get("/api/admin/users", params={"role": "admin"}).json()
    assert [u["username"] for u in admins["items"]] == ["admin"]
    assert all("password_hash" not in u for u in page1["items"])


def test_new_member_person_id_defaults_to_username_and_is_unique(client):
    u = create_member(client, "dana")
    assert u["person_id"] == "dana" and u["role"] == "member" and u["is_active"]
    r = client.post(
        "/api/admin/users",
        json={"username": "dana2", "role": "member", "password": "Password1", "person_id": "dana"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "person_taken"
    r = client.post(
        "/api/admin/users", json={"username": "dana", "role": "member", "password": "Password1"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "username_taken"


def test_deactivation_revokes_sessions_and_is_audited(client):
    user = create_member(client, "erin")
    login_as(client, "erin")
    assert client.get("/api/auth/me").status_code == 200
    r = login_as(client, "admin").patch(f"/api/admin/users/{user['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert login_as(client, "erin").get("/api/auth/me").status_code == 401
    audit = login_as(client, "admin").get("/api/admin/audit", params={"actor": "admin"}).json()
    actions = [e["action"] for e in audit["items"]]
    assert "user.deactivated" in actions and "user.created" in actions
    deactivated = next(e for e in audit["items"] if e["action"] == "user.deactivated")
    assert deactivated["metadata"]["sessions_revoked"] == 1


def test_admin_cannot_deactivate_self(client):
    me = login_as(client, "admin").get("/api/auth/me").json()["user"]
    r = client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert r.status_code == 422 and r.json()["error"]["code"] == "cannot_deactivate_self"


def test_audit_filters_and_pagination(client):
    make_handoff(client)
    login_as(client, "alice")  # the admin's own login predates the reset, which clears audit
    login_as(client, "bob")
    data = (
        login_as(client, "admin")
        .get("/api/admin/audit", params={"action": "auth.login", "size": 1})
        .json()
    )
    assert data["total"] >= 2 and len(data["items"]) == 1
    assert all(e["action"] == "auth.login" for e in data["items"])
    future = client.get("/api/admin/audit", params={"date_from": "2999-01-01"}).json()
    assert future["total"] == 0


# ---------- capture and verify roles ----------


def test_successor_cannot_review_and_admin_cannot_publish(client, oracle):
    h = make_handoff(client)
    f = by_area(analyze(client, h))["settlement"]
    r = login_as(client, "bob").post(
        f"/api/findings/{f['id']}/review",
        json={"action": "confirm", "expected_revision": f["revision"]},
    )
    assert r.status_code == 403
    assert login_as(client, "bob").get(f"/api/findings/{f['id']}").status_code == 403

    f = (
        login_as(client, "alice")
        .post(
            f"/api/findings/{f['id']}/review",
            json={"action": "confirm", "expected_revision": f["revision"]},
        )
        .json()
    )
    d = client.put(
        f"/api/findings/{f['id']}/draft", json={"content": oracle["expert_capture"]["content"]}
    ).json()
    body = {"expected_finding_revision": f["revision"], "draft_revision": d["revision"]}
    r = login_as(client, "admin").post(f"/api/findings/{f['id']}/publish", json=body)
    assert r.status_code == 403
    assert client.get(f"/api/findings/{f['id']}").status_code == 200  # admin may read
    r = client.put(
        f"/api/findings/{f['id']}/draft", json={"content": oracle["expert_capture"]["content"]}
    )
    assert r.status_code == 403


def test_actor_in_body_is_ignored(client, oracle):
    h = make_handoff(client)
    f = by_area(analyze(client, h))["settlement"]
    r = login_as(client, "bob").post(
        f"/api/findings/{f['id']}/review",
        json={"action": "confirm", "expected_revision": f["revision"], "actor_id": "alice"},
    )
    assert r.status_code == 403
    r = client.get(f"/api/exercises/{uuid.uuid4()}", params={"viewer_id": "alice"})
    assert r.status_code == 404  # the query parameter grants nothing; the row just isn't there

    _, _, ex = released_exercise(client, oracle)
    a = submit(client, ex["id"], oracle["successor_answers"]["unsafe"], actor_id="alice")
    assert a.status_code == 201 and a.json()["successor_id"] == "bob"


def test_admin_cannot_author_or_answer_exercises(client, oracle):
    _, v, ex = released_exercise(client, oracle)
    login_as(client, "admin")
    assert client.post(f"/api/knowledge/{v['id']}/exercises").status_code == 403
    r = client.post(f"/api/exercises/{ex['id']}/approve", json={"expected_revision": 1})
    assert r.status_code == 403
    assert submit(client, ex["id"], "anything", as_user="admin").status_code == 403
    full = client.get(f"/api/exercises/{ex['id']}").json()  # but may read everything
    assert full["viewer_role"] == "admin" and full["criteria"]


def test_successor_never_sees_rubric(client, oracle):
    h, v, ex = released_exercise(client, oracle)
    criteria = [c["text"] for c in ex["criteria"]]
    login_as(client, "bob")
    payloads = [
        client.get(f"/api/exercises/{ex['id']}"),
        client.get(f"/api/knowledge/{v['id']}/exercises"),
        client.get("/api/me/exercises"),
    ]
    for r in payloads:
        assert r.status_code == 200, r.text
        for word in ("criteria", "critical", "source_path", "rubric"):
            assert word not in r.text
        for t in criteria:
            assert t not in r.text
    mine = payloads[2].json()
    assert [e["id"] for e in mine] == [ex["id"]] and mine[0]["viewer_role"] == "successor"
    detail = client.get(f"/api/handoffs/{h['id']}").json()
    assert detail["viewer_role"] == "successor" and "analyses" not in detail


def test_everyone_signed_in_reads_library_and_okf(client, oracle):
    create_member(client, "carol")
    _, _, _, v = confirmed_settlement(client, oracle)
    for user in ("carol", "bob", "admin"):
        login_as(client, user)
        lib = client.get("/api/library").json()
        assert [x["version_id"] for x in lib] == [v["id"]]
        assert client.get(f"/api/knowledge/{v['id']}/okf").status_code == 200


def test_handoff_list_is_scoped_to_participants(client):
    create_member(client, "carol")
    h = make_handoff(client)
    assert [x["id"] for x in login_as(client, "admin").get("/api/handoffs").json()] == [h["id"]]
    assert login_as(client, "alice").get("/api/handoffs").json()[0]["viewer_role"] == "expert"
    assert login_as(client, "bob").get("/api/handoffs").json()[0]["viewer_role"] == "successor"
    assert login_as(client, "carol").get("/api/handoffs").json() == []
    assert client.get(f"/api/handoffs/{h['id']}").status_code == 403


def test_successor_cannot_run_analysis(client):
    h = make_handoff(client)
    r = login_as(client, "bob").post(f"/api/handoffs/{h['id']}/analyses", json={})
    assert r.status_code == 403
    assert (
        login_as(client, "admin").post(f"/api/handoffs/{h['id']}/analyses", json={}).status_code
        == 201
    )


# ---------- handoff creation rules ----------


def test_external_hire_can_be_successor_and_take_the_exercise(client, oracle):
    create_member(client, "newhire")
    h = make_handoff(client, "alice", "newhire")
    assert h["successor_id"] == "newhire"
    _, _, ex = released_exercise(client, oracle, successor="newhire")
    r = submit(client, ex["id"], oracle["successor_answers"]["correct_paraphrase"], "newhire")
    assert r.status_code == 201, r.text
    assert r.json()["aggregate_result"] == "demonstrated"
    assert submit(client, ex["id"], "x", "bob").status_code == 403  # bob is not in this handoff


def _create_handoff(client, expert, successor):
    return login_as(client, "admin").post(
        "/api/handoffs",
        json={"bundle_id": client.bundle["id"], "expert_id": expert, "successor_id": successor},
    )


def test_expert_must_appear_in_evidence(client):
    create_member(client, "outsider")
    r = _create_handoff(client, "outsider", "bob")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_person"


def test_inactive_successor_is_rejected(client):
    bob = next(
        u
        for u in login_as(client, "admin")
        .get("/api/admin/users", params={"q": "bob"})
        .json()["items"]
    )
    client.patch(f"/api/admin/users/{bob['id']}", json={"is_active": False})
    r = _create_handoff(client, "alice", "bob")
    assert r.status_code == 422 and r.json()["error"]["code"] == "inactive_account"


def test_handoff_participant_rules(client):
    r = _create_handoff(client, "alice", "nobody")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_person"
    r = _create_handoff(client, "alice", "alice")
    assert r.status_code == 422 and r.json()["error"]["code"] == "same_person"
    create_member(client, "boss")
    boss = client.get("/api/admin/users", params={"q": "boss"}).json()["items"][0]
    client.patch(f"/api/admin/users/{boss['id']}", json={"role": "admin"})
    r = _create_handoff(client, "alice", "boss")
    assert r.status_code == 422 and r.json()["error"]["code"] == "admin_not_participant"


# ---------- score breakdown ----------


def test_finding_carries_weights_contributions_and_cap(client):
    f = by_area(analyze(client, make_handoff(client)))["settlement"]
    assert f["weights"] == WEIGHTS and f["cap"] == CAP
    for k, w in WEIGHTS.items():
        assert f["contributions"][k] == w * f["signals"][k]
    assert sum(f["contributions"].values()) == f["raw_score"]
