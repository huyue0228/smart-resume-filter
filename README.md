# 智能简历筛选系统

校招智能简历筛选系统，覆盖「查重与志愿排序 -> 岗位分类 -> 院校分类 -> 需求录入 -> 简历分配」主流程。系统按正式项目方式建设：后端启用登录与 RBAC 权限校验，前端菜单和按钮由后端权限码驱动；W3 认证、WeLink 真实下发等外部接口在方案确认后接入。

设计文档以 [`docs/需求描述.md`](docs/需求描述.md)、[`docs/后端设计.md`](docs/后端设计.md)、[`docs/数据库设计.md`](docs/数据库设计.md)、[`docs/前端设计.md`](docs/前端设计.md) 为准。

## 技术栈

- 后端：Django 4.2、Django REST Framework、Celery。
- 前端：Vite、React 18、Ant Design Pro、JavaScript `.jsx`。
- 本地开发：SQLite + Celery eager，同步执行任务，不依赖 Redis。
- 生产预期：PostgreSQL + Redis + Celery worker。

## 目录结构

```text
backend/    Django + DRF 后端，包含 accounts/core/ingestion/pipeline/api
frontend/   Vite + React 前端
docs/       四篇核心设计文档与原始材料
```

## 本地启动

### 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_base
python manage.py gen_sample
python manage.py load_sample
python manage.py runserver 8000
```

`seed_base` 会初始化：

- RBAC 权限点与预置角色。
- AI、WeLink、W3 预留开关等配置项。
- 多接口人功能测试账号和对应 Contact/Department。

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 [http://localhost:5173](http://localhost:5173)，并通过 Vite proxy 访问后端 `/api/`。

## 本地账号

初始化后可使用以下账号登录，默认密码均为 `pass1234`。

| 用户名 | 角色 | 用途 |
| --- | --- | --- |
| `admin` | 管理员 | 配置项、用户、角色、权限管理 |
| `hr` | HR | 数据导入、流水线处理、分配、下发、AI 复核 |
| `sec_tech` | 二级接口人 | 查看 HR 下发给技术二部的分配并转派三级 |
| `sec_product` | 二级接口人 | 查看 HR 下发给产品二部的分配并转派三级 |
| `ter_tech` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `ter_algo` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `ter_product` | 三级接口人 | 查看转派给自己的分配并反馈 |

这些账号用于正式权限链路的本地测试。W3 认证接入后，应由外部身份映射到系统 `User`、RBAC 角色和接口人 `Contact`。

## 权限与配置

系统默认启用 Token 登录。前端登录后调用 `/api/me/` 获取用户、角色、权限码、绑定接口人和数据范围。

权限边界：

- 管理员：维护配置项、用户、角色、权限。
- HR：导入主数据、运行处理流程、手动分配、下发二级接口人、查看全部分配。
- 二级接口人：只能查看下发给自己的分配，只能转派给本二级部门下的三级接口人。
- 三级接口人：只能查看转派给自己的分配，并提交通过/未通过反馈。

配置项页面维护：

- `ai_dispatch_threshold`
- `ai_review_threshold`
- `ai_timeout_seconds`
- `ai_concurrency`
- `ai_retry_count`
- `ai_retry_backoff_seconds`
- `welink_enabled`
- `w3_auth_enabled`

## 主要流程

1. 使用 `admin` 或 `hr` 登录。
2. 在简历库、岗位需求、院校清单、部门接口人页面导入对应 Excel/简历包；也可先执行 `gen_sample` 和 `load_sample`。
3. 简历导入后自动触发主流程；也可在分配页切换规则/AI 模式后重新处理。
4. HR 在「简历分配」查看待下发、待复核、已下发等分配尝试。
5. HR 单条、批量或一键全部下发给二级接口人。
6. 二级接口人登录后仅看到自己的分配，可导出简历并转派本部门三级接口人。
7. 三级接口人登录后仅看到转派给自己的分配，可导出简历并提交反馈。
8. HR/管理员可在配置项和用户权限页维护系统参数与 RBAC 绑定。

## API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login/` | 本地账号登录，返回 Token 与当前用户权限 |
| POST | `/api/auth/logout/` | 退出登录并删除 Token |
| GET | `/api/me/` | 当前用户、角色、权限码、接口人绑定和数据范围 |
| GET/POST/PATCH | `/api/users/` | 用户管理 |
| GET/POST/PATCH | `/api/roles/` | 角色管理与角色权限绑定 |
| GET | `/api/permissions/` | 后端预置权限树 |
| GET/PATCH | `/api/configs/` | 系统配置项 |
| POST | `/api/import/` | 上传简历列表、岗位、院校、接口人和简历包 |
| GET/POST | `/api/import/undo/` | 查看并撤销最近一次简历上传 |
| GET | `/api/resumes/` | 投递清单 |
| GET | `/api/candidates/` | 候选人聚合列表 |
| GET/POST/PATCH | `/api/jobs/` `/api/schools/` `/api/departments/` `/api/contacts/` | 主数据维护 |
| POST | `/api/pipeline/run/` | 触发处理流程，支持 `rule` / `ai` |
| GET | `/api/pipeline/runs/` | 处理运行记录 |
| GET | `/api/workflow-attempts/` | 分配尝试，后端按登录用户过滤数据范围 |
| POST | `/api/workflow-attempts/{id}/dispatch/` | HR 单条下发 |
| POST | `/api/workflow-attempts/bulk-dispatch/` | HR 批量或一键全部下发 |
| POST | `/api/workflow-attempts/{id}/assign-sub-contact/` | 二级接口人转派三级接口人 |
| POST | `/api/workflow-attempts/{id}/feedback/` | 三级接口人提交反馈 |
| GET | `/api/workflow-attempts/export/` | 导出简历 zip |
| GET/POST | `/api/agent-decisions/` | AI 决策查看与重试 |

## 验证命令

后端：

```bash
cd backend
./.venv/bin/python manage.py check
./.venv/bin/python manage.py test apps.pipeline apps.api apps.ingestion
./.venv/bin/python manage.py makemigrations accounts core --check --dry-run
```

前端：

```bash
cd frontend
npm run lint
npm run build
```

## 生产与外部系统预留

- W3 认证：当前保留 `w3_auth_enabled` 配置和本地 Token 登录。待 W3 接口方案确认后，应新增认证适配层，将 W3 身份映射到 `User`、角色和 `Contact`。
- WeLink：当前下发流程已保留状态和消息 ID 字段，`welink_enabled` 控制是否启用真实外部下发。真实接口确认后在服务层替换发送实现。
- 数据库：本地默认 SQLite；生产环境通过 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_PORT` 切换 PostgreSQL。
- Celery：本地默认 `CELERY_TASK_ALWAYS_EAGER=True`；生产环境应配置 Redis broker/backend 并启动 worker。
