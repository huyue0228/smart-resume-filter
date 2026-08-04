# AGENTS.md

This file gives Codex working context for this repository. The project was originally bootstrapped with Claude Code; keep `CLAUDE.md` as historical context, but prefer this file for Codex sessions.

## Project Overview

This is an intelligent resume screening system for campus recruitment. The core candidate workflow is: deduplication and volunteer-order resolution -> resume classification, assignment, and dispatch. School classification, job-demand entry, and department-contact maintenance provide the prerequisite data for assignment; assignment supports both Rule and AI modes.

Tech stack:

- Backend: Django 4.2 + Django REST Framework + Celery, default local mode uses SQLite and eager Celery.
- Frontend: Vite + React 18 + Ant Design Pro, JavaScript `.jsx` only.
- Docs: `docs/` contains four design documents: `需求描述.md`, `后端设计.md`, `数据库设计.md`, `前端设计.md`.

## Docs Workflow

The four design documents under `docs/` are the source of truth for product and implementation decisions. Before changing backend, frontend, database models, or workflow behavior, read the relevant design document first and keep implementation aligned with it.

Routine bug fixes, UI polish, tests, and internal refactors do not require an automatic documentation sync. Update the design documents only when the change introduces or changes a product requirement, public API contract, database schema, architecture/workflow behavior, deployment process, or when the user explicitly asks for documentation changes. Do not automatically stage, commit, or push code or documentation; only do so when the user explicitly requests it.

When modifying design documents under `docs/`:

1. Read the current related docs before editing; do not rely on memory.
2. Update the target document, keeping the original requirement intent unless the user explicitly changes it.
3. Ask the document-sync agent to check and synchronize related wording across `需求描述.md`, `后端设计.md`, `数据库设计.md`, and `前端设计.md`.
4. Ask the same persistent reviewer agent to review the document changes. Reuse the existing reviewer in the session; only create a new reviewer if the old one is unavailable.
5. Run `git diff --check -- docs/需求描述.md docs/后端设计.md docs/前端设计.md docs/数据库设计.md` and use `rg` when needed to check for stale wording.
6. Leave the reviewed documentation changes in the working tree unless the user explicitly asks to stage, commit, or push them.

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

For an amd64 offline release and external-drive handoff, use the project Skill at `skills/smart-resume-offline-release/SKILL.md`; its single entry point builds, verifies, packages, and copies the release without modifying the current Git worktree.

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
- `strategies.py` owns deterministic Rule matching. Formal AI screening lives under `backend/apps/pipeline/ai/` and must never fall back to Rule. The only runtime model connection source is the `settings.manage_ai_connection`-protected system settings page; the shared intranet Base URL, selectable API style, model ID and optional access token are stored there without provider/Profile templates. The backend reads OpenAI-compatible `GET /models` for model choices while keeping the field directly editable. AI mode requires a text-extractable PDF.
- AI Agent screening is a hard-rule-constrained recommendation flow: it only evaluates the candidate's current effective volunteer, never skips volunteer order or school admission rules, and never automatically falls back to Rule after AI failure.
- AI failures, timeouts, parse failures, invalid output, missing references, and guardrail blocks should be recorded for HR handling. HR chooses retry AI, switch to Rule, manual assignment, or archive handling.
- Frontend submits one `/api/pipeline/run/` request with a single explicit `mode` (`rule` or `ai`) and optional `scope` via `frontend/src/components/useProcessRunner.jsx`; the backend creates one mode-fixed run and executes it through the sequential Celery orchestration. AI is selectable only while the current full model-connection fingerprint has a successful test.

## API Notes

- Main API code is under `backend/apps/api/`.
- Standard pagination lives in `backend/apps/api/pagination.py`; list APIs support `page_size` with a max of 500.
- Routes use DRF `DefaultRouter` for resumes, candidates, jobs, schools, departments, contacts, workflow attempts, agent decisions, and runs.
- Explicit endpoints include `auth/logout/`, `auth/w3/status/`, `auth/w3/start/`, `auth/w3/callback/`, `auth/w3/complete/`, `me/`, `permissions/`, `import/`, `import/undo/`, and `pipeline/run/`.
- `AssignmentAttemptViewSet` has a `dispatch_welink` method with `url_path="dispatch"`. Do not rename it to `dispatch`, because that would override DRF ViewSet dispatch.
- Resume export and preview helpers return Django `HttpResponse`, not DRF `Response`. Keep zip headers such as `X-Export-Count` / `X-Export-Missing` and preview header `X-Resume-Filename` stable for the frontend.
- Candidate export, resume direct preview, assignment-attempt scoped preview, and visible-column list filters are covered in `backend/apps/api/tests.py`; keep those tests aligned when changing table columns or query params.
- API defaults to authenticated access. Production login is W3 OAuth2 only; W3 completion returns the existing DRF Token session. `/api/auth/login/` and `/admin/` are intentionally absent and both return 404. When `DEBUG=True` and W3 is not ready, use `python manage.py issue_dev_token --username <employee_no>` and let the login page validate that Token through `/api/me/` before storing it.
- `User` retains Django's `AbstractUser.password` column for framework compatibility, but every account must have an unusable password. User APIs reject any `password` field, contact imports and `seed_base` must call `set_unusable_password()`, and no UI or documentation should reintroduce default-password, initial-password, or reset-password flows.
- Contact imports automatically create/update interface-user accounts with `username = Contact.employee_no`, an unusable password, and the matching second/third-level contact role. W3 maps by employee number plus email.

## Frontend Notes

- Pages live in `frontend/src/pages/`.
- API wrappers live in `frontend/src/api/`.
- Layout and permission-code menu filtering live in `frontend/src/layouts/BasicLayout.jsx`.
- `RoleContext.jsx` holds the current token-backed user, `/api/me/` permissions, roles, contact binding, and data-scope helpers. Do not reintroduce demo role switching.
- Rule/AI selection is made by both the resume-upload dialog and the resume-processing dialog, and submitted as one explicit mode (`processing_mode` for uploads, `mode` for `/api/pipeline/run/`). Rule is always available; AI is enabled only when the current model connection test is valid. Allocation subpages only filter existing attempts by source.
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
