# 内网部署 Agent 指南

发布包：`__RELEASE_NAME__`，目标平台：`linux/amd64`。

1. 检查 `uname -m`、`docker --version` 和 `docker compose version`；仅在服务器为 `x86_64/amd64` 时继续。
2. 执行 `sha256sum -c SHA256SUMS`，任何失败都停止。
3. 复制 `.env.example` 为 `.env`，要求管理员填写 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS`、`POSTGRES_PASSWORD`、独立的 `RESTIC_PASSWORD`，并把 `BACKUP_TARGET_PATH` 指向异机挂载或外置磁盘；不得在对话或日志中输出密钥。
4. 使用 `smart-resume-offline-deploy-skill/scripts/deploy.sh` 部署，使用同目录 `verify.sh` 验证。
5. 升级时保留 `pgdata` 和 `media_data` volumes；未获得明确确认不得删除数据卷。
6. 完成后报告七个容器状态；确认 `worker` 消费 `default`、`ai-worker` 使用 threads 池消费 `ai`、`backup-scheduler` 正常运行，再报告后端检查、Nginx 检查和访问地址。
