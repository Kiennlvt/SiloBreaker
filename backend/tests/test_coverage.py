"""Source coverage states (FR-04) and runbook heading variants."""

import json
import shutil

import pytest

from app.analysis.offline import doc_facets
from app.analysis.service import run_analysis
from app.db import get_session
from app.errors import AppError
from app.evidence.importer import import_bundle
from app.models import EvidenceItem, Finding, Handoff
from tests.conftest import BACKEND

FIXTURES = BACKEND.parent / "fixtures" / "input"


@pytest.fixture
def bundle_dir(tmp_path):
    root = tmp_path / "bundle"
    shutil.copytree(FIXTURES, root)

    def edit(inventory: dict, drop_files: tuple[str, ...] = ()):
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["source_inventory"] = inventory
        for family in drop_files:
            manifest["files"].pop(family, None)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return root

    return edit


@pytest.fixture
def session(client):  # `client` resets the database first
    s = next(get_session())
    try:
        yield s
    finally:
        s.rollback()
        s.close()


ALL = {"jira": "included", "slack": "included", "github": "included", "document": "included"}


def _findings(session, bundle):
    h = Handoff(
        project_key=bundle.project_key, bundle_id=bundle.id, expert_id="alice", successor_id="bob"
    )
    session.add(h)
    session.flush()
    analysis = run_analysis(session, h, "alice")
    return {f.area_key: f for f in session.query(Finding).filter_by(analysis_id=analysis.id)}


def test_unknown_source_state_is_rejected(session, bundle_dir):
    root = bundle_dir(ALL | {"slack": "partly"})
    with pytest.raises(AppError) as err:
        import_bundle(session, root)
    assert err.value.status == 422 and err.value.code == "invalid_source_state"


def test_excluded_family_is_not_imported(session, bundle_dir):
    bundle = import_bundle(session, bundle_dir(ALL | {"github": "excluded"}))
    assert bundle.source_inventory["github"] == "excluded"
    sources = {i.source for i in session.query(EvidenceItem).filter_by(bundle_id=bundle.id)}
    assert "github" not in sources and "jira" in sources


def test_family_without_files_or_state_is_unavailable(session, bundle_dir):
    inventory = {k: v for k, v in ALL.items() if k != "slack"}
    bundle = import_bundle(session, bundle_dir(inventory, drop_files=("slack",)))
    assert bundle.source_inventory["slack"] == "unavailable"


def test_four_states_are_distinguishable_and_change_the_bundle(session, bundle_dir):
    full = import_bundle(session, bundle_dir(ALL))
    mixed = import_bundle(
        session,
        bundle_dir(
            {"jira": "included", "slack": "incomplete", "github": "excluded"},
            drop_files=("document",),
        ),
    )
    assert mixed.id != full.id  # the declared coverage is part of the bundle identity
    assert mixed.source_inventory == {
        "jira": "included",
        "slack": "incomplete",
        "github": "excluded",
        "document": "unavailable",
    }
    assert full.import_complete and not mixed.import_complete


def test_incomplete_documents_make_d_unknown(session, bundle_dir):
    bundle = import_bundle(session, bundle_dir(ALL | {"document": "incomplete"}))
    s = _findings(session, bundle)["settlement"]
    assert s.signal_values["signals"]["D"] is None
    assert s.eligibility_status == "insufficient" and s.review_priority is None
    assert "incomplete" in s.summary


def test_alternative_runbook_headings_are_recognised():
    body = """# Payout Runbook

## Before you begin
- Access to the payout console.

## Rollback
1. Revert the payout batch.

## When to stop
- Stop if the bank rejects the batch twice.

## Validation
- The bank statement shows the batch once.
"""
    assert set(doc_facets(body)) == {
        "preconditions",
        "steps",
        "stop_and_escalate",
        "success_checks",
    }


@pytest.mark.parametrize(
    ("heading", "facet"),
    [
        ("## Requirements", "preconditions"),
        ("### Procedure", "steps"),
        ("## How to recover", "steps"),
        ("## Escalation", "stop_and_escalate"),
        ("## Abort conditions", "stop_and_escalate"),
        ("## Verification", "success_checks"),
        ("## Checks after recovery", "success_checks"),
    ],
)
def test_heading_variants(heading, facet):
    assert doc_facets(f"# Doc\n\n{heading}\n- text\n") == [facet]


def test_plain_mentions_are_not_headings():
    assert doc_facets("# Doc\n\nWe validate things and stop sometimes.\n") == []
