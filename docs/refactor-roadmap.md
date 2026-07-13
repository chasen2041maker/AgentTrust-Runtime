# 重构路线图

本路线图记录架构演进的完成状态，而不是未来愿望清单。`v0.5.0` 已实现本地 Agent 执行控制的完整第一阶段。

## 已完成

### v0.1.1 安全默认值与工程门禁

- 安全 `shell` 使用 argv 与 `shell=False`，默认 effect 改为 `ask`；危险兼容模式使用明确名称。
- 未注册工具在权限阶段 fail closed。
- 文档、optional extras、Windows/Linux 与 Python 3.11-3.13 CI、Ruff、Mypy、coverage、CodeQL 和 wheel smoke 对齐。

### v0.2.0 Governed Session Runtime

- 领域层加入 session、tool call、approval 与生命周期状态机。
- 多调用 session 共享 run、身份、策略快照、facts 与 hash-linked evidence。
- JSONL evidence 加 SQLite 投影，支持 state rebuild。
- 审批持久化、参数摘要绑定、approve/deny、resume/cancel、超时和 final-answer 生命周期均已落地。

### v0.3.0 易用集成

- `govern()` 与 `@governed_tool` 可保护普通同步 Python 函数。
- OpenAI Agents、LangGraph、Pydantic AI adapters 重用外部 session。
- 每个集成都有无 API key 的 fake-model 测试与可运行 example。

### v0.4.0 真实 MCP Gateway

- stdio JSON-RPC transport、超时与协议错误的结构化结果。
- Claude Code、Codex、Cursor、VS Code 与项目配置的静态发现。
- consent、tool trust、command/schema fingerprint、drift invalidation 与 evidence 记录。

### v0.5.0 可观测性与安全基准

- JSONL evidence 到 OpenTelemetry/OTLP 的重建 exporter。
- `security-v1` 公开 100 例确定性安全基准，包含聚合误报、漏报与 latency 指标。

## 保持的架构规则

```text
domain        -> no adapter, CLI, YAML, filesystem, subprocess imports
application   -> domain + ports only
adapters      -> concrete side effects and external libraries
interfaces    -> compose adapters and expose CLI / Python API
```

下一阶段只在真实需求出现时扩展，例如更细的进程/网络 sandbox、更多稳定的 framework adapters 或 policy pack；不以 Dashboard、云服务或多语言 SDK 作为当前范围。
