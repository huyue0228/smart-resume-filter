# 简历宝离线部署

本目录是 `linux/amd64` 纯镜像离线包。优先使用随包附带的部署 Skill：

```bash
bash smart-resume-offline-deploy-skill/scripts/deploy.sh
```

首次运行选择“创建 `.env`、自动生成密钥并退出”。脚本会固定使用包内已确定的镜像、端口、并发、OCR、数据库标识、备份周期与保留策略，并自动生成 `DJANGO_SECRET_KEY`、`POSTGRES_PASSWORD` 和 `RESTIC_PASSWORD`。部署人员只需：

1. 把服务器实际 IP/域名写入 `DJANGO_ALLOWED_HOSTS`。
2. 确保异机/外置存储已挂载到 `/mnt/smart-resume-filter-backups`；现场路径不同时修改 `BACKUP_TARGET_PATH`。
3. 再次执行同一条部署命令。

人工部署的最短流程：

```bash
sha256sum -c SHA256SUMS
docker load -i smart-resume-filter-images-amd64.tar
# 建议先运行一次部署脚本，让它安全创建 .env 并生成三项密钥；不要直接使用模板占位值。
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

数据库和上传文件位于 Docker volumes。加密备份位于 `BACKUP_TARGET_PATH`；脚本会拒绝不存在、不可写或非绝对路径的备份目录。除非确认已有可恢复备份，不要删除 volumes。升级和灾后恢复必须保留原 `.env`，脚本不会为已有容器/数据卷重新生成密钥。
