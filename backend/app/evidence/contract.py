"""Canonical evidence contract (docs/04_EVIDENCE_ADAPTERS.md).

Adapters may only emit observed provider data. They must never add an inferred topic,
risk, target gap, expected question or correct answer.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Author(BaseModel):
    id: str
    display_name: str


class EvidenceItemInput(BaseModel):
    source: str
    source_type: str
    external_id: str
    parent_external_id: str | None = None
    author: Author | None = None
    participants: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    title: str | None = None
    body: str
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def payload_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class Identities:
    """Maps provider-specific account IDs to one canonical person ID."""

    def __init__(self, table: dict[str, dict[str, str]]):
        self._by_provider: dict[tuple[str, str], tuple[str, str]] = {}
        for person_id, row in table.items():
            for provider, account in row.items():
                if provider != "display_name":
                    self._by_provider[(provider, account)] = (person_id, row["display_name"])

    def resolve(
        self, provider: str, account: str | None, fallback_name: str | None = None
    ) -> Author | None:
        if not account:
            return None
        person = self._by_provider.get((provider, account))
        if person:
            return Author(id=person[0], display_name=person[1])
        return Author(id=f"{provider}:{account}", display_name=fallback_name or account)


class EvidenceAdapter(Protocol):
    source: str

    def load(self, files: list[str]) -> list[dict[str, Any]]: ...

    def normalize(self, record: dict[str, Any]) -> list[EvidenceItemInput]: ...


def sha256_json(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()
