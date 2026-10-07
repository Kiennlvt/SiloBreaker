"""Import, normalize, hash and chunk one evidence bundle (FR-02, FR-03, FR-04)."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.evidence.adapters import ADAPTERS
from app.evidence.contract import EvidenceItemInput, Identities, sha256_json, sha256_text
from app.models import EvidenceBundle, EvidenceChunk, EvidenceItem

CHUNK_LINES = 6


def load_bundle(root: Path) -> tuple[dict, list[EvidenceItemInput]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise AppError(422, "manifest_missing", f"No manifest.json in {root.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identities = Identities(manifest.get("identities", {}))
    items: list[EvidenceItemInput] = []
    errors: list[str] = []
    for source, files in manifest.get("files", {}).items():
        adapter_cls = ADAPTERS.get(source)
        if adapter_cls is None:
            errors.append(f"unknown source family '{source}'")
            continue
        adapter = adapter_cls(root, identities)
        for path, record in zip(files, adapter.load(files), strict=False):
            try:
                items.extend(adapter.normalize(record))
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{path}: cannot normalize ({exc.__class__.__name__}: {exc})")
    if errors:
        raise AppError(422, "invalid_evidence", "; ".join(errors))
    return manifest, _dedupe(items)


def _dedupe(items: list[EvidenceItemInput]) -> list[EvidenceItemInput]:
    """Identical duplicates collapse; conflicting duplicates are rejected."""
    seen: dict[tuple[str, str], EvidenceItemInput] = {}
    for item in items:
        key = (item.source, item.external_id)
        if key in seen:
            if seen[key].payload_hash() != item.payload_hash():
                raise AppError(
                    422,
                    "duplicate_external_id",
                    f"{item.source}:{item.external_id} appears twice with different content",
                )
            continue
        seen[key] = item
    return sorted(seen.values(), key=lambda i: (i.source, i.external_id))


def chunk_text(text: str) -> list[tuple[int, int, str]]:
    """Split into stable citation units: Markdown sections when present, else line windows."""
    lines = text.splitlines() or [""]
    if any(line.startswith("## ") for line in lines):
        starts = [0] + [n for n, line in enumerate(lines) if line.startswith("## ")]
        bounds = list(zip(starts, [*starts[1:], len(lines)], strict=False))
        out = []
        for s, e in bounds:
            body = "\n".join(lines[s:e]).strip()
            if body:
                out.append((s + 1, e, body))
        return out
    chunks = []
    for start in range(0, len(lines), CHUNK_LINES):
        part = lines[start : start + CHUNK_LINES]
        body = "\n".join(part).strip()
        if body:
            chunks.append((start + 1, start + len(part), body))
    return chunks or [(1, 1, text.strip())]


def import_bundle(session: Session, root: Path) -> EvidenceBundle:
    manifest, items = load_bundle(root)
    content_hash = sha256_json(
        {
            "schema_version": manifest["schema_version"],
            "project_key": manifest["project_key"],
            "items": [i.payload_hash() for i in items],
        }
    )
    existing = session.scalar(
        select(EvidenceBundle).where(EvidenceBundle.content_hash == content_hash)
    )
    if existing:
        return existing  # importing the same bundle twice is idempotent

    times = [i.timestamp for i in items if i.timestamp]
    inventory = dict(manifest.get("source_inventory", {}))
    for family in ADAPTERS:
        inventory.setdefault(family, "unavailable")
    bundle = EvidenceBundle(
        project_key=manifest["project_key"],
        schema_version=manifest["schema_version"],
        content_hash=content_hash,
        source_inventory=inventory,
        coverage_start=min(times) if times else None,
        coverage_end=max(times) if times else None,
        import_complete=True,
    )
    session.add(bundle)
    session.flush()
    for it in items:
        row = EvidenceItem(
            bundle_id=bundle.id,
            source=it.source,
            source_type=it.source_type,
            external_id=it.external_id,
            parent_external_id=it.parent_external_id,
            author_id=it.author.id if it.author else None,
            author_display_name=it.author.display_name if it.author else None,
            participants=it.participants,
            occurred_at=it.timestamp,
            title=it.title,
            normalized_text=it.body,
            source_url=it.url,
            metadata_=it.metadata,
            payload_hash=it.payload_hash(),
        )
        session.add(row)
        session.flush()
        for n, (start, end, text) in enumerate(chunk_text(it.body)):
            session.add(
                EvidenceChunk(
                    evidence_item_id=row.id,
                    ordinal=n,
                    line_start=start,
                    line_end=end,
                    text=text,
                    text_hash=sha256_text(text),
                )
            )
    session.flush()
    return bundle
