# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

校招智能简历筛选系统。核心是一条**五步流水线**：查重与志愿排序 → 岗位分类 → 院校分类 → 需求录入 → 简历分配，每步支持**规则 / AI 双模式**。目标单批约 3 万条简历，2026 年 7 月底交付可用版本。当前为第一版（规则模式全链路打通，AI 模式为占位回退）。

后端 Django 4.2 + DRF，前端 Vite + React 18 + Ant Design Pro。文档在 `docs/`（需求与技术方案、数据库设计、前端设计、原始需求、项目路标与进展）。

## 常用命令

### 后端（在 `backend/` 下，先激活 venv）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_base    # 省份南北字典 + 分配倍数 Config（必跑，否则 Step1/Step5 无基础数据）
python manage.py gen_sample   # 生成样例 xlsx + 简历包 zip 到 backend/sample_data/
python manage.py load_sample  # 导入样例数据
python manage.py runserver 8000
```

迁移注意：本仓库自定义了 `AUTH_USER_MODEL=accounts.User`。新建/改模型后**必须显式指定 app** 生成迁移，否则可能漏建表：
`python manage.py makemigrations accounts core`（不带 app 名时曾出现 "No changes detected" 导致表缺失）。重置时 `rm backend/db.sqlite3` 后重新 migrate。

### 前端（在 `frontend/` 下）

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173，已代理 /api → localhost:8000
npm run lint     # oxlint
npm run build
```

### 完整栈（可选）

`docker compose up` 启动 Postgres + Redis + backend + Celery worker（生产形态）。本机 demo 不需要，用上面的 SQLite 路径即可。

## 架构要点（需跨文件理解的部分）

### 输入源解耦（关键约束）
业务逻辑**不得耦合 Excel 字段**。后续可能不再依赖 HR 表格输入。所有外部输入经 `apps/ingestion/` 适配为规范化领域模型（`apps/core/models.py`），流水线只依赖领域模型。新增输入源时扩展 ingestion 适配器，不要在 pipeline/api 里直接读 Excel 列名。

### 身份模型
- `Candidate`（人）由 `identity_hash = SHA-256(规范化姓名 + 规范化手机号)` 唯一标识，见 `apps/ingestion/identity.py`。
- `Resume`（投递）由 `apply_id`（应聘ID）唯一标识。**一人多投**：Candidate 1—N Resume。
- 无批次概念：所有数据进同一数据池，用 `imported_at` 时间标签筛选。导入用 `update_or_create`（按 identity_hash / apply_id）实现幂等增量更新。

### 流水线编排（`apps/pipeline/`）
- `runner.py` 是入口：`run_step(step, mode, scope)`，每次执行写一条 `ProcessingRun` 记录（含 success/failed + message）。
- **执行顺序非数字顺序**：`STEP_ORDER = [step1, step3, step2, step4, step5]` —— 院校分类(Step3)提前到岗位分类前，保证 Step5 分配时 `is_target_school` 已就绪。改步骤依赖关系时注意这点。
- 各步实现在 `services/`：dedup（Step1 志愿排序，户籍南北→GW/YLS，缺失按学校所在地，见 `regions.py`）、classify_job（Step2）、classify_school（Step3）、demand（Step4）、allocate（Step5：筛选 志愿1 + 目标院校 + 待处理状态，按部门 cap = max_hc × 倍数，倍数来自 Config `allocation_multiplier` 默认 5）。
- **规则/AI 策略**：`strategies.py` 的 `get_strategy(mode)` 返回 RuleStrategy 或 AIStrategy，统一接口。AIStrategy 目前回退到规则并附说明（接 OpenAI 待做）。仅 Step2/Step5 用 mode。
- `tasks.py` 是 Celery 包装；demo 下 `CELERY_TASK_ALWAYS_EAGER=True` 同步执行。

### API（`apps/api/`）
- DRF DefaultRouter（resumes/candidates/jobs/schools/departments/allocations/runs）+ 显式 `import/` 与 `pipeline/run/`。
- `AllocationViewSet` 的下发 action 方法名是 `dispatch_welink`（url_path="dispatch"），**不要命名为 `dispatch`** —— 会覆盖 DRF ViewSet 自身的 `dispatch` 方法。
- demo 全程 `AllowAny`（无鉴权），正式环境需启用 RBAC + 登录。

### 配置（`backend/config/settings.py`）
环境变量切换形态：设 `POSTGRES_DB` → 切 PostgreSQL（否则 SQLite）；`CELERY_TASK_ALWAYS_EAGER=False` + Redis → 真异步。默认全为 demo 友好值。

## 约定

- 前端是 **JavaScript（.jsx，非 TS）**。页面在 `frontend/src/pages/`，API 封装在 `src/api/`，布局 `src/layouts/BasicLayout.jsx`（ProLayout）。
- 注释与文档以中文为主，跟随现有风格。
- `纪要.md`、`backend/sample_data/`、`*.sqlite3`、`backend/media/` 不纳入版本控制（见 .gitignore）。
