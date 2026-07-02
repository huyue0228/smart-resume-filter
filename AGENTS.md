# AGENTS.md

This file gives Codex working context for this repository. The project was originally bootstrapped with Claude Code; keep `CLAUDE.md` as historical context, but prefer this file for Codex sessions.

## Project Overview

校招智能简历筛选系统。核心候选人处理流程是：查重与志愿排序 -> 简历分类、分配与下发。院校分类、需求录入、部门接口人维护是分配前置数据准备；分配环节支持规则 / AI 双模式。

Tech stack:

- Backend: Django 4.2 + Django REST Framework + Celery, default local mode uses SQLite and eager Celery.
- Frontend: Vite + React 18 + Ant Design Pro, JavaScript `.jsx` only.
- Docs: `docs/` contains four design documents: `需求描述.md`, `后端设计.md`, `数据库设计.md`, `前端设计.md`.

## Docs Workflow

The four design documents under `docs/` are the source of truth for product and implementation decisions. Before changing backend, frontend, database models, or workflow behavior, read the relevant design document first and keep implementation aligned with it.

When modifying design documents under `docs/`:

1. Read the current related docs before editing; do not rely on memory.
2. Update the target document, keeping the original requirement intent unless the user explicitly changes it.
3. Ask the document-sync agent to check and synchronize related wording across `需求描述.md`, `后端设计.md`, `数据库设计.md`, and `前端设计.md`.
4. Ask the same persistent reviewer agent to review the document changes. Reuse the existing reviewer in the session; only create a new reviewer if the old one is unavailable.
5. Run `git diff --check -- docs/需求描述.md docs/后端设计.md docs/前端设计.md docs/数据库设计.md` and use `rg` when needed to check for stale wording.
6. Stage and commit the involved docs after review passes. Do not push unless the user explicitly asks.

Do not create additional design documents casually. Prefer updating the four established documents to avoid multi-document drift.

## Common Commands

Backend, from `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_base
python manage.py gen_sample
python manage.py load_sample
python manage.py runserver 8000
```

Frontend, from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
```

Full stack, optional:

```bash
docker compose up
```

## Verification

Use focused verification for the files changed:

- Backend model/API/pipeline changes: run relevant Django checks or commands from `backend/`, at minimum `python manage.py check`. If migrations are involved, run `python manage.py makemigrations accounts core`.
- Frontend changes: run `npm run lint` and `npm run build` from `frontend/` when practical.
- End-to-end demo path: migrate, `seed_base`, `gen_sample`, `load_sample`, run backend on `8000`, frontend on `5173`.

There is no dedicated test suite in the current repo.

## Architecture Rules

- Business logic must not depend directly on Excel column names. External files are adapted through `backend/apps/ingestion/` into domain models in `backend/apps/core/models.py`.
- The data model has no batch concept. Use `imported_at` time tags for filtering; incremental imports should query by business keys in the service layer, update a single match, create when absent, and reject ambiguous duplicates.
- `Candidate` is the person entity and is merged by normalized name + normalized phone in the application layer; missing-phone candidates are skipped.
- `Resume` is the application entity and is matched by `apply_id` in the application layer; one candidate can have many resumes.
- Keep comments and user-facing docs mainly in Chinese, following the existing style.

## Pipeline Notes

- Entry point: `backend/apps/pipeline/runner.py`, `run_step(step, mode, scope)`.
- The `all` order is intentionally `step1`, `step3`, `step2`, `step4`; do not assume numeric order. `step5` is only a legacy allocation alias, and new frontend/backend work should prefer the Step2 allocation flow. Step3 must run before allocation so school tags are ready.
- Step implementations live in `backend/apps/pipeline/services/`.
- `strategies.py` exposes `RuleStrategy` and `AIStrategy`; existing code may still contain AI placeholder or rule-fallback behavior, but new development must follow the AI Agent screening design in the four docs.
- AI Agent screening is a hard-rule-constrained recommendation flow: it only evaluates the candidate's current effective volunteer, never skips volunteer order or school admission rules, and never automatically falls back to Rule after AI failure.
- AI failures, timeouts, parse failures, invalid output, missing references, and guardrail blocks should be recorded for HR handling. HR chooses retry AI, switch to Rule, manual assignment, or archive handling.
- Frontend drives processing by calling `/api/pipeline/run/` step by step via `frontend/src/components/useProcessRunner.jsx`.

## API Notes

- Main API code is under `backend/apps/api/`.
- Routes use DRF `DefaultRouter` for resumes, candidates, jobs, schools, departments, contacts, workflow attempts, agent decisions, and runs.
- Explicit endpoints include `import/`, `import/undo/`, and `pipeline/run/`.
- `AssignmentAttemptViewSet` has a `dispatch_welink` method with `url_path="dispatch"`. Do not rename it to `dispatch`, because that would override DRF ViewSet dispatch.
- `AssignmentAttemptViewSet.export_resumes` returns a zip `HttpResponse`, not a DRF `Response`.
- Demo mode uses `AllowAny`; production work must add real RBAC/login rather than relying on frontend role hiding.

## Frontend Notes

- Pages live in `frontend/src/pages/`.
- API wrappers live in `frontend/src/api/`.
- Layout and role-based menu filtering live in `frontend/src/layouts/BasicLayout.jsx`.
- `RoleContext.jsx` stores demo roles `HR` / `contact` in localStorage. This is presentation-only access control.
- `ModeContext.jsx` stores `rule` / `ai` in localStorage. The allocation page owns the mode switch; switching mode reruns the Step2 allocation flow.
- Import UI is decentralized through `frontend/src/components/ImportButton.jsx`; there is no standalone import page.

## Migration Gotchas

- The backend uses `AUTH_USER_MODEL = "accounts.User"`.
- When creating or changing models, run migrations with explicit app names:

```bash
python manage.py makemigrations accounts core
```

Running `makemigrations` without app names has previously missed changes.

## Generated / Local Files

Do not commit local demo data or generated artifacts:

- `backend/db.sqlite3`
- `backend/sample_data/`
- `backend/media/`
- `纪要.md`
