# smart-resume-filter 离线部署

本目录是 `linux/amd64` 纯镜像离线包。优先使用随包附带的部署 Skill：

```bash
cp .env.example .env
# 修改 DJANGO_SECRET_KEY、DJANGO_ALLOWED_HOSTS、POSTGRES_PASSWORD、RESTIC_PASSWORD 和 BACKUP_TARGET_PATH
bash smart-resume-offline-deploy-skill/scripts/deploy.sh
```

人工部署的最短流程：

```bash
sha256sum -c SHA256SUMS
docker load -i smart-resume-filter-images-amd64.tar
cp .env.example .env
# 修改 .env 中的必填配置
docker compose --env-file .env --profile init run --rm init
docker compose --env-file .env up -d
```

启动后必须同时存在 `worker`（消费 `default`）、`ai-worker`（threads 池消费 `ai`）和 `backup-scheduler`（默认每小时备份）；AI 任务只有在两个 worker 都运行时才会被调度和执行。

验证：

```bash
bash smart-resume-offline-deploy-skill/scripts/verify.sh
```

停止服务但保留数据：

```bash
docker compose --env-file .env down
```

数据库和上传文件位于 Docker volumes。加密备份位于 `BACKUP_TARGET_PATH`；生产环境应把该目录放到异机挂载或外置磁盘。除非确认已有可恢复备份，不要删除 volumes。
