"""Structured Knowledge Unit content and the offline structurer.

The structurer may only reorganize the expert's own sentences. It never adds facts, and
anything it cannot place stays visible as a step for the expert to move or delete.
"""

import re

from pydantic import BaseModel, Field, field_validator


class KnowledgeContent(BaseModel):
    applicability: str = Field(min_length=3)
    prerequisites: list[str] = []
    steps: list[str] = Field(min_length=1)
    stop_and_escalate: list[str] = []
    success_checks: list[str] = []
    limitations: list[str] = []
    unresolved: list[str] = []

    @field_validator(
        "prerequisites", "steps", "stop_and_escalate", "success_checks", "limitations", "unresolved"
    )
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


STOP = re.compile(
    r"\b(never|do not|don't|must not|stop|pause|escalat\w*|unknown|unclear)\b", re.IGNORECASE
)
SUCCESS = re.compile(
    r"\b(done when|done means|confirm that|verify that|success|resolved when)\b", re.IGNORECASE
)
PREREQ = re.compile(r"\b(you need|requires?|make sure you have|before you start)\b", re.IGNORECASE)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def structure_answer(answer: str, applicability: str) -> KnowledgeContent:
    buckets: dict[str, list[str]] = {
        "prerequisites": [],
        "steps": [],
        "stop_and_escalate": [],
        "success_checks": [],
    }
    for s in split_sentences(answer):
        if SUCCESS.search(s):
            buckets["success_checks"].append(s)
        elif STOP.search(s):
            buckets["stop_and_escalate"].append(s)
        elif PREREQ.search(s):
            buckets["prerequisites"].append(s)
        else:
            buckets["steps"].append(s)
    if not buckets["steps"]:
        buckets["steps"] = ["(Expert to confirm the ordered steps)"]
    unresolved = [
        f"No {name.replace('_', ' ')} stated by the expert"
        for name in ("stop_and_escalate", "success_checks")
        if not buckets[name]
    ]
    return KnowledgeContent(applicability=applicability, unresolved=unresolved, **buckets)
