# 运行时架构

AgentTrust Runtime 是一个 ports-and-adapters 风格的本地执行控制层。它不编排 Agent；外部框架、CLI 或自定义循环把工具请求交给它后，运行时负责策略、审批、沙箱、证据、恢复与最终答案核验。

## 控制路径

```mermaid
flowchart LR
    A["Framework / CLI / Python API"] --> B["AgentTrustSession"]
    B --> C["ToolIntent"]
    C --> D["Policy + Tool Registry"]
    D --> E["Approval State"]
    E --> F["Hook + Path Sandbox"]
    F --> G["Tool Gateway"]
    G --> H["ToolResult + Facts"]
    H --> I["JSONL Evidence"]
    I --> J["SQLite Projection"]
    H --> K["GroundGuard Final Answer"]
    I --> L["OTel Export"]
```

一个 session 的每次工具调用都带相同的 `run_id`、`actor_id`、`agent_id`、`session_id` 和 `policy_version`。`tool_call_id` 单调递增，避免把多个 Agent 任务混入同一审计单元。

## 生命周期

```text
created -> running -> completed
                  -> failed
                  -> cancelled
                  -> waiting_approval -> running
```

工具调用状态是 `requested`、`policy_denied`、`waiting_approval`、`approved`、`sandbox_denied`、`executing`、`succeeded` 或 `failed`。领域状态转换在 `domain/lifecycle.py` 内校验，不允许接口层任意改写。

## 分层与依赖规则

```text
domain/        纯模型、策略、状态机、审批摘要；只依赖标准库和 domain
application/   use case 与 port；依赖 domain，不导入具体 adapter
adapters/      YAML、JSONL、SQLite、文件、shell、MCP、GroundGuard、OTel
interfaces/    CLI 与 Python SDK，负责组合并调用 application
integrations/  OpenAI Agents、LangGraph、Pydantic AI 的 session 复用包装
benchmark/     公开的确定性安全控制回归数据集
```

兼容模块保留旧 import 路径，但真正的实现位于边缘 adapter。架构边界测试确保 domain 不依赖 CLI、YAML、文件系统或 subprocess，application 不直接导入具体 adapter。

## 存储模型

```text
.agenttrust/
  policy.yaml
  state.db
  mcp-consent.json
  mcp-trust.json
  runs/{run_id}/
    trace.jsonl
    facts.jsonl
    approvals.jsonl
    policy-snapshot.yaml
    groundguard-report.json
    backups/
```

- `trace.jsonl` 是 append-only evidence 源。每个事件包含上一事件 hash 与自身 hash。
- `state.db` 是 session、tool call 和 approval 的查询投影，不是信任根。
- `agenttrust state rebuild` 会先验证 trace，再从 JSONL 重建 SQLite。
- policy snapshot 与 identity 被绑定到每个 evidence event；恢复不使用后来修改过的项目 policy。

## 策略、审批和沙箱

策略返回 `allow`、`ask` 或 `deny`。未匹配规则时静态 Tool Registry 提供默认效果；没有注册的工具直接返回 `unregistered_tool`。`ask` 的最终效果取决于运行模式：interactive 等待决定、noninteractive 拒绝、test 由确定性 mock approver 放行。

`PathSandbox` 将文件工具限制在 project root 内，拒绝系统路径、`.env`、PEM 与 SSH 路径。对写入，它先解析父目录再计算目标，降低新路径和符号链接逃逸的风险。恢复同时约束目标路径与 backup 路径。

## MCP 边界

真实 stdio MCP 的执行顺序是：静态发现、inspect、consent、`tools/list`、tool trust、fingerprint 校验、`tools/call`。command hash、工具 description hash 和 input schema hash 都进入信任记录；漂移使记录失效，调用被拒绝并写入 evidence。

## 最终答案与可观测性

工具结果经 mapper 形成显式 facts；`finalize_answer()` 将答案与同一 session 的 facts 交给 GroundGuard。证据 export 不创建第二个事实源：OTel adapter 从 JSONL 重建 `agenttrust.session`、工具阶段和最终答案 span，供 OTLP 后端消费。
