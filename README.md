# 智能简历筛选系统

校招简历筛选系统：覆盖「查重 → 分类 → 院校分类 → 需求录入 → 分配」五步流水线，支持规则 / AI 双模式。
后端 Django + DRF（+ Celery/Redis 可选），前端 React + Ant Design Pro。

设计文档见 [`docs/`](docs/)：需求与技术方案、数据库设计、前端设计、原始需求。

## 目录结构

```
backend/    Django + DRF 后端（apps: core / accounts / ingestion / pipeline / api）
frontend/   Vite + React + Ant Design 前端
docs/       设计文档
docker-compose.yml   完整栈（Postgres + Redis + 异步 Celery，可选）
```

## 本机最简 demo（推荐，无需 Docker）

后端默认 **SQLite + Celery eager（同步执行）**，不需要 Postgres/Redis。

### 1) 后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_base      # 省份南北字典 + 分配倍数
python manage.py gen_sample     # 生成样例 xlsx 到 backend/sample_data/
python manage.py load_sample    # 导入样例数据（也可在前端「数据导入」页手动上传）
python manage.py runserver 8000
```

后端跑在 http://localhost:8000 ，API 前缀 `/api/`，Django Admin 在 `/admin/`
（如需后台账号：`python manage.py createsuperuser`）。

### 2) 前端

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 ，已代理 /api 到 8000
```

### 3) 走一遍流程

1. 打开 http://localhost:5173
2. 各数据页自带导入入口（已用 `load_sample` 则可跳过）：
   - 「简历库 → 导入简历」：简历信息列表 xlsx + 简历包 zip
   - 「岗位需求 → 导入岗位」、「院校清单 → 导入院校」、「部门接口人 → 导入接口人」：各自的 xlsx
3. 「处理流水线」：点「一键全流程」或逐步运行；Step2/Step5 可切规则/AI
4. 「简历库」查看打标结果；「简历分配」查看分配并「下发」
5. 右上角「演示身份」可切 HR / 接口人：接口人仅能看到「分配结果」一页（前端演示用权限隔离，后端鉴权见 M6）

## 完整栈（可选：Postgres + Redis + 异步 Celery）

```bash
docker compose up        # 启动 db / redis / backend / celery worker
# 前端仍在本地跑：
cd frontend && npm install && npm run dev
```

后端切 PostgreSQL 通过环境变量 `POSTGRES_DB` 等；Celery 异步通过 `CELERY_TASK_ALWAYS_EAGER=False` + Redis broker。

## API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/import/` | 上传 4 表 + 简历包（multipart，字段 resume_list/jobs/schools/contacts/resume_package，mode=incremental\|replace） |
| GET  | `/api/resumes/` | 投递清单（分页/筛选 search,status,imported_after,imported_before） |
| GET  | `/api/candidates/` `/api/jobs/` `/api/schools/` `/api/departments/` | 主数据 CRUD |
| POST | `/api/pipeline/run/` | 触发流水线 `{step: step1..step5\|all, mode: rule\|ai}` |
| GET  | `/api/pipeline/runs/` | 运行记录 |
| GET  | `/api/allocations/` | 分配结果 |
| POST | `/api/allocations/{id}/dispatch/` | WeLink 下发 |

> 注：demo 关闭了鉴权（AllowAny）便于本机测试；正式环境需启用 RBAC + 登录（见技术方案）。

## 第一版范围与后续

- 已实现：数据导入与身份归并、五步**规则模式**全链路、CRUD/分配 API、前端核心页面、样例数据。
- AI 模式（Step2/Step5）目前为占位（回退规则并附说明），后续接 OpenAI。
- 待接：RBAC/W3 登录、WeLink 真实下发、规则 vs AI 对比页、性能压测。
