"""Offline checks of scripts/fetch_gitlab_bundle.py helpers: exclusion, pseudonymization and
the attribution summary. No network: the script's HTTP functions are never called."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_gitlab_bundle.py"
spec = importlib.util.spec_from_file_location("fetch_gitlab_bundle", SCRIPT)
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)

PROD = "gitlab-com/gl-infra/production"


def _user(name, **extra):
    return {
        "id": len(name),
        "username": name,
        "name": name.title(),
        "web_url": f"https://gitlab.com/{name}",
        **extra,
    }


def _issue(iid, assignee, notes):
    return {
        "issue": {
            "iid": iid,
            "title": f"Incident {iid}",
            "description": f"cc @{assignee} and @Helper",
            "state": "closed",
            "issue_type": "incident",
            "labels": ["Service::Redis"],
            "author": _user("reporter"),
            "assignees": [_user(assignee)],
            "web_url": f"https://gitlab.com/{PROD}/-/issues/{iid}",
            "references": {"full": f"{PROD}#{iid}"},
        },
        "notes": notes,
    }


def _note(who, system=False):
    return {"id": 1, "body": "did a thing", "author": _user(who), "system": system}


def _mr(author, related=(), description=""):
    return {
        "merge_request": {
            "iid": 7,
            "title": "fix",
            "description": description,
            "source_branch": "b",
            "author": _user(author),
            "web_url": "https://gitlab.com/x/-/merge_requests/7",
            "references": {"full": "x!7"},
        },
        "notes": [],
        "related_issues": list(related),
    }


def test_attribution_follows_the_resolver_rule():
    issues = [
        _issue(1, "sre", [_note("sre")]),  # assignee wrote a note: attributable
        _issue(2, "sre", [_note("sre", system=True)]),  # system notes never count
        _issue(3, "sre", []),  # acted only through an MR linked by URL below
        _issue(4, "sre", [_note("someone-else")]),
    ]
    mrs = [_mr("sre", description=f"see https://gitlab.com/{PROD}/-/issues/3")]
    row = fg.attribution(["Redis"], issues, mrs)["Redis"]
    assert row == {"closed_incidents": 4, "with_assignee": 4, "attributable": 2}


def test_excluded_users_vanish_from_lists_and_fields():
    rec = _issue(1, "gitlab-bot", [])
    out = fg.drop_users([rec], {"gitlab-bot"})[0]
    assert out["issue"]["assignees"] == []
    assert out["issue"]["author"]["username"] == "reporter"
    assert {u["username"] for u in fg.walk_users([_user("a", bot=True)]) if u.get("bot")} == {"a"}


def test_pseudonymize_codes_users_and_mentions_but_keeps_record_links():
    rec = _issue(1, "sre", [_note("sre")])
    codes = {"reporter": "E01", "sre": "E02", "helper": "E03"}
    mention = __import__("re").compile(r"(?<![\w.-])@(reporter|sre|helper)(?![\w/-])", 2)
    out = fg.pseudonymize(rec, codes, mention)
    issue = out["issue"]
    assert issue["assignees"][0] == {"id": 2, "username": "E02", "name": "E02", "state": None}
    assert issue["description"] == "cc @E02 and @E03"
    assert issue["web_url"] == f"https://gitlab.com/{PROD}/-/issues/1"  # record link intact
    assert "web_url" not in issue["author"]  # profile link removed
    assert fg.mentioned_handles({"body": "ping @a.b, mail x@y.com, group @org/team"}) == {"a.b"}
