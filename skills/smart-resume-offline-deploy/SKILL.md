---
name: smart-resume-offline-deploy
description: 在 Linux amd64 内网服务器上部署、验证、卸载校招智能简历筛选系统离线 Docker 包。部署与卸载时通过固定编号菜单和二次确认控制 Docker 变更及数据清理。
---

# 智能简历筛选系统离线部署

本 Skill 必须在已解压的离线包根目录使用。先阅读本文件，再执行 `scripts/` 下的脚本；不得手工省略确认步骤，也不得在日志、对话或截图中输出 `.env` 内的密钥。

## 固定交互

与用户交互时，只展示当前阶段规定的编号选项，等待用户回复单个编号。收到其它内容时，原样重复该菜单；不要猜测意图、不要改用自由文本确认、不要把不同阶段的选项合并。

- 部署前检查：`1. 已完成检查，继续`、`2. 先修改 .env`、`3. 取消`。
- 已有部署：`1. 升级并保留数据`、`2. 仅查看状态`、`3. 取消`。
- 开始部署：`1. 导入镜像并启动`、`2. 取消`。
- 卸载范围：`1. 常规卸载并保留数据`、`2. 删除容器和数据卷`、`3. 删除容器、数据卷和镜像`、`4. 取消`。
- 不可恢复清理：`1. 确认永久删除`、`2. 返回并保留数据`。

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

部署脚本会显示同一套编号菜单；若检测到同项目已有容器，会说明升级会保留数据卷并让操作者选择升级、仅查看状态或取消。

## 验证

```bash
bash smart-resume-offline-deploy-skill/scripts/verify.sh
```

成功条件：服务状态正常，backend 的 `manage.py check` 通过，frontend 的 `nginx -t` 通过。

## 卸载

```bash
bash smart-resume-offline-deploy-skill/scripts/uninstall.sh
```

默认卸载只停止并删除容器、网络，保留 PostgreSQL 数据卷和上传文件卷。若选择删除数据卷或镜像，脚本会再显示“确认永久删除 / 返回并保留数据”菜单；未选择确认不会执行清理。
