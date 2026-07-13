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
docker compose build
docker compose --profile init run --rm init
docker compose up
```

Compose uses project Dockerfiles now: backend/worker share `smart-resume-filter-backend:${APP_VERSION:-latest}` based on Python 3.12.3, frontend uses a built React bundle served by Nginx, and db/redis are wrapped as project images for offline deployment. See README for server deployment details.

## Verification

Use focused verification for the files changed:

- Backend model/API/pipeline changes: run relevant Django checks or commands from `backend/`, at minimum `python manage.py check`. If migrations are involved, run `python manage.py makemigrations accounts core`.
- Frontend changes: run `npm run lint` and `npm run build` from `frontend/` when practical.
- End-to-end local path: migrate, `seed_base`, `gen_sample`, `load_sample`, run backend on `8000`, frontend on `5173`, then log in with seeded RBAC accounts.
- Backend tests exist for ingestion, pipeline, API, AI decision retry, and RBAC/data-scope behavior. Prefer focused tests plus `python manage.py check`.

## Architecture Rules

- Business logic must not depend directly on Excel column names. External files are adapted through `backend/apps/ingestion/` into domain models in `backend/apps/core/models.py`.
- The data model has no batch concept. Use `imported_at` time tags for filtering; incremental imports should query by business keys in the service layer, update a single match, create when absent, and reject ambiguous duplicates.
- `Candidate` is the person entity and is merged by normalized name + normalized phone in the application layer; missing-phone candidates are skipped.
- `Resume` is the application entity and is matched by `apply_id` in the application layer; one candidate can have many resumes.
- Keep comments and user-facing docs mainly in Chinese, following the existing style.

## Pipeline Notes

- Entry point: `backend/apps/pipeline/runner.py`; API submits `ProcessingRun` records through `create_runs()` and workers execute them through `execute_run()`.
- The `all` order is intentionally `step3`, `step4`, `step1`, `step2`; do not assume numeric order. Step3/Step4 prepare or verify prerequisite data before the candidate flow. A normal resume upload runs `step1`, then `step2`.
- Step implementations live in `backend/apps/pipeline/services/`.
- `strategies.py` owns deterministic Rule matching. Formal AI screening lives under `backend/apps/pipeline/ai/` and must never fall back to Rule. Model profile templates live in `backend/config/ai_models.json`; the only runtime model connection source is the `settings.manage_ai_connection`-protected system settings page. AI mode requires a text-extractable PDF.
- AI Agent screening is a hard-rule-constrained recommendation flow: it only evaluates the candidate's current effective volunteer, never skips volunteer order or school admission rules, and never automatically falls back to Rule after AI failure.
- AI failures, timeouts, parse failures, invalid output, missing references, and guardrail blocks should be recorded for HR handling. HR chooses retry AI, switch to Rule, manual assignment, or archive handling.
- Frontend submits one `/api/pipeline/run/` request with non-empty `modes` and optional `scope` via `frontend/src/components/useProcessRunner.jsx`; the backend creates independent runs and executes them through the sequential Celery orchestration.

## API Notes

- Main API code is under `backend/apps/api/`.
- Standard pagination lives in `backend/apps/api/pagination.py`; list APIs support `page_size` with a max of 500.
- Routes use DRF `DefaultRouter` for resumes, candidates, jobs, schools, departments, contacts, workflow attempts, agent decisions, and runs.
- Explicit endpoints include `auth/login/`, `auth/logout/`, `me/`, `permissions/`, `import/`, `import/undo/`, and `pipeline/run/`.
- `AssignmentAttemptViewSet` has a `dispatch_welink` method with `url_path="dispatch"`. Do not rename it to `dispatch`, because that would override DRF ViewSet dispatch.
- Resume export and preview helpers return Django `HttpResponse`, not DRF `Response`. Keep zip headers such as `X-Export-Count` / `X-Export-Missing` and preview header `X-Resume-Filename` stable for the frontend.
- Candidate export, resume direct preview, assignment-attempt scoped preview, and visible-column list filters are covered in `backend/apps/api/tests.py`; keep those tests aligned when changing table columns or query params.
- API defaults to authenticated access. Local formal development uses DRF Token login seeded by `seed_base`; W3 authentication is a future adapter around the same `User`/RBAC/`Contact` mapping.
- Contact imports automatically create/update interface-user accounts with `username = Contact.employee_no`, default password `pass1234` for new users, and the matching second/third-level contact role. W3 login will also map by employee number.

## Frontend Notes

- Pages live in `frontend/src/pages/`.
- API wrappers live in `frontend/src/api/`.
- Layout and permission-code menu filtering live in `frontend/src/layouts/BasicLayout.jsx`.
- `RoleContext.jsx` holds the current token-backed user, `/api/me/` permissions, roles, contact binding, and data-scope helpers. Do not reintroduce demo role switching.
- Rule/AI selection is made by the resume-processing dialog and submitted as a non-empty `modes` array; allocation subpages only filter existing attempts by source.
- Import UI is decentralized through `frontend/src/components/ImportButton.jsx`; there is no standalone import page.
- Shared table header filters and resizable column wiring live in `frontend/src/components/DataTableControls.jsx` and `frontend/src/components/ResizableHeaderCell.jsx`; reuse them for dense data tables instead of rebuilding per page.
- PDF preview UI lives in `frontend/src/components/ResumePreview.jsx` and supports direct resume previews and assignment-attempt scoped previews.
- `SchoolsPage.jsx` exposes the current school name, label and province fields only. North/south judgment is calculated from province at runtime; do not add regional fields or a regional configuration page.

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
