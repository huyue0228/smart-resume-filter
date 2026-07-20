---
name: smart-resume-offline-deploy
description: 在 Linux 服务器上部署、验证、卸载校招智能简历筛选系统。支持当前源码仓库 amd64/arm64 构建部署和 amd64 纯镜像离线包部署，并通过固定编号菜单和二次确认控制 Docker 变更及数据清理。
---

# 智能简历筛选系统离线部署

先阅读本文件，再执行 `scripts/` 下的脚本；不得手工省略确认步骤，也不得在日志、对话或截图中输出 `.env` 内的密钥。脚本可从源码仓库的 `skills/` 目录调用，也可随纯镜像离线包一同调用；未能自动判断根目录时，使用 `DEPLOY_ROOT=/path/to/package` 指定部署根目录。

## 固定交互

与用户交互时，只展示当前阶段规定的编号选项，等待用户回复单个编号。收到其它内容时，原样重复该菜单；不要猜测意图、不要改用自由文本确认、不要把不同阶段的选项合并。

- 部署前检查：`1. 已完成检查，继续`、`2. 先修改 .env`、`3. 取消`。
- 未找到环境文件：`1. 创建 .env 模板并退出`、`2. 取消`。
- 已有部署：`1. 升级并保留数据`、`2. 仅查看状态`、`3. 取消`。
- 开始部署：`1. 构建/导入镜像、初始化并启动`、`2. 取消`。
- 卸载范围：`1. 常规卸载并保留数据`、`2. 删除容器和数据卷`、`3. 删除容器、数据卷和镜像`、`4. 取消`。
- 不可恢复清理：`1. 确认永久删除`、`2. 返回并保留数据`。

## 包含内容

- `scripts/deploy.sh`：校验、导入镜像、初始化数据库、启动并验证服务。
- `scripts/verify.sh`：检查服务状态、Django 配置和 Nginx 配置。
- `scripts/uninstall.sh`：停止并卸载服务；默认保留数据库和上传文件。
- `assets/deployment-agent.md`：部署时必须执行的确认与交付口径。
- `assets/uninstall-agent.md`：卸载时必须执行的风险确认口径。

## 部署

1. 确认服务器 CPU 为 `x86_64/amd64` 或 `aarch64/arm64`，Docker Engine 与 Docker Compose v2 已安装。当前纯镜像离线包仅支持 amd64；源码模式支持两种架构，且 `.env` 的 `DOCKER_PLATFORM` 必须与服务器一致。
2. 在源码仓库或离线包根目录执行：

```bash
bash skills/smart-resume-offline-deploy/scripts/deploy.sh
```

若 Skill 随离线包存放在包根目录下一层，则将上面的 `skills/smart-resume-offline-deploy` 改为实际 Skill 目录名。

3. 脚本首次运行会创建 `.env` 模板。必须先修改 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS`、`POSTGRES_PASSWORD`、独立的 `RESTIC_PASSWORD`，并将 `BACKUP_TARGET_PATH` 指向异机挂载或外置磁盘，然后才允许继续。
4. `DEPLOY_MODE=auto`（默认）在存在 `smart-resume-filter-images-amd64.tar` 时选择离线模式，否则从当前源码构建。可显式指定 `DEPLOY_MODE=offline` 或 `DEPLOY_MODE=source`。
5. 离线模式要求交付包内的 `docker-compose.yml` 只使用 `image:`，不得保留 `build:`；源码模式使用当前项目的 Compose 构建后端、前端、PostgreSQL、Redis 和备份工具镜像。
6. 首次部署才会执行 `init` 写入基础权限、账号和预置数据。检测到已有部署时，脚本只更新镜像并启动服务，迁移由 backend 自动完成，不会重置管理员在系统设置中维护的配置。
7. 部署不决定 AI 功能是否启用、模型连接或 API Key。服务启动后，由拥有权限的管理员在「系统设置 → AI 模型连接」配置并测试；不要在部署对话、脚本参数或日志中提供 API Key。

部署脚本会先显示部署前检查菜单；若检测到同项目已有容器，会说明升级会保留数据卷与配置并让操作者选择升级、仅查看状态或取消。

## 验证

```bash
bash skills/smart-resume-offline-deploy/scripts/verify.sh
```

成功条件：`db`、`redis`、`backend`、`worker`、`ai-worker`、`frontend`、`backup-scheduler` 均处于运行状态；`worker` 只消费 `default`，`ai-worker` 以 threads 池消费 `ai` 队列，备份调度默认每小时执行。backend 的 `manage.py check` 通过，frontend 的 `nginx -t` 通过。

## 卸载

```bash
bash skills/smart-resume-offline-deploy/scripts/uninstall.sh
```

默认卸载只停止并删除容器、网络，保留 PostgreSQL 数据卷和上传文件卷。若选择删除数据卷或镜像，脚本会再显示“确认永久删除 / 返回并保留数据”菜单；未选择确认不会执行清理。
