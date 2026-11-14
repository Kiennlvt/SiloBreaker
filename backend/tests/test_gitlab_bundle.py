"""GitLab issue/MR adapters and offline detection on a GitLab-shaped bundle.

The payloads below are small, made-up records in the GitLab REST v4 shape that
scripts/fetch_gitlab_bundle.py writes. Real public data is fetched by that script, never
committed by tests.
"""

import json

import pytest

from app.analysis.service import run_analysis
from app.db import get_session
from app.evidence.importer import import_bundle, load_bundle
from app.models import Finding, Handoff

PROD = "gitlab-com/gl-infra/production"
WEB = f"https://gitlab.com/{PROD}/-/issues"


def _user(name: str) -> dict:
    return {"id": hash(name) % 1000, "username": name, "name": name.replace("-", " ").title()}


def _note(nid: int, who: str, body: str, at: str, system: bool = False) -> dict:
    return {"id": nid, "body": body, "author": _user(who), "created_at": at, "system": system}


def _incident(iid: int, title: str, assignee: str, notes: list[dict]) -> dict:
    return {
        "issue": {
            "id": 90000 + iid,
            "iid": iid,
            "project_id": 7444821,
            "title": title,
            "description": f"Incident {iid}: {title}.",
            "state": "closed",
            "issue_type": "incident",
            "created_at": f"2025-0{iid % 9 + 1}-01T10:00:00.000Z",
            "updated_at": f"2025-0{iid % 9 + 1}-01T12:00:00.000Z",
            "closed_at": f"2025-0{iid % 9 + 1}-01T12:00:00.000Z",
            "labels": ["incident", "Service::Patroni", "severity::2"],
            "author": _user("oncall-reporter"),
            "assignees": [_user(assignee)],
            "web_url": f"{WEB}/{iid}",
            "references": {"short": f"#{iid}", "relative": f"#{iid}", "full": f"{PROD}#{iid}"},
            "confidential": False,
        },
        "notes": notes,
    }


@pytest.fixture
def gitlab_bundle(tmp_path):
    root = tmp_path / "gitlab"
    t = "2025-01-01T11:00:00.000Z"
    records = {
        "gitlab_issue/101.json": _incident(
            101,
            "Patroni primary failover stalled",
            "pg-expert",
            [
                _note(1, "pg-expert", "Promoted the replica manually; leader key was stale.", t),
                _note(2, "gitlab-bot", "added ~severity::2 label", t, system=True),
            ],
        ),
        "gitlab_issue/102.json": _incident(
            102,
            "Replication lag on patroni-main",
            "pg-expert",
            [_note(3, "pg-expert", "Paused the reindex job by hand, lag recovered.", t)],
        ),
        "gitlab_issue/103.json": _incident(
            103,
            "Patroni cluster lost quorum",
            "pg-expert",
            [_note(4, "pg-expert", "Restarted consul agents, then patroni.", t)],
        ),
        "gitlab_mr/runbooks-1.json": {
            "merge_request": {
                "id": 5001,
                "iid": 1,
                "project_id": 1,
                "title": "Document leader key cleanup",
                "description": "Follow-up for the stalled failover.",
                "state": "merged",
                "created_at": "2025-02-03T09:00:00.000Z",
                "merged_at": "2025-02-04T09:00:00.000Z",
                "source_branch": "leader-key",
                "target_branch": "master",
                "author": _user("pg-expert"),
                "web_url": "https://gitlab.com/gitlab-com/runbooks/-/merge_requests/1",
                "references": {"full": "gitlab-com/runbooks!1"},
            },
            "notes": [_note(9, "reviewer-one", "LGTM", t)],
            "related_issues": [f"{PROD}#101"],
        },
        "gitlab_mr/runbooks-2.json": {
            "merge_request": {
                "id": 5002,
                "iid": 2,
                "project_id": 1,
                "title": "Throttle reindex",
                "description": f"Prevents the lag seen in {WEB}/102.",
                "state": "merged",
                "created_at": "2025-03-03T09:00:00.000Z",
                "source_branch": "throttle",
                "target_branch": "master",
                "author": _user("pg-expert"),
                "web_url": "https://gitlab.com/gitlab-com/runbooks/-/merge_requests/2",
                "references": {"full": "gitlab-com/runbooks!2"},
            },
            "notes": [],
        },
        "docs/patroni-failover.json": {
            "path": "runbooks/docs/patroni/failover.md",
            "title": "Patroni failover",
            "updated_at": "2023-05-01T00:00:00Z",
            "url": "https://gitlab.com/gitlab-com/runbooks/-/blob/master/docs/patroni/failover.md",
            "body": "# Patroni failover\n\n## Steps\n1. Run patronictl failover.\n",
        },
    }
    files: dict[str, list[str]] = {}
    for rel, data in records.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(data), encoding="utf-8")
        family = {"gitlab_issue": "gitlab_issue", "gitlab_mr": "gitlab_mr", "docs": "document"}
        files.setdefault(family[rel.split("/")[0]], []).append(rel)
    people = ["oncall-reporter", "pg-expert", "reviewer-one"]
    manifest = {
        "schema_version": "evidence-bundle/1",
        "project_key": "gitlab-com-production",
        "source_inventory": {
            "gitlab_issue": "incomplete",
            "gitlab_mr": "incomplete",
            "document": "included",
            "slack": "unavailable",
        },
        "identities": {
            p: {"display_name": p.replace("-", " ").title(), "gitlab": p} for p in people
        },
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_adapters_keep_provider_data_and_skip_system_notes(gitlab_bundle):
    _, inventory, items = load_bundle(gitlab_bundle)
    assert inventory == {
        "jira": "unavailable",
        "slack": "unavailable",
        "github": "unavailable",
        "document": "included",
        "gitlab_issue": "incomplete",
        "gitlab_mr": "incomplete",
    }
    by_id = {(i.source, i.external_id): i for i in items}
    incident = by_id[("gitlab_issue", f"{PROD}#101")]
    assert incident.source_type == "issue:incident"
    assert incident.metadata["components"] == ["Patroni"]
    assert incident.metadata["status"] == "closed"
    assert incident.metadata["assignee"] == "pg-expert"
    assert incident.url == f"{WEB}/101"
    notes = [i for i in items if i.parent_external_id == f"{PROD}#101"]
    assert [n.external_id for n in notes] == [f"{PROD}#101#note_1"]  # system note dropped
    assert notes[0].url == f"{WEB}/101#note_1"
    mr = by_id[("gitlab_mr", "gitlab-com/runbooks!1")]
    assert mr.metadata["related_issues"] == [f"{PROD}#101"]
    doc = by_id[("document", "runbooks/docs/patroni/failover.md")]
    assert doc.url and doc.url.startswith("https://gitlab.com/")


@pytest.fixture
def session(client):  # `client` resets the database first
    s = next(get_session())
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_offline_detection_finds_the_service_area(session, gitlab_bundle):
    bundle = import_bundle(session, gitlab_bundle)
    h = Handoff(
        project_key=bundle.project_key,
        bundle_id=bundle.id,
        expert_id="pg-expert",
        successor_id="reviewer-one",
    )
    session.add(h)
    session.flush()
    analysis = run_analysis(session, h, "pg-expert")
    findings = {f.area_key: f for f in session.query(Finding).filter_by(analysis_id=analysis.id)}
    patroni = findings["Patroni"]
    counts = patroni.signal_values["counts"]
    assert counts["distinct_events"] == 3
    assert counts["events_by_selected"] == 3 and counts["events_by_others"] == 0
    assert counts["manual_events"] == 2  # "manually" and "by hand"
    assert counts["relevant_documents"] == 1
    # 3 incidents + 3 human notes + 2 MRs (one joined through GitLab's related list, one
    # through the incident URL in its description) + 1 MR note + 1 runbook.
    assert counts["linked_records"] == 10
    assert patroni.signal_values["signals"]["D"] == 0.5  # runbook has steps, misses the rest
    assert patroni.review_priority is not None and patroni.eligibility_status == "ranked"
