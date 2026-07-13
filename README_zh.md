<p align="center">
  <img src="docs/assets/agenttrust-mark.svg" width="104" alt="AgentTrust Runtime 标识" />
</p>

<h1 align="center">AgentTrust Runtime</h1>

<p align="center">
  <strong>为 AI Agent 的每一次工具调用增加策略、审批、恢复和可验证证据。</strong>
</p>

<p align="center">
  不替换 OpenAI Agents、LangGraph、Pydantic AI、MCP 或自研 Python Agent；只在它们与真实工具之间加入本地、fail-closed 的执行控制。
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="docs/index.md">文档</a> | <a href="CHANGELOG.md">变更记录</a> | <a href="SECURITY.md">安全策略</a> | <a href="docs/refactor-roadmap.md">路线图</a>
</p>

<p align="center">
  <a href="https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml"><img src="https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB" alt="Python 3.11 或更新版本" />
  <img src="https://img.shields.io/badge/status-beta-F59E0B" alt="Beta 状态" />
  <img src="https://img.shields.io/badge/license-MIT-0F766E" alt="MIT 许可证" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Policy-fail--closed-C2410C" alt="Fail-closed 策略" />
  <img src="https://img.shields.io/badge/Approvals-resumable-0369A1" alt="可恢复审批" />
  <img src="https://img.shields.io/badge/Evidence-hash--linked-7C3AED" alt="Hash 链证据" />
  <img src="https://img.shields.io/badge/Recovery-governed%20writes-0F766E" alt="受控写入恢复" />
  <img src="https://img.shields.io/badge/MCP-stdio%20%2B%20drift-D97706" alt="MCP stdio 与漂移检查" />
</p>

![AgentTrust Runtime 控制流程](docs/assets/runtime-flow.svg)

> **v0.6.0 Beta / 开发者预览**：适合本地开发、集成验证和确定性控制回归。它不是生产安全保证；连接真实系统前仍需完成权限审查、独立威胁建模和环境级防护。

## AgentTrust 是什么？

Agent 框架负责决定“想做什么”；AgentTrust 负责当这个决定真正到达工具时，控制“会发生什么”。

每次工具调用都会回答并留下证据：

1. 这次调用应当允许、拒绝，还是等待人工审批？
2. 文件路径、命令参数、MCP 信任状态和恢复边界是否通过控制检查？
3. 是哪个 actor、会话、策略快照和参数产生了结果？
4. 进程重启后，已审批调用能否带着原始参数安全恢复？
5. 最终答案是否引用了同一会话记录的事实？

它刻意保持为控制层，不是 Agent 规划器、模型提供方、工作流引擎、Dashboard 或云端策略服务。

## 30 秒验证

当前 beta 尚未发布到 PyPI。可以直接从本仓库安装，然后运行一个确定性会话，生成 evidence、facts、GroundGuard 报告和 HTML 报告。

```powershell
python -m pip install "agenttrust-runtime @ git+https://github.com/chasen2041maker/AgentTrust-Runtime.git"
mkdir agenttrust-demo
cd agenttrust-demo
agenttrust init
agenttrust run-fixture verified_answer --mode test
agenttrust evidence verify <run_id>
agenttrust report <run_id> --format html
```

Evidence 校验的预期输出：

```text
{
  "valid": true,
  "event_count": 11,
  "head_hash": "sha256:..."
}
```

每个 run 会保留实际执行路径产生的 artifact：

```text
trace.jsonl             # 本地、append-oriented、hash-linked 的事件源
trace-head.json          # 已验证 trace 头部的追加检查点
policy-snapshot.yaml    # 本次运行实际使用的策略文本
facts.jsonl             # 有工具事实时生成的结构化账本
groundguard-report.json # 调用 finalize_answer() 后生成的核验结果
report.md / report.html # 从已验证时间线生成的报告
```

`trace.jsonl` 可以检测 hash chain 内的改动；它不是外部签名、不可变存储，也不提供不可抵赖性。

## 第一个受控会话

在已有 Agent loop 中使用 Python API。这个例子会让一次代码写入等待审批，而不是立即执行。

```python
from pathlib import Path

from agenttrust import AgentTrustRuntime

runtime = AgentTrustRuntime(Path("."), runtime_mode="interactive", approval_mode="deferred")

with runtime.session(actor_id="alice", agent_id="coding-agent") as session:
    outcome = session.execute(
        "write_file",
        {"path": "src/report.py", "content": "print('hello')\n"},
    )

    if outcome.approval_request:
        print("Approval required:", outcome.approval_request.approval_id)
        print("Evidence:", session.run_dir / "trace.jsonl")
```

审批后以仍绑定到审批记录的参数摘要恢复同一调用：

```powershell
agenttrust approvals list
agenttrust approvals inspect <approval_id>
agenttrust approvals approve <approval_id> --reason "reviewed"
agenttrust run resume <run_id>
```

## V0.6：策略协议与异步运行时

v0.6 保持现有 YAML 策略格式，同时提供可移植的 `DecisionRequest`、`DecisionResponse` 与 `Obligation` 协议对象。`policy explain` 会展示所有命中规则、工具默认值和最终优先级；`lint` 与 `test` 可以直接放入 CI。

```powershell
agenttrust policy lint .agenttrust/policy.yaml
agenttrust policy test .agenttrust/policy.yaml policy-fixtures.json
agenttrust policy explain .agenttrust/policy.yaml --tool write_file --path src/report.py
```

宿主框架已经使用事件循环时，可以使用异步会话。原生 async 工具会被直接 `await`，内建同步工具仍由网关兼容层提供。

```python
from agenttrust import AgentTrustRuntime, govern_async

runtime = AgentTrustRuntime(Path("."), runtime_mode="test")

async with runtime.async_session(actor_id="alice") as session:
    async def summarize(text: str) -> str:
        return text.upper()

    governed_summarize = govern_async(
        summarize, session=session, tool_name="summarize", default_effect="allow"
    )
    assert await governed_summarize("ready") == "READY"
```

一个 session 可以同时保存多个待审批调用。审批后，存在多个候选调用时用 `tool_call_id` 精确恢复：

```powershell
agenttrust run resume <run_id> --tool-call-id call_002
```

开发安装和测试命令见 [贡献指南](CONTRIBUTING.md)。

## 为什么需要 AgentTrust？

| 能力 | Prompt Guardrail | 可观测性 | Sandbox | AgentTrust |
| --- | --- | --- | --- | --- |
| 工具执行前策略 | 有限 | 否 | 有时 | 是 |
| 人工审批 | 有限 | 否 | 否 | 可恢复 |
| 路径和工具控制 | 否 | 否 | 是 | 是 |
| Evidence | 否 | 仅 trace | 否 | Hash-linked 本地 JSONL |
| 恢复受控写入 | 否 | 否 | 依赖快照 | 已验证 run artifact |
| 最终答案事实核验 | 否 | 否 | 否 | GroundGuard 支持 |
| 替换 Agent 框架 | 否 | 否 | 否 | 否 |

这个表格只描述能力范围，不表示任何单一类别能覆盖全部部署风险。

## 核心能力

| Policy Gate | 可恢复审批 | 路径与工具控制 |
| --- | --- | --- |
| 每个调用都会得到 `allow`、`ask` 或 `deny`；未知工具 fail closed。[核心概念](docs/concepts.md) | 暂停会话，稍后决策，再从已验证 evidence 恢复原始参数。[CLI](docs/cli.md) | 治理本地文件、安全 shell argv、MCP 调用和自定义 Python 函数。[架构](docs/ARCHITECTURE.md) |

| Evidence 与 replay | 可恢复写入 | 最终答案核验 |
| --- | --- | --- |
| 写入本地 hash-linked trace，重建 SQLite 投影并导出 span。[Evidence](docs/concepts.md) | 为受控文件写入保存备份，并从已验证 trace 恢复。[恢复](docs/cli.md) | 用同一会话中的 facts 检查答案中的关键声明。[GroundGuard](docs/concepts.md) |

## 工作方式

1. 将框架回调、MCP 请求或自定义函数归一化为 `ToolIntent`。
2. 执行策略与已注册工具默认值；未知工具 fail closed。
3. 检查文件路径、安全 shell `argv`，或 MCP 的 consent、trust 与 command/schema fingerprint。
4. 当策略结果为 `ask` 时持久化审批请求；否则执行受控工具。
5. 追加生命周期事件、映射 facts，并将可查询状态投影到 SQLite。
6. 从已验证 evidence replay，用于恢复、报告、OpenTelemetry 导出和最终答案核验。

SQLite 是可重建的查询投影，而不是恢复 run 时的证据源。

## 集成

AgentTrust 重用调用方创建的 session，不会为每个被包装的工具创建新 run。

| 集成 | 入口 | 可运行示例 |
| --- | --- | --- |
| OpenAI Agents SDK | `agenttrust.integrations.openai_agents` | `python examples/openai_agents_sdk_adapter.py` |
| LangGraph | `agenttrust.integrations.langgraph` | `python examples/langgraph_tool_adapter.py` |
| Pydantic AI | `agenttrust.integrations.pydantic_ai` | `python examples/pydantic_ai_adapter.py` |
| 自定义 Python | `govern()` / `@governed_tool(...)` | [会话 API](#第一个受控会话) |

示例使用 fake-model 路径，不需要 API key。仅在接入原生对象时安装对应 extra：`.[openai]`、`.[langgraph]`、`.[pydantic-ai]`。

## 本地 MCP stdio 治理

AgentTrust 明确区分“读取 MCP 配置”和“启动 MCP server”：

```text
静态发现 -> inspect -> 显式 consent -> tools/list -> tool trust
-> command 与 schema fingerprint -> tools/call -> evidence
```

```powershell
agenttrust mcp discover
agenttrust mcp inspect <server-or-config>
agenttrust mcp consent grant <server>
agenttrust mcp trust <server> --tool read_file
```

- `discover` 和 `inspect` 不启动 server，也不输出环境变量值。
- 真实调用需要 server consent 和 tool-level trust。
- command、description 或 input schema 漂移会使 trust 失效，后续调用被阻断。
- 模拟调用只在 test 模式或运行时显式开启模拟能力时允许；其事实会标为 `test_only`，不能用于验证普通模式的最终答案。
- 当前 sandbox profile 是策略元数据，**不是**操作系统级进程或网络隔离。

## Evidence、恢复与报告

![Evidence 报告示例](docs/assets/evidence-report-preview.svg)

Evidence 事件是带前序 hash 的 append-oriented JSONL 记录。新的 v1 事件带有可移植 envelope，读取已验证的 v0.5 trace 时会在内存中完成兼容迁移。`trace-head.json` 让正常追加不随历史事件数线性变慢；检查点缺失或陈旧时会回退到完整验证。`agenttrust evidence verify` 会在 replay、restore 或 OpenTelemetry 导出前验证 trace；`agenttrust state rebuild` 可从已验证 trace 重建本地 SQLite 投影。

对受控的 `write_file`，运行时只会在写入成功后记录恢复点，并绑定实际写后 digest。恢复默认只预览；目标文件在运行后被修改时会跳过，除非显式使用 `--force`。

```powershell
agenttrust evidence verify <run_id>
agenttrust evidence export <run_id>
agenttrust state rebuild
agenttrust restore <run_id>
agenttrust restore <run_id> --apply
agenttrust report <run_id> --format html
```

安装 `.[otel]` 后，可以把 evidence 重建为 OTLP HTTP span，发送到 Phoenix、Jaeger、Tempo 或 Langfuse 等后端。项目本身不提供 Dashboard。

## 最终答案核验

`finalize_answer()` 会记录最终答案，并把要求的 fact key 与当前会话产出的 facts 对照。这在工具结果与答案声明之间提供可检查的关联，但不证明任意模型输出的完整性或真实性。

可在策略中设置 `verification.mode: groundguard_required`，让缺失或无效的 GroundGuard 输出明确成为未验证结果。默认 `fallback` 模式保留适用于本地开发的内置确定性核验器。

```python
result = session.finalize_answer(
    "Revenue was $3.83 billion [fact:revenue].",
    required_fact_keys=["revenue"],
)
assert result.status == "verified"
```

## Security Regression Suite

`security-v1` 是公开、确定性的控制回归套件，不是渗透测试，也不是“覆盖全部 Agent 攻击”的声明。它不会运行传入的 shell 命令或用户配置的 MCP server；第一个 drift 用例只会启动项目内置的 fake stdio server。

```powershell
agenttrust benchmark security --output benchmark-report.json
```

在 v0.5.1 代码上的一次执行结果为：

```text
107 个确定性检查
100 个预期拦截 / 100 个实际拦截
7 个预期允许的安全基线
0 false positives / 0 false negatives / 0 critical bypasses
```

JSON 报告包含 case ID、预期与实际结果、类别计数和 policy latency。请用上方命令复现；性能取决于 Python 与操作系统环境。用例定义和边界见[基准说明](benchmarks/README.md)。

## 适用场景

**Coding Agents**：在源码写入或 shell 执行前要求审查，并保留恢复 artifact。

**本地 MCP Clients**：对本地 MCP server 做显式 consent、逐工具 trust 和 schema drift 检查。

**Research 与 Data Agents**：保留工具产生的 facts，并核验最终报告中的声明。

**受监管或需审计的流程**：让 actor、session、policy、approval、tool result 和 final-answer evidence 保持在同一个 run 中。

## 项目状态与限制

**状态：Beta。** 运行时已具备面向生产的本地控制形态，但仍是开发者预览。

当前可用：

- 会话级执行、持久化审批记录，以及从已验证本地 evidence replay。
- 本地 MCP stdio 的 consent、tool trust 和 drift 检查。
- 版本化策略与 evidence 协议、异步会话执行、hash-linked evidence、SQLite 投影重建、报告生成和 OTLP 导出。
- GroundGuard 支持的最终答案必需事实检查。

已知限制：

- 本地 evidence 没有外部签名、可信时间戳或不可变存储锚点。
- 同一 run 的 evidence 和状态转换使用跨平台运行锁；外部签名和不可变存储仍不属于本地运行时的边界。
- `govern()` 包装的自定义函数需要在重启后再次注册，才能恢复执行。
- 审批请求默认 TTL 为一小时，可通过 `approvals.default_ttl_seconds` 或 session override 配置。
- MCP sandbox profile 尚未实现 OS 级进程或网络隔离。
- 文件恢复不是通用事务或回滚机制。

## 路线图

下一阶段会聚焦外部 evidence anchoring、OS 级 MCP 隔离，以及更广泛的 policy pack 互操作性。完整的实施历史和计划边界见[重构路线图](docs/refactor-roadmap.md)与[企业架构方案](docs/enterprise-architecture.md)。

## 文档

- [快速入门](docs/getting-started.md)
- [CLI 参考](docs/cli.md)
- [核心概念](docs/concepts.md)
- [协议与异步运行时](docs/protocols.md)
- [运行时架构](docs/ARCHITECTURE.md)
- [威胁模型](docs/THREAT_MODEL.md)
- [相关工作与边界](docs/RELATED_WORK.md)
- [安全基准](benchmarks/README.md)
- [变更记录](CHANGELOG.md)
- [安全策略](SECURITY.md)

## 社区与贡献

欢迎能增强确定性运行时控制的贡献。请从[贡献指南](CONTRIBUTING.md)开始；带着最小复现提出 issue；潜在安全问题请按照[安全策略](SECURITY.md)私下报告。

## License

[MIT](LICENSE)
