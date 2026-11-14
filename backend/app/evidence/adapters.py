"""Fixture-backed adapters that read provider-shaped JSON.

A live read-only HTTP client can replace `load` without changing `normalize`, because
both paths emit the same EvidenceItemInput.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from app.evidence.contract import EvidenceItemInput, Identities

BODY_LIMIT = 4000


def _bounded(text: str) -> str:
    text = text.strip()
    return text if len(text) <= BODY_LIMIT else text[:BODY_LIMIT] + "\n[truncated]"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # Jira uses +0000 without a colon; Python wants +00:00.
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
    return datetime.fromisoformat(value)


def adf_to_text(node: Any) -> str:
    """Flatten the supported subset of Atlassian Document Format to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    children = [adf_to_text(c) for c in node.get("content", [])]
    if kind in ("doc", "bulletList", "orderedList"):
        return "\n".join(c for c in children if c)
    if kind == "listItem":
        return "- " + " ".join(children)
    if kind == "hardBreak":
        return "\n"
    return "".join(children)


class _FileAdapter:
    source = ""

    def __init__(self, root: Path, identities: Identities):
        self.root = root
        self.identities = identities

    def load(self, files: list[str]) -> list[dict[str, Any]]:
        return [json.loads((self.root / f).read_text(encoding="utf-8")) for f in files]


class JiraAdapter(_FileAdapter):
    source = "jira"

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        f = record["fields"]
        key = record["key"]
        base_url = record["self"].split("/rest/")[0]
        url = f"{base_url}/browse/{key}"
        reporter = f.get("reporter") or {}
        assignee = f.get("assignee") or {}
        comments = (f.get("comment") or {}).get("comments", [])
        participants = {
            p
            for p in [
                self._person(reporter),
                self._person(assignee),
                *(self._person(c.get("author") or {}) for c in comments),
            ]
            if p
        }
        items = [
            EvidenceItemInput(
                source=self.source,
                source_type=f"issue:{(f.get('issuetype') or {}).get('name', 'Issue').lower()}",
                external_id=key,
                author=self.identities.resolve(
                    "jira", reporter.get("accountId"), reporter.get("displayName")
                ),
                participants=sorted(participants),
                timestamp=_parse_time(f.get("created")),
                title=f.get("summary"),
                body=_bounded(adf_to_text(f.get("description"))),
                url=url,
                metadata={
                    "status": (f.get("status") or {}).get("name"),
                    "issue_type": (f.get("issuetype") or {}).get("name"),
                    "components": [c["name"] for c in f.get("components", [])],
                    "labels": f.get("labels", []),
                    "priority": (f.get("priority") or {}).get("name"),
                    "assignee": self._person(assignee),
                    "updated": f.get("updated"),
                },
            )
        ]
        for c in comments:
            author = c.get("author") or {}
            items.append(
                EvidenceItemInput(
                    source=self.source,
                    source_type="issue_comment",
                    external_id=f"{key}#comment-{c['id']}",
                    parent_external_id=key,
                    author=self.identities.resolve(
                        "jira", author.get("accountId"), author.get("displayName")
                    ),
                    participants=[p for p in [self._person(author)] if p],
                    timestamp=_parse_time(c.get("created")),
                    title=f"Comment on {key}",
                    body=_bounded(adf_to_text(c.get("body"))),
                    url=f"{url}?focusedCommentId={c['id']}",
                    metadata={},
                )
            )
        return items

    def _person(self, account: dict[str, Any]) -> str | None:
        a = self.identities.resolve("jira", account.get("accountId"), account.get("displayName"))
        return a.id if a else None


class SlackAdapter(_FileAdapter):
    source = "slack"
    # Only human messages become evidence; joins, bot posts and edits are skipped.
    ACCEPTED_SUBTYPES: ClassVar[frozenset] = frozenset({None, "thread_broadcast"})

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        channel = record["channel"]
        out = []
        for m in record["response"]["messages"]:
            if (
                m.get("type") != "message"
                or m.get("subtype") not in self.ACCEPTED_SUBTYPES
                or m.get("bot_id")
            ):
                continue
            author = self.identities.resolve("slack", m.get("user"))
            thread = m.get("thread_ts")
            out.append(
                EvidenceItemInput(
                    source=self.source,
                    source_type="message",
                    external_id=f"{channel}:{m['ts']}",
                    parent_external_id=f"{channel}:{thread}"
                    if thread and thread != m["ts"]
                    else None,
                    author=author,
                    participants=[author.id] if author else [],
                    timestamp=datetime.fromtimestamp(float(m["ts"]), tz=UTC),
                    title=f"#{record.get('channel_name', channel)}",
                    body=_bounded(m.get("text", "")),
                    url=None,
                    metadata={"channel": channel, "ts": m["ts"], "thread_ts": thread},
                )
            )
        return out


class GitHubAdapter(_FileAdapter):
    source = "github"

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        login = (record.get("user") or {}).get("login")
        author = self.identities.resolve("github", login)
        participants = [author.id] if author else []
        if "pull_request_url" in record:  # a pull request review
            pr_no = record["pull_request_url"].rstrip("/").split("/")[-1]
            return [
                EvidenceItemInput(
                    source=self.source,
                    source_type="pull_request_review",
                    external_id=str(record["id"]),
                    parent_external_id=f"pr:{pr_no}",
                    author=author,
                    participants=participants,
                    timestamp=_parse_time(record.get("submitted_at")),
                    title=f"Review on PR #{pr_no}",
                    body=_bounded(record.get("body") or ""),
                    url=record.get("html_url"),
                    metadata={
                        "state": record.get("state"),
                        "commit_id": record.get("commit_id"),
                        "author_association": record.get("author_association"),
                    },
                )
            ]
        return [
            EvidenceItemInput(
                source=self.source,
                source_type="pull_request",
                external_id=f"pr:{record['number']}",
                author=author,
                participants=participants,
                timestamp=_parse_time(record.get("created_at")),
                title=record.get("title"),
                body=_bounded(record.get("body") or ""),
                url=record.get("html_url"),
                metadata={
                    "state": record.get("state"),
                    "merged_at": record.get("merged_at"),
                    "head_ref": (record.get("head") or {}).get("ref"),
                    "base_ref": (record.get("base") or {}).get("ref"),
                },
            )
        ]


class DocumentAdapter(_FileAdapter):
    source = "document"

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        return [
            EvidenceItemInput(
                source=self.source,
                source_type="runbook",
                external_id=record["path"],
                timestamp=_parse_time(record.get("updated_at")),
                title=record.get("title"),
                body=_bounded(record["body"]),
                url=record.get("url"),  # optional: a link back to a public original
                metadata={"path": record["path"]},
            )
        ]


class _GitLabAdapter(_FileAdapter):
    """GitLab REST v4 records, stored as `{"<object>": <API object>, "notes": [<API notes>]}`.

    Both parts are verbatim API responses (see scripts/fetch_gitlab_bundle.py). Identities use
    the provider key "gitlab" for issues and merge requests alike: one GitLab account.
    """

    def _author(self, user: dict[str, Any] | None):
        user = user or {}
        return self.identities.resolve("gitlab", user.get("username"), user.get("name"))

    def _notes(
        self, notes: list[dict[str, Any]], parent: str, url: str, kind: str
    ) -> list[EvidenceItemInput]:
        out = []
        for n in notes:
            if n.get("system"):  # "changed the label", "mentioned in": not human evidence
                continue
            author = self._author(n.get("author"))
            out.append(
                EvidenceItemInput(
                    source=self.source,
                    source_type=f"{kind}_note",
                    external_id=f"{parent}#note_{n['id']}",
                    parent_external_id=parent,
                    author=author,
                    participants=[author.id] if author else [],
                    timestamp=_parse_time(n.get("created_at")),
                    title=f"Note on {parent}",
                    body=_bounded(n.get("body") or ""),
                    url=f"{url}#note_{n['id']}" if url else None,
                    metadata={},
                )
            )
        return out


class GitLabIssueAdapter(_GitLabAdapter):
    """GitLab issues and incidents: the issue-tracker role Jira plays in other bundles."""

    source = "gitlab_issue"

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        issue = record["issue"]
        ref = issue["references"]["full"]
        url = issue.get("web_url") or ""
        author = self._author(issue.get("author"))
        assignees = [self._author(a) for a in issue.get("assignees") or []]
        assignees = [a for a in assignees if a]
        notes = self._notes(record.get("notes", []), ref, url, "issue")
        participants = {p.id for p in [author, *assignees] if p} | {
            n.author.id for n in notes if n.author
        }
        labels = issue.get("labels", [])
        state = issue.get("state")
        return [
            EvidenceItemInput(
                source=self.source,
                source_type=f"issue:{(issue.get('issue_type') or 'issue').lower()}",
                external_id=ref,
                author=author,
                participants=sorted(participants),
                timestamp=_parse_time(issue.get("created_at")),
                title=issue.get("title"),
                body=_bounded(issue.get("description") or ""),
                url=url or None,
                metadata={
                    # GitLab has no "status" field; state opened/closed is the closest one.
                    "status": state,
                    "issue_type": issue.get("issue_type"),
                    # GitLab's scoped "Service::<name>" labels play the role of Jira components.
                    "components": [
                        lb.split("::", 1)[1] for lb in labels if lb.lower().startswith("service::")
                    ],
                    "labels": labels,
                    "assignee": assignees[0].id if assignees else None,
                    "closed_at": issue.get("closed_at"),
                    "updated": issue.get("updated_at"),
                    # Other ways a record can name this issue, all provider-given.
                    "aliases": [a for a in [url] if a],
                },
            ),
            *notes,
        ]


class GitLabMergeRequestAdapter(_GitLabAdapter):
    """GitLab merge requests: the code-review role GitHub pull requests play elsewhere."""

    source = "gitlab_mr"

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]:
        mr = record["merge_request"]
        ref = mr["references"]["full"]
        url = mr.get("web_url") or ""
        author = self._author(mr.get("author"))
        return [
            EvidenceItemInput(
                source=self.source,
                source_type="merge_request",
                external_id=ref,
                author=author,
                participants=[author.id] if author else [],
                timestamp=_parse_time(mr.get("created_at")),
                title=mr.get("title"),
                body=_bounded(mr.get("description") or ""),
                url=url or None,
                metadata={
                    "state": mr.get("state"),
                    "merged_at": mr.get("merged_at"),
                    "head_ref": mr.get("source_branch"),
                    "base_ref": mr.get("target_branch"),
                    # Issues GitLab itself reports as related to this MR
                    # (GET /projects/:id/issues/:iid/related_merge_requests), not inferred.
                    "related_issues": sorted(record.get("related_issues", [])),
                },
            ),
            *self._notes(record.get("notes", []), ref, url, "merge_request"),
        ]


ADAPTERS = {
    a.source: a
    for a in (
        JiraAdapter,
        SlackAdapter,
        GitHubAdapter,
        DocumentAdapter,
        GitLabIssueAdapter,
        GitLabMergeRequestAdapter,
    )
}
# Always listed in a bundle's inventory, as "unavailable" when absent. Other families are listed
# only when the manifest declares them or supplies files, so a Jira/Slack bundle stays unchanged.
CORE_FAMILIES = ("jira", "slack", "github", "document")
