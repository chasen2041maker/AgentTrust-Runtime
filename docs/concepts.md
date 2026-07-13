# 核心概念

## AgentSession

`AgentSession` 是一个完整 Agent 任务的边界。它包含 `run_id`、`actor_id`、可选 `agent_id`、`session_id`、`policy_version` 与生命周期状态。一个 session 内可连续调用多个工具，共享 evidence chain、fact ledger 和 policy snapshot。

## ToolIntent 与 SessionToolCall

`ToolIntent` 是进入治理路径的标准化请求：工具名、参数、来源、运行模式、run 与 tool call ID。`SessionToolCall` 额外保留递增 sequence、参数摘要和生命周期状态。参数摘要是审批恢复的防替换绑定。

## Policy、PermissionDecision 与 FinalPermission

策略规则首先给出 `allow`、`ask`、`deny` 的 `PermissionDecision`。运行模式再把它变为可执行 `FinalPermission`：

| 模式 | `ask` 的最终结果 |
| --- | --- |
| `interactive` | 暂停为 `waiting_approval`，等待批准或拒绝。 |
| `noninteractive` | `deny`，reason 为 `approval_required`。 |
| `test` | 确定性 mock approver 放行，便于测试。 |

没有匹配规则时，Tool Registry 的默认 effect 作为安全回退；没有注册的工具直接拒绝。

## ApprovalRequest

审批请求记录 `approval_id`、run/tool call、工具、`arguments_digest`、命中规则、原因、时间、决定与 approver。它可以在进程重启后由 `agenttrust approvals` 决定，随后使用 `agenttrust run resume` 恢复同一调用。

## Evidence 与 SQLite 投影

`trace.jsonl` 是 append-only、hash-linked evidence。`state.db` 仅提供可查询的 session、tool call 和 approval 投影。`agenttrust evidence verify` 验证链，`agenttrust state rebuild` 从有效 evidence 重新生成投影。

## Facts 与 FinalAnswerResult

工具成功后，显式 `AGENTTRUST_FACTS` block 与可靠 metadata 可映射为 `Fact`。`session.finalize_answer()` 只使用当前 session 的 facts 调用 GroundGuard，产生 `FinalAnswerResult` 和 `groundguard-report.json`。策略可在事实不完整时警告、拒绝完成或要求修订。

## MCP 信任面

MCP server 的 consent 与 tool trust 分开保存。真实 trust 保存 command hash、工具描述 hash 与输入 schema hash；后续发现任何漂移，状态变为 `trust_stale`。静态 `discover`/`inspect` 不启动 server。

## OTel 与 Security Regression Suite

OpenTelemetry exporter 只从 evidence 重建 span，不引入第二套运行事实。`security-v1` 将路径、秘密、shell、审批、MCP、篡改与事实控制编为 107 个确定性检查：100 个预期拦截攻击用例和 7 个预期允许基线。报告列出每例结果与误报/漏报指标。
