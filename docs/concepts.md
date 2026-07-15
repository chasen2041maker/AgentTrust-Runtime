# 核心概念

## AgentSession 与 SessionToolCall

`AgentSession` 是一个完整 Agent 任务的边界，包含 `run_id`、actor/agent/session 身份、策略快照摘要和生命周期状态。`SessionToolCall` 记录同一 session 内的递增调用序号、工具、参数摘要和状态。

`waiting_approval` 表示 session 中至少有一个调用等待审批，而不是冻结整个 session。可以继续提交其他工具调用并同时得到多个审批请求；恢复时使用 `tool_call_id` 精确选择目标调用。

## Policy Protocol v1

`DecisionRequest` 是策略求值的可移植输入：

- `principal`：actor、agent 和角色。
- `action`：调用类型、工具与风险等级。
- `resource`：主要资源标识和分类。
- `context`：session、运行模式和 sandbox profile。
- `arguments_digest`：原始参数的稳定摘要。
- `attributes`：内置 YAML matcher 所需的最小可见属性，例如 path、command、argv、server 和 tool。

`DecisionResponse` 返回 `allow`、`ask` 或 `deny`，并携带命中规则、最终规则 ID 和 obligations。内置优先级是 `policy deny > registry deny > policy ask > policy allow > tool default`；未注册工具和注册表硬拒绝不能被策略 allow 提升。

`agenttrust.policy-pack/v1` 是 policy v1 的离线交换格式。导出时会先把 YAML 归一化为运行时实际执行的字段组合，再对规范 JSON 计算 digest；导入会重新解析、拒绝未知字段和语义不一致的 payload，并默认拒绝覆盖项目 YAML。该 digest 用于完整性与可复现性，不是作者签名或远程 trust root。

## 审批

`ApprovalRequest` 绑定 `approval_id`、run/tool call、脱敏参数预览、`arguments_digest`、规则、原因、TTL 与决定信息。批准或拒绝都写入 evidence；恢复前会重放已验证 trace，而不会信任可变 SQLite 缓存。

## Evidence v1 与 SQLite

`trace.jsonl` 是 append-only、hash-linked evidence。v1 事件包含 `schema_version`、`event_id`、`event_sequence`、`subject` 和 `payload`，同时保留兼容的扁平字段；已验证读取会将 v0.5 事件迁移为同一内存形态。

`trace-head.json` 保存已验证 head、文件大小和修改时间。正常 append 只检查检查点与尾事件，避免随 trace 长度增长而重复扫描；检查点缺失或陈旧时会完整验证 hash chain。`state.db` 是查询投影：新事件增量投影，恢复/审批只重建当前 run，`agenttrust state rebuild` 才重建全部 run。

安装 `.[signing]` 后，`agenttrust evidence anchor` 可以用 Ed25519 为已验证的 `run_id`、事件数、head hash、签名时间和公钥指纹生成 `trace-anchor.json`。验证方应通过独立可信渠道固定公钥并传入 `verify-anchor --public-key`；内附公钥只能证明签名在数学上自洽，不能单独证明签名者身份。anchor 会在 trace 后续变化时失效，但不等同于可信时间戳、外部见证或不可变存储。

## 同步与异步 API

- 同步：`runtime.session()`、`session.execute()`、`govern()`、`@governed_tool`。
- 异步：`runtime.async_session()`、`session.execute_async()`、`await runtime.async_resume()`、`govern_async()`、`@governed_async_tool`。

异步自定义工具通过 `AsyncToolExecutorPort` 被直接 await。内建同步工具仍可在 async gateway 兼容路径中使用，因此策略、审批、沙箱和 evidence 语义在两种 API 中保持一致。

## Facts 与最终答案

工具结果可以映射为带来源和信任等级的 `Fact`。`finalize_answer()` 将最终答案与本 session 中的 facts 对照；调用 GroundGuard 时会传入同一个 `run_id` 作为 `FactGate(session_id=...)`，并把该 session ID 写入 `groundguard-report.json` 与 `groundguard_check` evidence。`verification.mode: groundguard_required` 会在 GroundGuard 不可用或无效时明确拒绝降级；默认 `fallback` 模式保留内置确定性检查。

## MCP 信任面

MCP server 的 consent 与逐工具 trust 分开保存。真实 trust 绑定 command、描述和输入 schema fingerprint；发现漂移后状态变为 `trust_stale`，后续调用被阻断。真实 stdio 进程使用最小 OS 运行时环境白名单，加上配置中显式声明的 `env`，并以 config 目录为工作目录启动、关闭继承句柄；trace/OTel 只保存该模式和变量数量，不保存值。sandbox profile 目前仍是策略元数据，不是操作系统级网络或进程隔离。
