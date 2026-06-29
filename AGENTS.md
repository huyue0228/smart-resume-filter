# AGENTS.md

This file gives Codex working context for this repository. The project was originally bootstrapped with Claude Code; keep `CLAUDE.md` as historical context, but prefer this file for Codex sessions.

## Project Overview

校招智能简历筛选系统。核心流程是五步流水线：查重与志愿排序 -> 岗位分类 -> 院校分类 -> 需求录入 -> 简历分配。每步面向规则 / AI 双模式；当前规则模式已打通，AI 模式仍是占位回退。

Tech stack:

- Backend: Django 4.2 + Django REST Framework + Celery, default local mode uses SQLite and eager Celery.
- Frontend: Vite + React 18 + Ant Design Pro, JavaScript `.jsx` only.
- Docs: `docs/` contains requirements, technical design, database design, frontend design, roadmap, and original requirements.

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
- The data model has no batch concept. Use `imported_at` time tags for filtering and `update_or_create` for idempotent incremental imports.
- `Candidate` is the person entity and is unique by `identity_hash` from normalized name + phone.
- `Resume` is the application entity and is unique by `apply_id`; one candidate can have many resumes.
- Keep comments and user-facing docs mainly in Chinese, following the existing style.

## Pipeline Notes

- Entry point: `backend/apps/pipeline/runner.py`, `run_step(step, mode, scope)`.
- The all-step order is intentionally `step1`, `step3`, `step2`, `step4`, `step5`; do not assume numeric order. Step3 must run before Step5 so `is_target_school` is ready.
- Step implementations live in `backend/apps/pipeline/services/`.
- `strategies.py` exposes `RuleStrategy` and `AIStrategy`; `AIStrategy` currently falls back to rules with explanatory text.
- Frontend drives processing by calling `/api/pipeline/run/` step by step via `frontend/src/components/useProcessRunner.jsx`.

## API Notes

- Main API code is under `backend/apps/api/`.
- Routes use DRF `DefaultRouter` for resumes, candidates, jobs, schools, departments, contacts, allocations, and runs.
- Explicit endpoints include `import/`, `import/undo/`, and `pipeline/run/`.
- `AllocationViewSet` has a `dispatch_welink` method with `url_path="dispatch"`. Do not rename it to `dispatch`, because that would override DRF ViewSet dispatch.
- `AllocationViewSet.export_resumes` returns a zip `HttpResponse`, not a DRF `Response`.
- Demo mode uses `AllowAny`; production work must add real RBAC/login rather than relying on frontend role hiding.

## Frontend Notes

- Pages live in `frontend/src/pages/`.
- API wrappers live in `frontend/src/api/`.
- Layout and role-based menu filtering live in `frontend/src/layouts/BasicLayout.jsx`.
- `RoleContext.jsx` stores demo roles `HR` / `contact` in localStorage. This is presentation-only access control.
- `ModeContext.jsx` stores `rule` / `ai` in localStorage. The allocation page owns the mode switch; switching mode reruns Step2 + Step5.
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

