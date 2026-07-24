# 简历宝离线部署

本目录是 `linux/amd64` 纯镜像离线包。优先使用随包附带的部署 Skill：

```bash
bash smart-resume-offline-deploy-skill/scripts/deploy.sh
```

首次运行选择“创建 `.env`、自动生成密钥并退出”。脚本会固定使用包内已确定的镜像、端口、并发、OCR、数据库标识、备份周期与保留策略，并自动生成 `DJANGO_SECRET_KEY`、`POSTGRES_PASSWORD` 和 `RESTIC_PASSWORD`。部署人员只需：

1. 把生产域名写入 `DJANGO_ALLOWED_HOSTS`，配置 DNS、可信 TLS 证书和 HTTPS 反向代理或企业网关；所有路径统一转发到 frontend 暴露端口，不直接暴露 backend `8000`。同机反代建议将 `FRONTEND_BIND` 改为 `127.0.0.1`。
2. 确保异机/外置存储已挂载到 `/mnt/smart-resume-filter-backups`；现场路径不同时修改 `BACKUP_TARGET_PATH`。
3. 再次执行同一条部署命令。

前端只提供 W3 登录，因此 W3 OAuth2 是可用部署的必要条件。模板中的 `W3_OAUTH2_ENABLED=False` 只用于首次安全生成 `.env`；正式部署前须通过安全渠道改为 `True`，填写 client id、authorize/token/userinfo HTTPS 地址、精确 redirect URI、工号/邮箱字段路径、客户端认证方式、超时和事务有效期。`W3_OAUTH2_REDIRECT_URI` 必须与反向代理的 HTTPS 域名完全一致，例如 `https://resume.example.com/api/auth/w3/callback/`。当前 UserInfo 顶层字段映射已预填为 `W3_OAUTH2_EMPLOYEE_NO_FIELD=employeeNumber`、`W3_OAUTH2_EMAIL_FIELD=email`；`tenantId`、`uuid`、`globalUserID` 当前不参与账号匹配。机密客户端还必须填写 client secret，scope 按 W3 要求填写。部署脚本会在任何 Docker 变更前校验，W3 关闭或配置不完整都会停止。本地密码 API 默认关闭且无前端入口，仅允许在明确的应急场景临时开启。

离线部署的最短流程仍必须经过部署 Skill，不允许用 `docker compose init/up` 绕过 W3、域名、备份路径和已有数据保护校验：

```bash
sha256sum -c SHA256SUMS
bash smart-resume-offline-deploy-skill/scripts/deploy.sh
```

首次执行只创建 `.env` 和三项随机密钥后退出；补齐生产域名、反向代理、W3 和备份路径配置后，再次执行同一条部署命令完成镜像导入、初始化和启动。

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
