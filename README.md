<div align="center">

# AgentTrust Runtime

**本地优先、会话感知的 Agent 执行控制层。**

在现有 Agent 框架与真实工具之间加入策略、可恢复审批、沙箱、可验证 evidence，以及 GroundGuard 最终答案核验。

[![CI](https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Version](https://img.shields.io/badge/version-0.5.0-green)
![License](https://img.shields.io/badge/license-MIT-green)

[快速开始](#快速开始) | [会话 API](#会话-api) | [MCP](#真实-mcp-网关) | [证据与可观测性](#证据与可观测性) | [安全基准](#安全基准) | [文档](#文档)

</div>

## 它解决什么问题

AgentTrust 不负责规划 Agent，也不替代模型或工作流框架。它只负责在 Agent 想调用工具时，回答并留下证据：

1. 这次调用是否被策略允许，是否需要人工批准？
2. 参数是否越过了文件、MCP 或恢复边界？
3. 这次调用属于哪个用户、Agent、会话和策略快照？
4. 程序重启后，等待批准的调用能否以原始参数安全恢复？
5. 最终答案是否引用了同一会话中记录的事实？

它把这些问题收拢为一个本地、可审计的闭环：

```text
Agent framework / custom loop
          -> AgentTrust Session
          -> policy -> approval -> sandbox -> tool
          -> JSONL evidence + SQLite state + facts
          -> GroundGuard final-answer check
          -> replay / restore / OpenTelemetry export
```

## 快速开始

```powershell
git clone https://github.com/chasen2041maker/AgentTrust-Runtime.git
cd AgentTrust-Runtime
python -m pip install -e ".[test]"
agenttrust init
python -m pytest
```

初始化后，运行一次确定性示例并校验证据链：

```powershell
agenttrust run-fixture verified_answer --mode test
agenttrust evidence verify <run_id>
agenttrust report <run_id> --format html
```

每个 run 都会在 `.agenttrust/runs/{run_id}/` 下保留 `trace.jsonl` 与 `policy-snapshot.yaml`。按执行路径还会生成：

```text
trace.jsonl             # 运行期 append-only、hash-linked evidence
facts.jsonl             # 有工具事实时生成的结构化账本
policy-snapshot.yaml    # 本次运行实际使用的策略
approvals.jsonl         # 有审批请求时生成
groundguard-report.json # 调用 finalize_answer() 后生成
report.md / report.html # 执行 agenttrust report 后生成
```

## 会话 API

一个 `AgentTrustSession` 让多次工具调用共享同一个 `run_id`、身份、策略快照、事实账本和证据链。

```python
from pathlib import Path

from agenttrust import AgentTrustRuntime

runtime = AgentTrustRuntime(Path("."), runtime_mode="interactive")

with runtime.session(actor_id="alice", agent_id="research-agent") as session:
    first = session.execute("read_file", {"path": "README.md"})
    second = session.execute("git_diff", {})
    lines = first.outcome.result.metadata["lines"]
    result = session.finalize_answer(
        f"README has {lines} lines [fact:read_file_lines].",
        required_fact_keys=["read_file_lines"],
    )
```

会话具有 `running`、`waiting_approval`、`completed`、`failed` 和 `cancelled` 等显式状态。工具调用需要批准时会暂停，而不是把整个 run 当作失败处理。

```powershell
agenttrust approvals list
agenttrust approvals inspect <approval_id>
agenttrust approvals approve <approval_id> --reason "reviewed"
agenttrust run resume <run_id>
agenttrust run cancel <run_id>
agenttrust state rebuild
```

审批请求绑定 `arguments_digest`。恢复前会先校验 hash chain、策略快照和原始参数摘要，防止“批准安全参数后再偷偷换参数”。

## 一行接入现有工具

普通同步 Python 函数可以直接被治理。默认效果必须显式声明，且函数参数必须可 JSON 序列化。

```python
from pathlib import Path

from agenttrust import AgentTrustRuntime, govern

def send_email(to: str, body: str) -> str:
    return f"sent to {to}"

runtime = AgentTrustRuntime(Path("."), runtime_mode="test")
with runtime.session(actor_id="alice") as session:
    safe_send_email = govern(send_email, session=session, default_effect="ask")
    print(safe_send_email("ops@example.com", "Deployment complete"))
```

也可使用 `@governed_tool(...)`。`ask` 在非交互模式默认收紧为 `deny`；`test` 模式使用确定性的 mock approver，专门服务于 CI。

## 框架集成

支持三个小而明确的集成包，并且它们重用调用方创建的 session，不会每次包裹工具时新建 run：

- `agenttrust.integrations.openai_agents`
- `agenttrust.integrations.langgraph`
- `agenttrust.integrations.pydantic_ai`

三个示例无需 API key 或框架安装即可运行，采用 fake-model 路径验证会话复用：

```powershell
python examples/openai_agents_sdk_adapter.py
python examples/langgraph_tool_adapter.py
python examples/pydantic_ai_adapter.py
```

需要原生框架对象时，分别安装独立 extra：`.[openai]`、`.[langgraph]` 或 `.[pydantic-ai]`。

## 真实 MCP 网关

AgentTrust 支持本地 stdio MCP，不把 config inspect 和 server 启动混为一谈：

```text
静态发现 -> inspect -> 显式 consent -> tools/list -> tool trust
-> command/schema fingerprint -> tools/call -> evidence
```

```powershell
agenttrust mcp discover
agenttrust mcp inspect <server-or-config>
agenttrust mcp consent grant <server>
agenttrust mcp trust <server> --tool read_file
agenttrust mcp consent revoke <server>
```

- `discover` 与 `inspect` 只读取配置，不启动 server，也不输出环境变量值。
- 真实调用前必须有 server consent 与 tool-level trust。
- 信任记录包含 command、description 和 input schema 的 hash；任一漂移都会把状态降为 `trust_stale`，后续调用被拒绝。
- stdio、超时和协议异常以结构化 `ToolResult` 和 evidence 记录，而非静默失败。

## 证据与可观测性

JSONL 是不可变 evidence 源，SQLite 是可查询的状态投影。即使 `state.db` 丢失，也可从已验证 trace 重建。

```powershell
agenttrust evidence verify <run_id>
agenttrust evidence export <run_id>
agenttrust state rebuild
```

安装 OTel extra 后，既有 evidence 可以重建为标准 span 并发送到任意 OTLP HTTP 后端：

```powershell
python -m pip install -e ".[otel]"
agenttrust evidence export-otel <run_id> --endpoint http://localhost:4318/v1/traces
```

span 层级为 `agenttrust.session -> agenttrust.tool -> policy / approval / sandbox / execute`，最终答案路径为 `agenttrust.final_answer -> agenttrust.groundguard`。项目不内置 Dashboard；Phoenix、Jaeger、Tempo、Langfuse 等 OTLP 后端是更合适的显示层。

## 安全基准

`security-v1` 是公开、确定性、可复现的 100 例攻击基准。运行时不会执行攻击 shell 命令，也不会启动用户配置的 MCP server；首个 MCP drift 用例只启动项目内置的 fake stdio server，以验证真实 fingerprint 路径。

```powershell
agenttrust benchmark security --output benchmark-report.json
```

报告包含逐例 ID、期望与实际拦截结果，以及：

- `cases_total`、`expected_blocks`、`detected_blocks`
- `false_positives`、`false_negatives`、`critical_bypasses`
- `median_policy_latency_ms`

数据集覆盖 20 个路径逃逸、10 个秘密访问、20 个 shell 注入、15 个审批绕过、15 个 MCP trust/drift、10 个恢复篡改和 10 个事实矛盾攻击样例，并附带 7 个预期允许的基线，以测量误报。完整说明见 [安全基准](benchmarks/README.md)。

## 安全默认值

- 未注册工具在权限阶段 fail closed。
- `shell` 默认 `ask`，安全执行只接受 `argv` 并使用 `shell=False`；兼容危险模式必须明确使用 `unsafe_shell_command`。
- `PathSandbox` 限制读写在 `project_root` 内，阻断 `.env`、PEM、SSH 和系统路径。
- `ask` 在 noninteractive 模式变成 `deny`；审批记录不等于自动批准。
- 本地 artifact 可能包含路径、工具输出和业务事实，分享前必须脱敏。

## 不做什么

AgentTrust 有意保持窄而硬的边界：不做 Agent 编排框架、Web Dashboard、云端 policy server、用户/组织系统、多语言 SDK、远程 memory service、skill marketplace 或完整 SIEM。它的价值在于让现有 Agent 的工具执行更可控、更可恢复、更能证明发生过什么。

## 文档

- [入门](docs/getting-started.md)
- [CLI 参考](docs/cli.md)
- [核心概念](docs/concepts.md)
- [运行时架构](docs/ARCHITECTURE.md)
- [威胁模型](docs/THREAT_MODEL.md)
- [相关工作与边界](docs/RELATED_WORK.md)
- [架构演进方案](docs/enterprise-architecture.md)
- [重构路线图](docs/refactor-roadmap.md)
- [变更记录](CHANGELOG.md)
- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)

## License

MIT License.
