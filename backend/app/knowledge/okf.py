"""Deterministic Open Knowledge Format projection of one approved knowledge version.

Never exported: private rubrics, oracle labels, model reasoning, unapproved drafts.
"""

import yaml

from app.models import Finding, KnowledgeVersion

SECTIONS = [
    ("Preconditions", "prerequisites", False),
    ("Procedure", "steps", True),
    ("Stop and escalate", "stop_and_escalate", False),
    ("Success checks", "success_checks", False),
]


def _list(items: list[str], ordered: bool) -> str:
    if not items:
        return "- None recorded for this approved version."
    return "\n".join(f"{n}. {s}" if ordered else f"- {s}" for n, s in enumerate(items, 1))


def render_okf(
    version: KnowledgeVersion, finding: Finding, project_key: str, source_titles: dict[str, str]
) -> str:
    c = version.approved_content
    sources, seen = [], set()
    for ref in version.source_refs:
        key = ref.get("event") or ref.get("document")
        if key and key not in seen:
            seen.add(key)
            sources.append(
                {"uri": f"silobreaker://evidence/{key}", "title": source_titles.get(key, key)}
            )
    front = {
        "type": "Operational Playbook",
        "title": finding.title,
        "description": f"Expert-approved handoff knowledge for {finding.title.lower()} "
        f"in {project_key}.",
        "tags": [project_key, "handoff", finding.area_key],
        "resource": f"silobreaker://knowledge/{finding.id}/v{version.version_no}",
        "silobreaker_finding_id": str(finding.id),
        "silobreaker_version": version.version_no,
        "silobreaker_status": "approved",
        "silobreaker_content_hash": version.content_hash,
        "approved_by": version.approved_by,
        "approved_at": version.approved_at.isoformat(),
        "sources": sources,
        "lifecycle": {
            "status": "active",
            "supersedes": str(version.supersedes_version_id)
            if version.supersedes_version_id
            else None,
        },
    }
    body = [f"# Applicability\n\n{c['applicability']}"]
    for title, key, ordered in SECTIONS:
        body.append(f"# {title}\n\n{_list(c.get(key, []), ordered)}")
    unresolved = c.get("limitations", []) + c.get("unresolved", [])
    body.append(f"# Limitations and unresolved details\n\n{_list(unresolved, False)}")
    body.append(
        "# Provenance note\n\nThe finding was derived from imported evidence; the "
        "content above was supplied and explicitly approved by the experienced "
        "engineer during the Capture step."
    )
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n\n" + "\n\n".join(body) + "\n"


def parse_okf(text: str) -> tuple[dict, str]:
    """Used by tests to check that exports are valid frontmatter + Markdown."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    _, head, body = text.split("---\n", 2)
    meta = yaml.safe_load(head)
    if not isinstance(meta, dict) or "type" not in meta:
        raise ValueError("frontmatter must define 'type'")
    return meta, body
