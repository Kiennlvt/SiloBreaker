"""Deterministic offline extractor, a stand-in for the model step.

It reads only the BundleView, never the oracle, and treats evidence text as data: it
looks for issue keys, thread/PR parents and a small lexicon, and never follows any
instruction written inside the evidence. It lets the full flow run without an API key
and gives tests a reproducible baseline. A model-backed extractor must return the same
Extraction schema and passes through the same citation validation.
"""

import re
from collections import defaultdict

from app.analysis.contract import (
    BundleView,
    Citation,
    Extraction,
    ItemView,
    ProposedArea,
    ProposedDocument,
    ProposedEvent,
)

MANUAL = re.compile(r"\bmanual(?:ly)?\b|\bby hand\b", re.IGNORECASE)
FACET_HEADINGS = {
    "preconditions": re.compile(
        r"^##\s*(preconditions|prerequisites)", re.IGNORECASE | re.MULTILINE
    ),
    "steps": re.compile(r"^##\s*(steps|procedure)", re.IGNORECASE | re.MULTILINE),
    "stop_and_escalate": re.compile(r"^##\s*(stop|escalat)", re.IGNORECASE | re.MULTILINE),
    "success_checks": re.compile(
        r"^##\s*(success|verification|verify)", re.IGNORECASE | re.MULTILINE
    ),
}
INCIDENT_TYPES = {"incident"}


def _first_sentence(text: str, limit: int = 140) -> str:
    line = next((ln.strip(" -#") for ln in text.splitlines() if ln.strip(" -#")), text)
    m = re.match(r"(.+?[.!?])(\s|$)", line)
    s = m.group(1) if m else line
    return s[:limit]


def _cite(item: ItemView) -> Citation:
    chunk = item.chunks[0]
    return Citation(chunk_id=chunk.id, quote=_first_sentence(chunk.text))


def _text(item: ItemView) -> str:
    return "\n".join(c.text for c in item.chunks) + "\n" + (item.title or "")


class OfflineExtractor:
    model_id = "offline-rules/1"

    def extract(self, view: BundleView) -> Extraction:
        children: dict[str, list[ItemView]] = defaultdict(list)
        for it in view.items:
            if it.parent_ref:
                children[it.parent_ref].append(it)

        issues = [
            it for it in view.items if it.source == "jira" and it.source_type.startswith("issue:")
        ]
        by_component: dict[str, list[ItemView]] = defaultdict(list)
        for issue in issues:
            for comp in issue.metadata.get("components", []):
                by_component[comp].append(issue)

        areas = []
        for comp, comp_issues in sorted(by_component.items()):
            area_refs: set[str] = set()
            events = []
            for issue in sorted(comp_issues, key=lambda i: i.ref):
                key = issue.ref.split(":", 1)[1]
                linked = self._linked_records(issue, key, view.items, children)
                area_refs.update(r.ref for r in linked)
                if issue.source_type.split(":", 1)[1] not in INCIDENT_TYPES:
                    continue
                resolver = self._resolver(issue, linked)
                cites = [_cite(issue)]
                resolver_rec = next(
                    (
                        r
                        for r in linked
                        if resolver and r.author_id == resolver and r.ref != issue.ref
                    ),
                    None,
                )
                if resolver_rec:
                    cites.append(_cite(resolver_rec))
                events.append(
                    ProposedEvent(
                        key=key,
                        record_refs=sorted(r.ref for r in linked),
                        resolver_id=resolver,
                        manual=any(MANUAL.search(_text(r)) for r in linked),
                        citations=cites,
                    )
                )
            documents = []
            for doc in view.items:
                if doc.source != "document":
                    continue
                where = f"{doc.metadata.get('path', '')} {doc.title or ''}".lower()
                if comp.lower() not in where:
                    continue
                body = _text(doc)
                facets = [f for f, rx in FACET_HEADINGS.items() if rx.search(body)]
                documents.append(
                    ProposedDocument(record_ref=doc.ref, facets=facets, citations=[_cite(doc)])
                )
                area_refs.add(doc.ref)
            title = comp.replace("-", " ").capitalize()
            if events:
                title += " recovery"
            areas.append(
                ProposedArea(
                    key=comp,
                    title=title,
                    record_refs=sorted(area_refs),
                    events=events,
                    documents=documents,
                    citations=[_cite(comp_issues[0])],
                )
            )
        return Extraction(areas=areas)

    def _linked_records(
        self,
        issue: ItemView,
        key: str,
        all_items: list[ItemView],
        children: dict[str, list[ItemView]],
    ) -> list[ItemView]:
        """Records about one event, across tools, so one incident counts once."""
        pattern = re.compile(rf"\b{re.escape(key)}\b")
        linked = {issue.ref: issue}
        for c in children.get(issue.ref, []):
            linked[c.ref] = c
        for it in all_items:
            if it.source in ("slack", "github") and not it.parent_ref:
                hay = _text(it) + " " + str(it.metadata.get("head_ref") or "")
                if pattern.search(hay):
                    linked[it.ref] = it
                    for c in children.get(it.ref, []):
                        linked[c.ref] = c
        return sorted(linked.values(), key=lambda r: r.ref)

    def _resolver(self, issue: ItemView, linked: list[ItemView]) -> str | None:
        """Assignee of a resolved incident counts only if they also acted in the record.

        A name mention or plain authorship never counts as operational participation.
        """
        if (issue.metadata.get("status") or "").lower() not in {"done", "resolved", "closed"}:
            return None
        assignee = issue.metadata.get("assignee")
        if assignee and any(r.author_id == assignee and r.ref != issue.ref for r in linked):
            return assignee
        return None
