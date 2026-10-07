# AGENTS.md

Rules for any coding agent (or human) working in this repository. Specs live in `docs/`.

## Architecture boundaries

- Modular monolith: `frontend/` (React + TS + Vite), `backend/` (FastAPI + Pydantic + SQLAlchemy), PostgreSQL.
- Backend modules: `evidence` (adapters, import, chunking), `analysis` (extraction contract, citation
  validation, offline extractor), `scoring` (pure deterministic rules), `knowledge` (capture, approval,
  OKF), `api` (routes, serializers), `operations` (idempotency), `audit`.
- The model **proposes**; application code **decides**. Numbers, gates, lifecycle transitions and
  approval live in code, never in model output.
- No microservices, queues or vector stores without a measured need.

## Commands

```bash
docker compose up -d db                       # PostgreSQL 16 on :5432 (+ silobreaker_test)
cd backend && pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
pytest -q                                     # uses silobreaker_test
ruff check app tests && ruff format --check app tests
cd frontend && npm install && npm run dev     # http://localhost:5173
npm run build                                 # type-check + build
python e2e/demo_flow.py                       # browser flow, API + dev server running
```

## Forbidden shortcuts

- Never read `fixtures/oracle/` from `backend/app/` or `frontend/`. It is for tests only.
- Never add inferred topics, risks, target gaps or answers to evidence in an adapter.
- Never let a model set `review_priority`, `eligibility_status`, `status` or any approval field.
- Never update `knowledge_version`, attempt answers or `audit_event` rows in place (DB triggers enforce it).
- Never duplicate scoring logic in the browser.
- Never treat a provider error as a learner failure or a finding.

## Migrations

- One Alembic migration per schema change, in `backend/migrations/versions/`.
- Schema changes touch shared contracts: serialize them, never run two agents on them in parallel.

## Done means

A task is done when its automated checks pass and the observable behaviour matches the acceptance
criterion in `docs/02_REQUIREMENTS.md`, not when an agent says it is done. Report the exact checks run.
