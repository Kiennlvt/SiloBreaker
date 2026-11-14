"""Fetch a sample of GitLab.com's public production incidents as a SiloBreaker evidence bundle.

Read-only, standard library only. Every record is written as the verbatim GitLab REST v4
response (wrapped with its notes), so each citation links back to a public original.

    python scripts/fetch_gitlab_bundle.py --list-services
    python scripts/fetch_gitlab_bundle.py --services Patroni Redis --per-service 8 --max-docs 6

GITLAB_TOKEN (read_api) is needed for notes: GitLab.com refuses them anonymously, so without
it notes are skipped (and SOURCES.md says so). Confidential issues are never
fetched. The adapters that read this output are in backend/app/evidence/adapters.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API = "https://gitlab.com/api/v4"
PRODUCTION = "gitlab-com/gl-infra/production"
RUNBOOKS = "gitlab-com/runbooks"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "fixtures" / "public" / "gitlab"
SUBDIRS = ("gitlab_issue", "gitlab_mr", "docs")
MAX_NOTE_PAGES = 5  # 500 notes per record is plenty for a sample


def _pid(path: str) -> str:
    return urllib.parse.quote(path, safe="")


def get(path: str, params: dict[str, Any] | None = None, raw: bool = False) -> Any:
    """GET one API resource, retrying on rate limits and transient server errors."""
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {"User-Agent": "silobreaker-fetch/1", "Accept": "application/json"}
    if token := os.environ.get("GITLAB_TOKEN"):
        headers["PRIVATE-TOKEN"] = token
    for attempt in range(5):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=30
            ) as r:
                body = r.read().decode("utf-8")
                return body if raw else json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                wait = int(exc.headers.get("Retry-After") or 2 ** (attempt + 1))
                print(f"  {exc.code} on {path}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def get_all(path: str, params: dict[str, Any], max_pages: int) -> list[Any]:
    out: list[Any] = []
    for page in range(1, max_pages + 1):
        batch = get(path, {**params, "per_page": 100, "page": page})
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


NOTES_SKIPPED = False  # set when GitLab refuses anonymous access to notes


def notes_of(project: str, kind: str, iid: int) -> list[dict]:
    """Notes of one issue/MR. GitLab.com answers 401 to anonymous notes requests."""
    global NOTES_SKIPPED
    if NOTES_SKIPPED:
        return []
    try:
        return get_all(
            f"/projects/{_pid(project)}/{kind}/{iid}/notes",
            {"sort": "asc", "order_by": "created_at"},
            MAX_NOTE_PAGES,
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 401 or os.environ.get("GITLAB_TOKEN"):
            raise
        NOTES_SKIPPED = True
        print(
            "  GitLab requires a token for notes; skipping all notes. "
            "Set GITLAB_TOKEN (read_api) to include them.",
            file=sys.stderr,
        )
        return []


def list_services(pages: int, top: int) -> None:
    issues = get_all(
        f"/projects/{_pid(PRODUCTION)}/issues",
        {"issue_type": "incident", "state": "closed", "confidential": "false"},
        pages,
    )
    counts = Counter(
        lb.split("::", 1)[1]
        for it in issues
        for lb in it.get("labels", [])
        if lb.lower().startswith("service::")
    )
    counts.pop("Needed", None)  # GitLab's placeholder for "service not set yet"
    print(f"Service labels across the {len(issues)} most recent closed incidents:")
    for name, n in counts.most_common(top):
        print(f"  {n:4d}  {name}")


def runbook_slug(service: str, overrides: dict[str, str]) -> str:
    return overrides.get(service) or re.sub(r"[^a-z0-9]+", "-", service.lower()).strip("-")


def fetch_runbooks(folder: str, limit: int, branch: str) -> tuple[list[dict], bool]:
    """Markdown files under docs/<folder>/; returns (records, cut_short)."""
    try:
        tree = get_all(
            f"/projects/{_pid(RUNBOOKS)}/repository/tree",
            {"path": f"docs/{folder}", "recursive": "true", "ref": branch},
            5,
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return [], False
        raise
    md = sorted(e["path"] for e in tree if e["type"] == "blob" and e["path"].endswith(".md"))
    records = []
    for path in md[:limit]:
        body = get(
            f"/projects/{_pid(RUNBOOKS)}/repository/files/{_pid(path)}/raw",
            {"ref": branch},
            raw=True,
        )
        commits = get(
            f"/projects/{_pid(RUNBOOKS)}/repository/commits",
            {"path": path, "ref_name": branch, "per_page": 1},
        )
        heading = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), None)
        records.append(
            {
                "path": f"runbooks/{path}",
                "title": heading or Path(path).stem,
                "updated_at": commits[0]["committed_date"] if commits else None,
                "url": f"https://gitlab.com/{RUNBOOKS}/-/blob/{branch}/{urllib.parse.quote(path)}",
                "body": body,
            }
        )
    return records, len(md) > limit


def prepare_out(out: Path, force: bool) -> None:
    """Only ever clears a folder this script wrote before (it has SOURCES.md)."""
    if out.exists() and any(out.iterdir()):
        if not (out / "SOURCES.md").exists() and not force:
            sys.exit(f"{out} is not empty and was not written by this script; use --force")
        for sub in SUBDIRS:
            if (out / sub).is_dir():
                shutil.rmtree(out / sub)
    for sub in SUBDIRS:
        (out / sub).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_user(obj: Any) -> bool:
    return isinstance(obj, dict) and "username" in obj and "id" in obj


def walk_users(obj: Any):
    """Every GitLab user object nested anywhere in an API response."""
    if is_user(obj):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_users(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_users(v)


def drop_users(obj: Any, excluded: set[str]) -> Any:
    """Excluded users vanish: removed from lists, None in single-user fields."""
    if isinstance(obj, dict):
        return {
            k: (None if is_user(v) and v["username"] in excluded else drop_users(v, excluded))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            drop_users(v, excluded) for v in obj if not (is_user(v) and v["username"] in excluded)
        ]
    return obj


TEXT_KEYS = ("title", "description", "body")
# "@handle", not an e-mail address ("a@b") and not a group path ("@org/group").
HANDLE_RX = re.compile(r"(?<![\w.-])@([A-Za-z0-9_](?:[\w.-]*[\w-])?)(?![\w/-])")


def mentioned_handles(obj: Any) -> set[str]:
    """Every @handle written in a title, description or body."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TEXT_KEYS and isinstance(v, str):
                found |= set(HANDLE_RX.findall(v))
            else:
                found |= mentioned_handles(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= mentioned_handles(v)
    return found


def pseudonymize(obj: Any, codes: dict[str, str], mention: re.Pattern | None) -> Any:
    """Usernames, names, profile links and @mentions become stable codes. Links to issues,
    merge requests, notes and runbooks (their web_url) stay intact."""
    if is_user(obj):
        code = codes[obj["username"]]
        return {
            "id": int(code[1:]),
            "username": code,
            "name": code,
            "state": obj.get("state"),
            **({"bot": obj["bot"]} if "bot" in obj else {}),
        }
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in TEXT_KEYS and isinstance(v, str) and mention:
                v = mention.sub(lambda m: "@" + codes[m.group(1).lower()], v)
            out[k] = pseudonymize(v, codes, mention)
        return out
    if isinstance(obj, list):
        return [pseudonymize(v, codes, mention) for v in obj]
    return obj


def human_notes(notes: list[dict]) -> list[dict]:
    return [n for n in notes if not n.get("system")]


def attribution(
    services: list[str], issues: list[dict], mrs: list[dict]
) -> dict[str, dict[str, int]]:
    """Per service, closed incidents whose assignee also acted in the record.

    Mirrors OfflineExtractor._linked_records and ._resolver (backend/app/analysis/offline.py)
    on the records as written: the first assignee counts only if they authored a human note
    on the incident, a linked merge request, or a human note on that MR. An MR is linked when
    GitLab lists it as related, or when its title, description or source branch names the
    incident by full reference or URL. Reporting only; scoring rules are not changed here.
    """
    summary = {}
    for service in services:
        label = f"service::{service.lower()}"
        row = {"closed_incidents": 0, "with_assignee": 0, "attributable": 0}
        for rec in issues:
            issue = rec["issue"]
            if label not in (lb.lower() for lb in issue.get("labels", [])):
                continue
            if (issue.get("issue_type") or "").lower() != "incident":
                continue
            if issue.get("state") != "closed":
                continue
            row["closed_incidents"] += 1
            assignee = next((a["username"] for a in issue.get("assignees") or []), None)
            if not assignee:
                continue
            row["with_assignee"] += 1
            ref = issue["references"]["full"]
            names = [ref, *([issue["web_url"]] if issue.get("web_url") else [])]
            pattern = re.compile("|".join(rf"(?<!\w){re.escape(n)}(?!\w)" for n in names))
            authors = {(n.get("author") or {}).get("username") for n in human_notes(rec["notes"])}
            for m in mrs:
                mr = m["merge_request"]
                hay = " ".join(
                    [
                        (mr.get("description") or "")[:4000],
                        mr.get("title") or "",
                        mr.get("source_branch") or "",
                    ]
                )
                if ref in m["related_issues"] or pattern.search(hay):
                    authors.add((mr.get("author") or {}).get("username"))
                    authors |= {
                        (n.get("author") or {}).get("username") for n in human_notes(m["notes"])
                    }
            if assignee in authors:
                row["attributable"] += 1
        summary[service] = row
    return summary


def fetch_bundle(args: argparse.Namespace) -> None:
    overrides = dict(pair.split("=", 1) for pair in args.runbook_dir)
    out: Path = args.out
    prepare_out(out, args.force)
    branch = get(f"/projects/{_pid(RUNBOOKS)}")["default_branch"]

    issues: list[dict] = []  # {"issue", "notes"}
    seen_iids: set[int] = set()
    mrs: dict[str, dict] = {}  # references.full -> {"merge_request", "notes", "related_issues"}
    docs: list[dict] = []
    docs_cut = False

    # 1. Fetch everything into memory.
    for service in args.services:
        print(f"Service::{service}")
        batch = get(
            f"/projects/{_pid(PRODUCTION)}/issues",
            {
                "issue_type": "incident",
                "state": "closed",
                "confidential": "false",
                "labels": f"Service::{service}",
                "order_by": "created_at",
                "per_page": args.per_service,
            },
        )
        for issue in batch:
            if issue.get("confidential") or issue["iid"] in seen_iids:
                continue  # confidential, or the same incident under two service labels
            seen_iids.add(issue["iid"])
            ref = issue["references"]["full"]
            notes = notes_of(PRODUCTION, "issues", issue["iid"])
            issues.append({"issue": issue, "notes": notes})
            print(f"  {ref}: {len(notes)} notes")
            related = get(
                f"/projects/{_pid(PRODUCTION)}/issues/{issue['iid']}/related_merge_requests"
            )
            for mr in related:
                rec = mrs.setdefault(
                    mr["references"]["full"],
                    {"merge_request": mr, "notes": [], "related_issues": set()},
                )
                rec["related_issues"].add(ref)
        folder = runbook_slug(service, overrides)
        got, cut = fetch_runbooks(folder, args.max_docs, branch)
        docs_cut |= cut
        docs.extend(d for d in got if d["path"] not in {x["path"] for x in docs})
        print(f"  runbooks docs/{folder}/: {len(got)}{' (cut short)' if cut else ''}")

    mr_list = []
    for _mref, rec in sorted(mrs.items()):
        mr = rec["merge_request"]
        try:
            rec["notes"] = notes_of(str(mr["project_id"]), "merge_requests", mr["iid"])
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404):
                raise
            rec["notes"] = []  # MR in a project whose notes are not public
        rec["related_issues"] = sorted(rec["related_issues"])
        mr_list.append(rec)

    # 2. Exclude named users and anything GitLab flags as a bot.
    everyone = {u["username"]: u for u in walk_users([issues, mr_list])}
    by_flag = {name for name, u in everyone.items() if u.get("bot") is True}
    by_name = set(args.exclude_users) & set(everyone)
    excluded = by_flag | by_name
    dropped_notes = 0
    for rec in [*issues, *mr_list]:
        kept = [n for n in rec["notes"] if (n.get("author") or {}).get("username") not in excluded]
        dropped_notes += len(rec["notes"]) - len(kept)
        rec["notes"] = kept
    issues = drop_users(issues, excluded)
    mr_list = drop_users(mr_list, excluded)
    botlike = sorted(n for n in set(everyone) - excluded if re.search(r"bot\b|-bot|bot$", n))

    # 3. Attribution, on the records exactly as they will be written.
    summary = attribution(args.services, issues, mr_list)

    # 4. People, then (optionally) stable codes in place of identities.
    people = {u["username"]: u.get("name") or u["username"] for u in walk_users([issues, mr_list])}
    if args.pseudonymize:
        # Participants get the first codes; handles only @mentioned in text come after them,
        # so a participant's code does not depend on who else happens to be mentioned.
        known = {u.lower() for u in people}
        mentioned = sorted(
            {h for h in mentioned_handles([issues, mr_list, docs]) if h.lower() not in known},
            key=str.lower,
        )
        mentioned = list({h.lower(): h for h in mentioned}.values())
        handles = [*sorted(people), *mentioned]
        width = max(2, len(str(len(handles))))
        codes = {u: f"E{i:0{width}d}" for i, u in enumerate(handles, 1)}
        mention = (
            re.compile(
                r"(?<![\w.-])@("
                + "|".join(re.escape(u) for u in sorted(codes, key=len, reverse=True))
                + r")(?![\w/-])",
                re.IGNORECASE,
            )
            if codes
            else None
        )
        codes |= {u.lower(): c for u, c in codes.items()}  # @mentions ignore case
        issues = pseudonymize(issues, codes, mention)
        mr_list = pseudonymize(mr_list, codes, mention)
        docs = pseudonymize(docs, codes, mention)
        people = {codes[u]: codes[u] for u in people}  # identities: participants only

    # 5. Write.
    files: dict[str, list[str]] = {"gitlab_issue": [], "gitlab_mr": [], "document": []}
    sources: list[str] = []
    for rec in issues:
        issue = rec["issue"]
        rel = f"gitlab_issue/{issue['iid']}.json"
        write_json(out / rel, rec)
        files["gitlab_issue"].append(rel)
        sources.append(f"- [{issue['references']['full']}]({issue['web_url']}) {issue['title']}")
    for rec in mr_list:
        mr = rec["merge_request"]
        mref = mr["references"]["full"]
        rel = "gitlab_mr/" + re.sub(r"[^A-Za-z0-9._-]+", "_", mref) + ".json"
        write_json(out / rel, rec)
        files["gitlab_mr"].append(rel)
        sources.append(f"- [{mref}]({mr['web_url']}) {mr['title']}")
    for doc in docs:
        rel = "docs/" + re.sub(r"[^A-Za-z0-9._-]+", "_", doc["path"].removeprefix("runbooks/docs/"))
        rel = rel.removesuffix(".md") + ".json"
        write_json(out / rel, doc)
        files["document"].append(rel)
        sources.append(f"- [{doc['path']}]({doc['url']})")

    manifest = {
        "schema_version": "evidence-bundle/1",
        "project_key": "gitlab-com-production",
        "source_inventory": {
            "jira": "unavailable",
            "slack": "unavailable",
            "github": "unavailable",
            "gitlab_issue": "incomplete",  # a sample, never the full export
            "gitlab_mr": "incomplete",
            "document": "incomplete" if docs_cut else "included",
        },
        "identities": {
            u: {"display_name": name, "gitlab": u} for u, name in sorted(people.items())
        },
        "files": {k: sorted(v) for k, v in files.items()},
    }
    write_json(out / "manifest.json", manifest)

    table = [
        "| Service | Closed incidents | With an assignee | Assignee also acted (attributable) |",
        "|---|---|---|---|",
        *(
            f"| {s} | {r['closed_incidents']} | {r['with_assignee']} | {r['attributable']} |"
            for s, r in summary.items()
        ),
    ]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    people_line = (
        "People are replaced by stable codes in user fields and @mentions: participants first,\n"
        "in order of GitLab username, then handles that are only @mentioned (these may include\n"
        "group handles). The same sample always gets the same codes. Links to issues, MRs and\n"
        "runbooks are kept, so anyone who opens one sees the real names there; names written as\n"
        "plain prose, and usernames inside branch names, are not rewritten.\n"
        if args.pseudonymize
        else "People are named as they appear in GitLab's public records.\n"
    )
    (out / "SOURCES.md").write_text(
        "# Sources\n\n"
        f"Fetched {now} from the public GitLab REST API ({API}), read-only.\n"
        f"Services: {', '.join(args.services)}; up to {args.per_service} closed incidents each "
        f"from `{PRODUCTION}`, related merge requests, and up to {args.max_docs} runbooks per "
        f"service from `{RUNBOOKS}` ({branch}). Confidential issues are never fetched.\n"
        + (
            "\n**Notes were not fetched** (no GITLAB_TOKEN): comments on incidents and merge\n"
            "requests are missing, so who acted on each incident is under-counted.\n"
            if NOTES_SKIPPED
            else ""
        )
        + f"\nExcluded users: {len(excluded)} ({len(by_name)} named with --exclude-users, "
        f"{len(by_flag)} flagged `bot: true` by GitLab); {dropped_notes} of their notes dropped.\n"
        + "\n"
        + people_line
        + "Results describe where knowledge is concentrated in this sample, not a judgement of\n"
        "anyone.\n\n"
        "## Attribution\n\n"
        "Closed incidents whose first assignee also authored a note, linked MR or MR note (the\n"
        "rule in `OfflineExtractor._resolver`). Only attributable incidents count toward a\n"
        "person's events.\n\n"
        + "\n".join(table)
        + "\n\n## Records\n\n"
        + "\n".join(sources)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(files['gitlab_issue'])} incidents, {len(files['gitlab_mr'])} MRs, "
        f"{len(files['document'])} runbooks, {len(people)} people to {out}"
    )
    print(f"Excluded {len(excluded)} users ({len(by_name)} by name, {len(by_flag)} bot flag)")
    if botlike:
        print(f"Bot-like usernames kept (pass --exclude-users to drop): {', '.join(botlike)}")
    print("Attribution (closed / with assignee / assignee also acted):")
    for s, r in summary.items():
        print(f"  {s}: {r['closed_incidents']} / {r['with_assignee']} / {r['attributable']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--list-services", action="store_true", help="count Service:: labels and exit")
    p.add_argument("--scan-pages", type=int, default=5, help="pages of 100 incidents to scan")
    p.add_argument("--top", type=int, default=25, help="services to list")
    p.add_argument("--services", nargs="+", help="Service::<name> label values to fetch")
    p.add_argument("--per-service", type=int, default=8, help="closed incidents per service")
    p.add_argument("--max-docs", type=int, default=6, help="runbook files per service")
    p.add_argument(
        "--runbook-dir",
        action="append",
        default=[],
        metavar="SERVICE=FOLDER",
        help="runbook folder under docs/ when it is not the service slug",
    )
    p.add_argument(
        "--exclude-users",
        nargs="+",
        default=[],
        metavar="USERNAME",
        help="GitLab usernames to leave out (users flagged bot: true are always left out)",
    )
    p.add_argument(
        "--pseudonymize",
        action="store_true",
        help="replace usernames and names with stable codes (E01, E02, ...); links stay intact",
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default: {DEFAULT_OUT}")
    p.add_argument("--force", action="store_true", help="clear a non-empty --out not made here")
    args = p.parse_args()
    if args.list_services:
        list_services(args.scan_pages, args.top)
    elif args.services:
        if any("=" not in pair for pair in args.runbook_dir):
            p.error("--runbook-dir takes SERVICE=FOLDER")
        fetch_bundle(args)
    else:
        p.error("pass --list-services or --services")


if __name__ == "__main__":
    main()
