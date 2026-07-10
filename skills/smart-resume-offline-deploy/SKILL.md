---
name: smart-resume-offline-deploy
description: 在 Linux amd64 内网服务器上部署、验证、卸载校招智能简历筛选系统离线 Docker 包。部署和卸载均要求向操作者确认；默认卸载保留业务数据，删除数据卷或镜像必须再次输入明确确认词。
---

# 智能简历筛选系统离线部署

本 Skill 必须在已解压的离线包根目录使用。先阅读本文件，再执行 `scripts/` 下的脚本；不要手工省略确认步骤，也不要在日志、对话或截图中输出 `.env` 内的密钥。

## 包含内容

- `scripts/deploy.sh`：校验、导入镜像、初始化数据库、启动并验证服务。
- `scripts/verify.sh`：检查服务状态、Django 配置和 Nginx 配置。
- `scripts/uninstall.sh`：停止并卸载服务；默认保留数据库和上传文件。
- `agents/deployment-agent.md`：部署时必须执行的确认与交付口径。
- `agents/uninstall-agent.md`：卸载时必须执行的风险确认口径。

## 部署

1. 确认服务器 CPU 为 `x86_64/amd64`，Docker Engine 与 Docker Compose v2 已安装。
2. 在离线包根目录执行：

```bash
bash smart-resume-offline-deploy-skill/scripts/deploy.sh
```

3. 脚本首次运行会创建 `.env` 模板。必须先修改 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS`、`POSTGRES_PASSWORD`，然后才允许继续。
4. 需要 AI 模式时，在 `.env` 填写 `AI_PROFILE` 和对应密钥；密钥只会传给 backend/worker 容器。

部署脚本会在修改 Docker 状态前要求操作者输入 `yes`。若检测到同项目已有容器，会说明升级会保留数据卷并再次确认。

## 验证

```bash
bash smart-resume-offline-deploy-skill/scripts/verify.sh
```

成功条件：服务状态正常，backend 的 `manage.py check` 通过，frontend 的 `nginx -t` 通过。

## 卸载

```bash
bash smart-resume-offline-deploy-skill/scripts/uninstall.sh
```

默认卸载只停止并删除容器、网络，保留 PostgreSQL 数据卷和上传文件卷。脚本会展示该影响并要求输入 `yes`。

如需彻底清理，按脚本提示额外输入：

- `DELETE_DATA`：删除数据库与上传文件卷，不可恢复。
- `REMOVE_IMAGES`：删除本项目已导入的 Docker 镜像。

这两个确认词即使操作者已确认普通卸载也不可省略。
