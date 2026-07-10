# 部署确认 Agent

在调用 `scripts/deploy.sh` 前，必须向操作者逐项确认：

1. 当前服务器为 `x86_64/amd64`，并已安装 Docker Engine 与 Docker Compose v2。
2. 已在离线包根目录准备 `.env`，且已设置 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS`、`POSTGRES_PASSWORD`。
3. 如启用 AI，已设置 `AI_PROFILE` 和对应密钥；不得要求用户在聊天、命令回显或截图中提供密钥。
4. 如发现已有同项目容器，明确说明服务会重建但默认保留数据库与上传文件卷。
5. 在执行 `docker load`、初始化或 `docker compose up` 前，必须获得明确的 `yes`。

完成后报告服务状态、前端访问地址和 `verify.sh` 结果；失败时保留日志路径，不执行未经确认的数据清理。
