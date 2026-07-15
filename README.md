# 智能简历筛选系统

校招智能简历筛选系统。候选人主流程为「Step1 查重与志愿排序 → Step2 简历分类、分配与下发」；院校分类 Step3 和需求数据准备核对 Step4 是分配前置步骤，显式全流程按 `Step3 → Step4 → Step1 → Step2` 执行。系统按正式项目方式建设：后端启用登录与 RBAC 权限校验，前端菜单和按钮由后端权限码驱动；AI Agent 已接入，W3 认证和 WeLink 真实下发仍待外部接口确认。

设计文档以 [`docs/需求描述.md`](docs/需求描述.md)、[`docs/后端设计.md`](docs/后端设计.md)、[`docs/数据库设计.md`](docs/数据库设计.md)、[`docs/前端设计.md`](docs/前端设计.md) 为准。

当前实现已包含：候选人聚合简历库、表头筛选、可拖拽列宽、候选人/分配尝试 PDF 预览、按当前筛选导出单个原文件或 zip、Token 登录、RBAC 权限控制、部门接口人导入自动创建账号，以及真实 PDF 解析、OpenAI 结构化输出、后端评分护栏、AI 决策审计和 HR 处置闭环。

> 上生产前仍需完成真实数据隐私评审、模型评测、容量压测和外部系统联调；扫描件 PDF 当前不含 OCR，需要先转为可提取文本的 PDF。

关键实现落点：

- 后端分页：`backend/apps/api/pagination.py`，统一支持 `page_size`，最大 500。
- 后端导出/预览/筛选：`backend/apps/api/views.py`，候选人、岗位、院校、接口人和分配尝试列表按查询参数过滤。
- 后端测试：`backend/apps/api/tests.py` 覆盖分页、表头筛选、候选人导出、简历预览和接口人 replace 导入边界。
- 前端共享表格能力：`frontend/src/components/DataTableControls.jsx`、`frontend/src/components/ResizableHeaderCell.jsx`、`frontend/src/index.css`。
- 前端简历预览：`frontend/src/components/ResumePreview.jsx`，简历库详情和分配尝试详情复用。

## 技术栈

- 后端：Django 4.2、Django REST Framework、Celery。
- 前端：Vite、React 18、Ant Design Pro、JavaScript `.jsx`。
- 本地开发：SQLite + Celery eager，同步执行任务，不依赖 Redis。
- 生产预期：PostgreSQL + Redis + Celery `default` worker + threads `ai` worker。

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
- AI、WeLink 等非敏感运行配置。
- 多接口人功能测试账号和对应 Contact/Department。

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 [http://localhost:5173](http://localhost:5173)，并通过 Vite proxy 访问后端 `/api/`。

## Docker Compose 部署手册

本节用于没有 Codex/Agent 工具的服务器环境。服务器上只需要 Git、Docker 和 Docker Compose v2，按下面步骤操作即可构建项目镜像并拉起完整栈：

- PostgreSQL：业务数据库。
- Redis：Celery broker/result backend。
- Django backend 镜像：基于 `python:3.12.3-slim`，内置后端源码、Python 依赖、Gunicorn、PostgreSQL/Redis 客户端。
- Celery workers：复用 backend 镜像；普通 worker 消费 `default` 队列，threads AI worker 消费 `ai` 队列。
- Nginx frontend 镜像：先用 Node 构建 React，再用 Nginx 托管静态资源并反代 `/api` 到 backend。

当前 `docker-compose.yml` 适合内网试运行、验收和单机部署。正式公网生产建议在前面再加 HTTPS/WAF 或企业统一网关；项目内置的 frontend 容器已经使用 Nginx 托管前端静态资源。

compose 内的 frontend 容器通过 Nginx `proxy_pass http://backend:8000` 访问后端；本地非 Docker 开发时 Vite 仍默认代理到 `http://localhost:8000`。

### 1. 服务器前置条件

推荐服务器环境：

```bash
docker --version
docker compose version
git --version
```

建议版本：

- Docker Engine 24+。
- Docker Compose v2。
- Linux 服务器开放前端端口 `5173`，如需直接访问后端 API，再开放 `8000`。
- 至少 2 CPU / 4GB 内存；真实 AI 任务或大批量简历处理建议 4 CPU / 8GB 以上。

### 2. 拉取代码

```bash
git clone https://github.com/huyue0228/smart-resume-filter.git
cd smart-resume-filter
git fetch --tags origin
git checkout --detach <交付说明中的发布标签或 commit>
```

如果服务器已经有旧代码：

```bash
cd smart-resume-filter
git fetch --tags origin
git checkout --detach <交付说明中的发布标签或 commit>
```

### 3. 创建服务器 `.env`

在项目根目录复制 `.env.example` 为 `.env`。Docker Compose 会自动读取该文件。

```bash
cp .env.example .env
```

必须修改：

- `DJANGO_SECRET_KEY`：换成随机长字符串。
- `POSTGRES_PASSWORD`：换成强密码。
- `DJANGO_ALLOWED_HOSTS`：填服务器 IP 或域名，多个值用英文逗号分隔。
- `APP_VERSION`：建议发布时改成明确版本号，如 `2026-07-03-1`，方便回滚和排查。
- `DOCKER_PLATFORM`：内网服务器是常见 x86_64 Linux 时保持 `linux/amd64`；如果是 ARM 服务器，改成 `linux/arm64` 后重新构建镜像包。

启用 AI 模式前，使用管理员账号进入「系统设置 → AI 模型连接」完成连接配置并执行测试。内网 DeepSeek V4 与 GLM 4.7 共用同一地址；页面配置 Base URL、可选访问令牌和 API 风格，并通过该地址的 OpenAI-compatible `GET /models` 获取模型 ID（也可直接输入），不配置服务商/Profile。模型连接只从系统设置中的数据库配置读取，部署环境变量不会参与决定。API Key 非空时仅允许写入并加密保存，页面和 API 均不会回显；无鉴权内网服务可留空。未配置可用连接时 AI 会写入 `ai_not_configured` 失败决策，不会回退 Rule。

`RUN_SEED_BASE` 默认保持 `0`。不要在长期运行环境里把它改成 `1`，否则每次 backend 重启都可能把配置页中的参数重置为种子默认值。首次初始化请使用下一节的一次性 `init` 命令。

上传大小不再设置固定 Nginx 上限：`client_max_body_size 0` 表示由服务器磁盘、Docker volume、CPU/内存和超时时间决定实际可处理上限。大文件上传临时目录默认是 `/app/media/tmp_uploads`，位于 `media_data` 持久化卷；`GUNICORN_TIMEOUT` 默认 `1800` 秒。

### 4. 首次启动完整栈

```bash
docker compose build
docker compose --profile init run --rm init
docker compose up -d
```

首次执行 `docker compose build` 会下载基础镜像、安装依赖并生成后端、前端、PostgreSQL、Redis 四个项目镜像，时间会比较久。查看启动状态：

```bash
docker compose ps
docker compose logs -f backend
```

backend 启动命令会自动执行：

```bash
python manage.py migrate
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

一次性 `init` 命令会执行迁移和 `seed_base`，初始化 RBAC 权限、预置角色、配置项、功能测试账号、接口人和部门基础数据。后续升级和重启只执行迁移，不重复 seed，避免覆盖管理员在配置页维护的参数。

### 5. 访问系统

浏览器打开：

```text
http://服务器IP:5173/
```

如果部署了域名和反向代理，则访问你的域名。frontend 容器会把 `/api` 反代到 backend，不需要在浏览器里直接调用 `8000`。

本地预置账号默认密码均为 `pass1234`：

| 用户名 | 角色 | 用途 |
| --- | --- | --- |
| `admin` | 管理员 | 配置项、用户、角色、权限管理 |
| `hr` | HR | 数据导入、流水线处理、分配、下发、AI 复核 |
| `L2001` | 二级接口人 | 查看 HR 下发给技术二部的分配并转派三级 |
| `L2002` | 二级接口人 | 查看 HR 下发给产品二部的分配并转派三级 |
| `T3001` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `T3002` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `T3003` | 三级接口人 | 查看转派给自己的分配并反馈 |

### 6. 可选：生成并加载样例数据

如果服务器用于演示或验收，可以加载样例数据：

```bash
docker compose exec backend python manage.py gen_sample
docker compose exec backend python manage.py load_sample
```

加载后刷新前端页面，即可在简历库、岗位、院校和接口人页面看到样例数据；分配结果在简历库中查看。

如果服务器承载真实数据，不要执行样例数据命令。

### 7. 页面使用要点

- 简历库按候选人聚合展示，一名候选人一行；详情抽屉可查看全部投递、分配尝试、反馈和 PDF 预览。
- 简历库、岗位、院校、接口人等主要表格支持表头筛选和列宽拖拽；筛选在后端执行，分页接口支持 `page_size`，单页最大 500。
- 简历库可以按当前筛选条件导出候选人简历，也可以在候选人详情中操作分配尝试。仅命中一个可用文件且无缺失清单时返回原文件，多文件或存在缺失时返回 zip，并在页面提示导出成功数量和缺失数量。
- 部门接口人导入会按工号自动创建或更新登录账号，新账号默认密码 `pass1234`；清空重导时，本次文件中不存在的旧接口人及绑定账号会同步停用。

### 8. 常用运维命令

查看所有服务状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f ai-worker
docker compose logs -f frontend
docker compose logs -f db
docker compose logs -f redis
```

重启服务：

```bash
docker compose restart backend worker ai-worker frontend
```

停止服务但保留数据库卷：

```bash
docker compose down
```

停止并删除数据库卷，慎用，会清空 PostgreSQL 数据：

```bash
docker compose down -v
```

进入后端容器执行 Django 命令：

```bash
docker compose exec backend python manage.py check
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_base
```

### 9. 更新版本

每次发布新代码后，在服务器项目目录执行：

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
docker compose build
docker compose up -d
docker compose ps
```

当前 compose 会在服务器本机构建 `smart-resume-filter-backend:${APP_VERSION}`、`smart-resume-filter-frontend:${APP_VERSION}`、`smart-resume-filter-postgres:${POSTGRES_VERSION}`、`smart-resume-filter-redis:${REDIS_VERSION}` 四个项目镜像。只改 `.env` 时不需要重新 build，只需 `docker compose up -d`。

如果新版本明确要求重新初始化基础权限或新增种子字典，再手动执行：

```bash
docker compose --profile init run --rm init
```

不要把 `RUN_SEED_BASE` 长期开成 `1`。

更新后建议检查：

```bash
docker compose exec backend python manage.py check
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 ai-worker
```

### 9. 数据备份与恢复

备份 PostgreSQL：

```bash
set -a
. ./.env
set +a
mkdir -p backups
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/srf-$(date +%Y%m%d-%H%M%S).sql
```

如果 shell 没有加载 `.env`，可以直接写 `.env` 中的用户名和库名，例如：

```bash
docker compose exec -T db pg_dump -U srf_user srf > backups/srf.sql
```

恢复 PostgreSQL 前先确认目标库可以被覆盖。恢复示例：

```bash
docker compose exec -T db psql -U srf_user -d srf < backups/srf.sql
```

上传简历文件保存在 Docker 命名卷 `media_data` 中，并挂载到 backend 的 `/app/media`。建议和数据库一起备份：

```bash
MEDIA_BACKUP=media-$(date +%Y%m%d-%H%M%S)
docker compose cp backend:/app/media "backups/$MEDIA_BACKUP"
tar -czf "backups/$MEDIA_BACKUP.tar.gz" -C backups "$MEDIA_BACKUP"
```

### 10. AI Agent 配置

以下 AI 运行阈值、超时、并发、重试参数在系统配置页维护：

- `ai_dispatch_threshold`
- `ai_review_threshold`
- `ai_timeout_seconds`
- `ai_concurrency`（所有 worker/运行共享的自适应并发上限，默认 8，范围 1–20）
- `ai_retry_count`
- `ai_retry_backoff_seconds`

大模型连接由拥有 `settings.manage_ai_connection` 的角色在「系统设置 → AI 模型连接」维护；管理员角色默认拥有该权限，也可在「用户权限」按角色授予。页面配置共享内网 Base URL、API 风格和可选 API Key，通过 `GET /models` 获取模型 ID，同时允许直接输入模型 ID，并执行一次最小真实模型测试，不展示服务商/Profile。API Key 非空时仅可写入；服务端用 Django `SECRET_KEY` 派生的 Fernet 密钥加密存储，GET、前端状态和测试结果都不会返回明文或密文。未获授权的 HR 和接口人不可见、不可调用相关配置、模型发现和测试接口。

模型连接仅由管理员保存的数据库配置决定；运行时不会读取部署环境变量中的 API 风格、模型、Base URL 或 API Key，也不读取模型服务商/Profile 模板。通常无需为改动模型连接重启 backend/worker。

AI 运行中的连接异常会继续写入 `AgentDispatchDecision.error_code` / `error_message`，但内容仅为稳定错误码和脱敏摘要。第三方 SDK 原始异常不会进入数据库、API 响应或日志；backend 和 worker 标准输出仅记录 model、api_style、错误码和异常类型。排查时执行：

```bash
docker compose logs --tail=200 backend
docker compose logs --tail=200 worker
docker compose logs --tail=200 ai-worker
```

### 11. 服务器安全检查

上线前至少完成：

- `.env` 不提交 Git，不复制到公开位置。
- `DJANGO_SECRET_KEY` 和 `POSTGRES_PASSWORD` 已改为强随机值。
- `DJANGO_DEBUG=False`。
- `DJANGO_ALLOWED_HOSTS` 只填写实际 IP/域名，避免长期使用 `*`。
- PostgreSQL `5432` 和 Redis `6379` 不暴露到公网；如无外部访问需求，只允许内网或安全组限制。
- 管理员首次登录后修改默认密码。
- 真实 W3 认证接入前，本地 Token 登录只用于内网试运行。

### 12. 常见问题

`backend` 反复重启：

```bash
docker compose logs --tail=200 backend
```

重点看数据库连接、迁移错误、环境变量拼写和 `DJANGO_ALLOWED_HOSTS`。

前端页面能打开但接口失败：

```bash
docker compose logs --tail=200 frontend
docker compose logs --tail=200 backend
```

当前前端容器使用 Nginx 托管静态资源，`/api` 会反代到 backend。确认 `backend` 服务健康，并且浏览器访问的是 `FRONTEND_PORT`。

数据库密码改了但服务起不来：

如果 PostgreSQL 数据卷已经初始化，单纯修改 `.env` 的 `POSTGRES_PASSWORD` 不会自动修改旧数据库用户密码。试运行环境可清空重建：

```bash
docker compose down -v
docker compose up -d
```

真实数据环境不要执行 `down -v`。应先备份数据库，再在 PostgreSQL 内修改用户密码。

镜像构建慢：

首次 `docker compose build` 会安装 Python 和 npm 依赖，慢是正常现象。后续只要依赖文件没有变化，Docker 会复用缓存；如果服务器无法访问 Docker Hub、PyPI 或 npm registry，需要提前在可联网环境构建并导出完整离线镜像包，再在服务器 `docker load`。

## 本地账号

初始化后可使用以下账号登录，默认密码均为 `pass1234`。

| 用户名 | 角色 | 用途 |
| --- | --- | --- |
| `admin` | 管理员 | 配置项、用户、角色、权限管理 |
| `hr` | HR | 数据导入、流水线处理、分配、下发、AI 复核 |
| `L2001` | 二级接口人 | 查看 HR 下发给技术二部的分配并转派三级 |
| `L2002` | 二级接口人 | 查看 HR 下发给产品二部的分配并转派三级 |
| `T3001` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `T3002` | 三级接口人 | 查看转派给自己的分配并反馈 |
| `T3003` | 三级接口人 | 查看转派给自己的分配并反馈 |

这些账号用于正式权限链路的本地测试。W3 认证接入后，应按工号映射到系统 `User.username`、RBAC 角色和接口人 `Contact`。

## 权限与配置

系统默认启用 Token 登录。前端登录后调用 `/api/me/` 获取用户、角色、权限码、绑定接口人和数据范围。

权限边界：

- 管理员：维护用户、角色、权限、认证与安全配置，也可维护业务规则。
- HR：导入主数据、运行处理流程、手动分配、下发二级接口人、查看全部分配，并维护获授权的院校准入、专业词表等业务规则。
- 二级接口人：只能查看下发给自己的分配，只能转派给本二级部门下的三级接口人。
- 三级接口人：只能查看转派给自己的分配，并提交通过/未通过反馈。

配置项页面维护：

- `ai_dispatch_threshold`
- `ai_review_threshold`
- `ai_timeout_seconds`
- `ai_concurrency`（所有 worker/运行共享的自适应并发上限，默认 8，范围 1–20）
- `ai_retry_count`
- `ai_retry_backoff_seconds`
- `welink_enabled`

拥有 `settings.manage_ai_connection` 的角色可在「系统设置 → AI 模型连接」配置共享内网 Base URL、API 风格和可选 API Key，通过 `GET /models` 选择或直接输入模型 ID，并执行最小真实模型测试；管理员角色默认拥有该权限，HR/接口人未被授权时不可访问。页面不展示服务商/Profile。Key 非空时仅允许写入、不会被读取接口返回，服务端以由 Django `SECRET_KEY` 派生的 Fernet 密文存储。运行时只读取该数据库配置。日常修改连接请使用授权角色的配置页，避免在 shell、文档或工单中传播 API Key。

## 主要流程

1. 使用 `admin` 或 `hr` 登录。
2. 在简历库、岗位需求、院校清单、部门接口人页面导入对应 Excel/简历包；也可先执行 `gen_sample` 和 `load_sample`。
3. 简历上传含候选人时按全局 `ai_enabled` 只创建当前模式的一条 `ProcessingRun`，并完成 Step1→Step2。Rule 模式按确定性规则执行；生产 AI 模式由有界调度器把候选人任务投递到专用 `ai` 队列，所有 AI worker 共享 Redis 自适应并发上限。使用 AI 模式前由管理员在「系统设置 → AI 模型连接」配置并测试模型，再用少量真实脱敏样本验收评分、护栏与并发吞吐。
4. HR 在「简历分配」查看待下发、待复核、已下发等分配尝试。
5. HR 单条、批量或一键全部下发给二级接口人。
6. 二级接口人登录后仅看到自己的分配，可导出简历并转派本部门三级接口人。
7. 三级接口人登录后仅看到转派给自己的分配，可导出简历并提交反馈。
8. HR/管理员按权限维护业务配置；仅管理员在用户权限页维护 RBAC 和安全设置。

## API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login/` | 本地账号登录，返回 Token 与当前用户权限 |
| POST | `/api/auth/logout/` | 退出登录并删除 Token |
| GET | `/api/me/` | 当前用户、角色、权限码、接口人绑定和数据范围 |
| GET/POST/PATCH | `/api/users/` | 用户管理 |
| GET/POST/PATCH | `/api/roles/` | 角色管理与角色权限绑定 |
| GET | `/api/permissions/` | 后端预置权限树 |
| GET | `/api/configs/`、`/api/configs/{key}/` | 查询白名单内的非敏感配置项 |
| PATCH | `/api/configs/{key}/` | 更新白名单配置值 |
| POST | `/api/import/` | 上传简历列表、岗位、院校、接口人和简历包 |
| GET/POST | `/api/import/undo/` | 查看并撤销最近一次简历上传 |
| GET | `/api/resumes/` | 投递清单 |
| GET | `/api/resumes/{id}/preview/` | 预览单条投递 PDF |
| GET | `/api/candidates/` | 候选人聚合列表 |
| GET | `/api/candidates/export/` | 按候选人 ID 或当前筛选条件导出单个原文件或 zip |
| GET/POST/PATCH | `/api/jobs/` `/api/schools/` `/api/departments/` `/api/contacts/` | 主数据维护 |
| POST | `/api/pipeline/run/` | 提交 `step + scope`，由后端按全局 `ai_enabled` 创建唯一 Rule 或 AI 运行；请求携带 `mode` / `modes` 返回 400。生产异步返回 202，本地 `CELERY_TASK_ALWAYS_EAGER=True` 同步完成返回 200，均返回 `processing_runs` |
| GET | `/api/pipeline/runs/` | 处理运行记录 |
| GET | `/api/ai-availability/` | 具有 `pipeline.run` 权限时只返回 AI 是否可用的 `enabled` 布尔值 |
| GET | `/api/workflow-attempts/` | 分配尝试，后端按登录用户过滤数据范围 |
| POST | `/api/workflow-attempts/{id}/dispatch/` | HR 单条下发 |
| POST | `/api/workflow-attempts/bulk-dispatch/` | HR 批量或一键全部下发 |
| POST | `/api/workflow-attempts/{id}/assign-sub-contact/` | 二级接口人转派三级接口人 |
| POST | `/api/workflow-attempts/{id}/feedback/` | 三级接口人提交反馈 |
| GET | `/api/workflow-attempts/export/` | 导出单个原文件或 zip |
| GET | `/api/workflow-attempts/{id}/resume-preview/` | 按分配尝试数据范围预览 PDF |
| GET | `/api/agent-decisions/` | AI 决策查看 |
| POST | `/api/agent-decisions/{id}/retry/` | AI 决策重试 |

列表接口默认分页，支持 `page` / `page_size` 查询参数；`page_size` 最大 500。

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

- W3 认证：当前未实现；待接口方案确认后，应新增仅管理员可维护的认证适配层，按工号映射到 `User.username`，并继续复用既有 RBAC 角色和 `Contact` 绑定。
- WeLink：当前下发流程已保留状态和消息 ID 字段，`welink_enabled` 控制是否启用真实外部下发。真实接口确认后在服务层替换发送实现。
- 数据库：本地默认 SQLite；生产环境通过 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_PORT` 切换 PostgreSQL。
- Celery：本地默认 `CELERY_TASK_ALWAYS_EAGER=True`；生产环境应配置 Redis broker/backend，并同时启动 `default` worker 与 threads `ai` worker。
