# 内网部署 Agent 指南

发布包：`__RELEASE_NAME__`，目标平台：`linux/amd64`。

1. 检查 `uname -m`、`docker --version` 和 `docker compose version`；仅在服务器为 `x86_64/amd64` 时继续。
2. 执行 `sha256sum -c SHA256SUMS`，任何失败都停止。
3. 首次运行 `smart-resume-offline-deploy-skill/scripts/deploy.sh`，选择创建 `.env`。脚本自动生成互不复用的 `DJANGO_SECRET_KEY`、`POSTGRES_PASSWORD` 和 `RESTIC_PASSWORD` 并设置 `600` 权限，任何密钥不得在对话或日志中输出。
4. 只要求管理员在 `.env` 补充实际 `DJANGO_ALLOWED_HOSTS`，并确认异机/外置存储已挂载到默认 `/mnt/smart-resume-filter-backups`；挂载点不同才修改 `BACKUP_TARGET_PATH`。再次运行部署脚本，并使用同目录 `verify.sh` 验证。
5. 升级时保留 `pgdata` 和 `media_data` volumes；未获得明确确认不得删除数据卷。
6. 完成后报告七个容器状态；确认 `worker` 消费 `default`、`ai-worker` 使用 threads 池消费 `ai`、`backup-scheduler` 正常运行，再报告后端检查、Nginx 检查和访问地址。

检测到旧容器或旧数据卷时不得替换密钥；原 `.env` 缺失应停止并走密钥恢复流程。
