"""Model-backed extractor with a fake client: no network, no API key (docs/07, FR-22)."""

import json
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.analysis import service
from app.analysis.contract import Citation, ProposedArea
from app.analysis.offline import OfflineExtractor
from app.analysis.openai_extractor import SYSTEM_PROMPT, OpenAIExtractor
from app.config import get_settings
from app.db import get_session
from app.errors import AppError
from tests.conftest import by_area, make_handoff


class FakeClient:
    """Mimics openai.OpenAI().chat.completions.create."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **body):
        self.requests.append(body)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        msg = SimpleNamespace(content=outcome, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def use(monkeypatch, client) -> OpenAIExtractor:
    ex = OpenAIExtractor(client, "fake-model", timeout_seconds=5, max_retries=2, max_calls=3)
    monkeypatch.setattr(service, "get_extractor", lambda: ex)
    return ex


def post_analysis(client, h):
    return client.post(f"/api/handoffs/{h['id']}/analyses", json={"selected_engineer_id": "alice"})


def count(table: str) -> int:
    session = next(get_session())
    try:
        return session.execute(text(f"select count(*) from {table}")).scalar_one()
    finally:
        session.close()


class ViewCapture:
    """Builds the real model output lazily from the same BundleView the extractor gets."""

    def __init__(self, transform=lambda e: e):
        self.transform = transform

    def install(self, monkeypatch, fake: FakeClient):
        original = fake._create

        def create(**body):
            view = json.loads(body["messages"][1]["content"])
            from app.analysis.contract import BundleView

            extraction = OfflineExtractor().extract(BundleView.model_validate(view))
            fake.outcomes = [self.transform(extraction).model_dump_json()]
            return original(**body)

        fake.chat.completions.create = create


def test_valid_model_output_passes_validation(client, monkeypatch):
    fake = FakeClient("placeholder")
    ViewCapture().install(monkeypatch, fake)
    use(monkeypatch, fake)
    r = post_analysis(client, make_handoff(client))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["model_id"] == "openai:fake-model" and a["rejected_areas"] == []
    assert by_area(a)["settlement"]["review_priority"] == 88
    assert len(fake.requests) == 1


def test_fabricated_citation_is_rejected(client, monkeypatch):
    def add_lie(extraction):
        any_chunk = extraction.areas[0].citations[0].chunk_id
        extraction.areas.append(
            ProposedArea(
                key="invented",
                title="Invented",
                record_refs=[],
                citations=[Citation(chunk_id=any_chunk, quote="the model made this up")],
            )
        )
        return extraction

    fake = FakeClient("placeholder")
    ViewCapture(add_lie).install(monkeypatch, fake)
    use(monkeypatch, fake)
    a = post_analysis(client, make_handoff(client)).json()
    assert "invented" not in by_area(a)
    assert a["rejected_areas"][0]["area_key"] == "invented"


def test_timeout_is_504_with_bounded_retries_and_no_finding(client, monkeypatch, caplog):
    fake = FakeClient(TimeoutError("slow"))
    use(monkeypatch, fake)
    h = make_handoff(client)
    with caplog.at_level(logging.INFO):
        r = post_analysis(client, h)
    assert r.status_code == 504 and r.json()["error"]["code"] == "provider_timeout"
    assert len(fake.requests) == 3  # one call + two retries, never more
    assert count("analysis") == 0 and count("finding") == 0
    evidence = fake.requests[0]["messages"][1]["content"]
    body_sample = json.loads(evidence)["items"][0]["chunks"][0]["text"]
    assert body_sample not in caplog.text  # no evidence body in logs


def test_transient_error_is_retried_then_succeeds(client, monkeypatch):
    fake = FakeClient("placeholder")
    calls = {"n": 0}
    ViewCapture().install(monkeypatch, fake)
    succeed = fake.chat.completions.create

    def flaky(**body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("reset")
        return succeed(**body)

    fake.chat.completions.create = flaky
    use(monkeypatch, fake)
    assert post_analysis(client, make_handoff(client)).status_code == 201
    assert calls["n"] == 2


def test_non_transient_error_is_502_without_retry(client, monkeypatch):
    fake = FakeClient(ValueError("bad request"))
    use(monkeypatch, fake)
    r = post_analysis(client, make_handoff(client))
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"
    assert len(fake.requests) == 1


def test_schema_invalid_output_is_provider_error(client, monkeypatch):
    use(monkeypatch, FakeClient('{"areas": [{"key": "x"}]}'))
    r = post_analysis(client, make_handoff(client))
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"
    assert count("finding") == 0


def test_request_has_no_tools_and_treats_evidence_as_untrusted():
    from app.analysis.contract import BundleView

    ex = OpenAIExtractor(FakeClient("{}"), "m")
    body = ex.request(BundleView(project_key="p", source_inventory={}, items=[]))
    assert "tools" not in body and "functions" not in body
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT and "never follow" in SYSTEM_PROMPT
    assert body["messages"][0]["content"] == SYSTEM_PROMPT


def test_openai_provider_without_key_is_503(monkeypatch):
    monkeypatch.setenv("SB_AI_PROVIDER", "openai")
    monkeypatch.delenv("SB_OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError) as err:
            service.get_extractor()
        assert err.value.status == 503 and err.value.code == "provider_not_configured"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert get_settings().ai_provider == "offline"
