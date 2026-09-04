# Smart Resume Agent Kernel

`agent-kernel` 是简历系统的独立智能执行内核。它接收 Django 生成并钉死版本的
`CaseEnvelopeV1`，在白名单只读工具中运行有轮次、调用次数和总时长上限的模型循环，
最后返回不具备业务写权限的 `AgentActionProposalV1`。

边界约束：

- 不连接业务数据库，不接收候选人、简历、岗位或部门的数据库 ID。
- 不提供分配、归档、通知、命令执行、文件写入或任意 HTTP 工具。
- 模型只能读取信封中的当前志愿、固定岗位上下文和简历文本。
- 最终证据必须能在简历原文中复核；Django Policy Gate 仍会进行第二次校验。
- 模型 API Key 只通过单次请求头传入，不写入信封、日志或 Kernel 持久化状态。

## 本地验证

```bash
go test ./...
go vet ./...
go build -trimpath -o /tmp/smart-resume-agent-kernel ./cmd/agent-kernel
```

## 运行

```bash
AGENT_KERNEL_TOKEN='replace-with-a-random-token' \
AGENT_KERNEL_ADDRESS=':8090' \
/tmp/smart-resume-agent-kernel
```

健康检查为 `GET /healthz`。评估入口为 `POST /v1/evaluate`，必须携带
`X-Agent-Kernel-Token`；模型需要鉴权时由 Django 额外携带
`X-Model-API-Key`。生产部署由根目录 `docker-compose.yml` 启动并进行版本健康检查。
