import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_DB = os.environ.get(
    "SB_TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/silobreaker_test"
)
os.environ["SB_DATABASE_URL"] = TEST_DB

BACKEND = Path(__file__).resolve().parents[1]
ORACLE = BACKEND.parent / "fixtures" / "oracle"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    from app.config import get_settings
    from app.db import reset_engine

    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(TEST_DB)
    with engine.begin() as c:
        c.execute(text("drop schema public cascade; create schema public;"))
    engine.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/demo/reset")
        assert r.status_code == 200, r.text
        c.bundle = r.json()
        yield c


@pytest.fixture
def oracle():
    """Evaluator-only expectations. Never imported by app code."""
    return {p.stem: json.loads(p.read_text()) for p in ORACLE.glob("*.json")}


def make_handoff(client, expert="alice", successor="bob"):
    r = client.post(
        "/api/handoffs",
        json={"bundle_id": client.bundle["id"], "expert_id": expert, "successor_id": successor},
    )
    assert r.status_code == 201, r.text
    return r.json()


def analyze(client, handoff, selected=None, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    r = client.post(
        f"/api/handoffs/{handoff['id']}/analyses",
        json={"selected_engineer_id": selected},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def by_area(analysis):
    return {f["area_key"]: f for f in analysis["findings"]}
