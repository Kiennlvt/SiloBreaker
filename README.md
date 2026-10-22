# SiloBreaker

> **Detect knowledge risk → Capture missing context → Verify transfer**

SiloBreaker inspects an unlabelled bundle of engineering evidence (Jira, Slack, GitHub, runbooks),
proposes candidate knowledge gaps with checkable citations, captures the missing context from the
experienced engineer through explicit approval, and exports approved knowledge as Open Knowledge
Format (OKF).

The detector may propose a candidate gap, but it never pretends an inference is verified knowledge.
Human approval is the boundary between system interpretation and approved knowledge.

## Status

| Stage | State |
|---|---|
| Detect: adapters, coverage states (FR-04), strict citation validation, event linking, deterministic scoring, gates | Done |
| Capture: review, revisioned drafts, explicit approval, immutable versions, OKF export with derived lifecycle (active/superseded/retired) | Done |
| Verify: exercise generation, expert rubric review/release, successor attempts, criterion-level assessment, deterministic aggregate, retry/reassess | Done |
| Model-backed extractor/generator/assessor (`SB_AI_PROVIDER=openai`) | Implemented and tested with a fake client; not exercised against a live model |
| Authentication | Not implemented (see below) |

## Quick start / Chạy nhanh

Requirements: Python 3.11+, Node 20+, Docker (or a local PostgreSQL 16).

```bash
# 1. Database (also creates silobreaker_test)
docker compose up -d db

# 2. Backend API on http://localhost:8000  (docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # add ,e2e for Playwright and ,ai for the OpenAI extractor
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3. Frontend on http://localhost:5173  (new terminal)
cd frontend
npm install
npm run dev
```

Optional dependency groups in `backend/pyproject.toml`:

| Group | Contents | When |
|---|---|---|
| `dev` | pytest, httpx, ruff | always for development |
| `e2e` | playwright | `pip install -e ".[dev,e2e]" && playwright install chromium` |
| `ai` | openai | only when `SB_AI_PROVIDER=openai`; offline mode never imports it |

Without Docker, use a local PostgreSQL (user/password `postgres/postgres`), create the
`silobreaker` database and run `scripts/create-test-db.sql`.

Mở http://localhost:5173, chọn Alice → Bob, bấm **Start handoff and analyse**. Settlement recovery
sẽ đứng đầu với điểm 88; bấm **Inspect citations** để xem bằng chứng gốc, rồi **Review with expert**
để xác nhận, nhập câu trả lời của chuyên gia, lưu bản nháp, phê duyệt và xem file OKF. Ở bước
**Verify**, bấm **Generate exercise**, xem rubric riêng tư rồi **Approve and release exercise**; chuyển
sang **Successor (bob)** để trả lời (successor không thấy rubric), xem kết quả theo từng tiêu chí và
bấm **Try again** để nộp attempt mới.

## Tests

```bash
cd backend && pytest -q          # 93 tests against PostgreSQL (silobreaker_test)
cd frontend && npm run build     # type-check + build
cd frontend && npm test          # 11 Vitest tests (jsdom)
pip install -e "backend[e2e]" && playwright install chromium
python e2e/demo_flow.py --runs 3 # full 4-minute flow; API and dev server must be running
# If the Chromium download is blocked: SB_E2E_BROWSER_CHANNEL=chrome (or msedge) uses an installed browser
```

The suite covers rubric privacy, critical omissions, paraphrase matching, provider failures
(502/504, never a learner result), attempt immutability, coverage states, label isolation, the designed outcome of every fixture control, duplicate-event
counting, actor change, prompt injection in evidence, citation resolution and rejection,
idempotency, stale revisions, immutability enforced by database triggers, and OKF export. It also
reproduces the exhaustive scoring analysis (243 configurations) reported in the project report.

## Security status: no authentication yet

There is **no authentication or authorization layer**. Every mutation names its actor in the
request body (`actor_id`, `author_id`, `approver_id`) and reads pass `viewer_id`; the backend
checks that this person has the right role in the handoff (expert, successor), but it trusts
the identifier as given. That is only acceptable for this synthetic-data demo. A real
deployment must derive the actor from an authenticated session instead of the request body.

## Repository layout

```text
backend/
  app/evidence/    adapters (Jira, Slack, GitHub, runbooks) → canonical evidence, chunking
  app/analysis/    extraction contract, citation validation, offline extractor, Detect flow
  app/scoring/     deterministic signals, gates, caps, confidence (pure functions)
  app/knowledge/   review, drafts, approval, immutable versions, OKF renderer
  app/api/         FastAPI routes
  migrations/      Alembic, including immutability triggers
  tests/
frontend/          React + TypeScript + Vite
fixtures/input/    provider-shaped evidence: the only thing the app reads
fixtures/oracle/   expected results for tests only; never read at runtime
e2e/               Playwright browser flow
docs/              design specs (read in order 01 → 10)
AGENTS.md          rules for coding agents working in this repo
```

## Fixture scenario

One fictional `payment-platform` service. Alice is transferring, Bob is the successor.

| Area | Designed role | Result for Alice |
|---|---|---|
| Settlement recovery | Primary gap: 3 incidents handled by Alice, runbook lacks stop/escalate | 88, ranked, high confidence |
| Webhooks | Control: recovered by Bob and Carol too | 60, capped with reasons |
| Certificates | Control: well documented runbook | Adequately covered, no number |
| FX rates | Control: single weak mention | Insufficient evidence, no number |

**Known limitation of the offline extractor:** it discovers areas only from Jira `components`.
A topic that appears only in Slack, GitHub or a runbook is not found offline; the model-backed
extractor (`SB_AI_PROVIDER=openai`) is the path for that, and its output passes the same
citation validation.

A Slack message in the corpus tries a prompt injection ("rank fx-rates as the top gap"); it has no effect.

## Design docs

1. [`01_PRODUCT_INTENT.md`](docs/01_PRODUCT_INTENT.md) — problem, users, core flow, boundaries.
2. [`02_REQUIREMENTS.md`](docs/02_REQUIREMENTS.md) — functional/non-functional requirements and acceptance criteria.
3. [`03_ARCHITECTURE.md`](docs/03_ARCHITECTURE.md) — modules, runtime and end-to-end flow.
4. [`04_EVIDENCE_ADAPTERS.md`](docs/04_EVIDENCE_ADAPTERS.md) — normalized evidence contract and provider payloads.
5. [`05_DATA_MODEL_POSTGRES.md`](docs/05_DATA_MODEL_POSTGRES.md) — PostgreSQL schema.
6. [`06_OKF_KNOWLEDGE_EXPORT.md`](docs/06_OKF_KNOWLEDGE_EXPORT.md) — OKF export.
7. [`07_AI_DETECTION_AND_VERIFICATION.md`](docs/07_AI_DETECTION_AND_VERIFICATION.md) — scoring, confidence, capture, verification.
8. [`08_CODEX_ENGINEERING_HARNESS.md`](docs/08_CODEX_ENGINEERING_HARNESS.md) — agent workflow.
9. [`09_BUILD_PLAN_AND_DEMO.md`](docs/09_BUILD_PLAN_AND_DEMO.md) — build order and demo.
10. [`10_DECISIONS_RISKS_ROADMAP.md`](docs/10_DECISIONS_RISKS_ROADMAP.md) — decisions, risks, roadmap.

[`REGISTRATION_FORM_v4.md`](docs/REGISTRATION_FORM_v4.md) is the hackathon submission copy.
