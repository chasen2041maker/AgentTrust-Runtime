<div align="center">

<h1>AgentTrust Runtime</h1>

**面向本地 AI Agent 的工具执行治理层：权限、沙箱、trace、恢复，以及 GroundGuard 事实门禁。**

把每一次 Agent 工具调用变成可审计的 `ToolIntent`，在执行前经过权限判断和路径沙箱；执行后记录 append-only trace、结构化 facts、恢复备份，并用 GroundGuard 校验最终回答是否真的引用了工具已经拿到的事实。

[![CI](https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/chasen2041maker/AgentTrust-Runtime/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-local--first--runtime-orange)

[快速开始](#快速开始) | [核心概念](#核心概念) | [CLI](#cli) | [架构](docs/ARCHITECTURE.md) | [威胁模型](docs/THREAT_MODEL.md) | [最终实施方案](AgentTrust-Runtime-%E6%9C%80%E7%BB%88%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md)

</div>

**当前验证信号：** 核心 runtime、MCP Lite、Skill Lite、Recovery Lite、Hook Lite、Memory/Context Lite 均已接入 pytest 覆盖；本地完整测试为 `36 passed, 1 skipped`。

```bash
python -m pip install -e ".[test]"
agenttrust init
agenttrust run-fixture mcp_tool_approved --mode test
agenttrust report <run_id> --format html
```

这个 run 会证明一件事：MCP wrapper 工具默认需要批准，test mode 里的 mock approver 放行后，工具结果会被映射为结构化 fact，并进入 GroundGuard 覆盖报告。

## 为什么需要 AgentTrust Runtime

工具型 Agent 的危险点经常不是“程序崩了”，而是它做了看似合理、实际越界的动作：

- Agent 试图读 `.env`、PEM、SSH key，或者通过大小写/路径变体绕过 secret 规则。
- Agent 在 noninteractive 模式下想写源码文件，但没有用户批准。
- Agent 调用 MCP tool 时，绕过了 runtime 的权限、trace 和事实记录。
- Agent 写坏了本地文件，却没有可恢复的 run artifact。
- 工具已经返回了关键事实，最终回答却改写、遗漏或编造了数字。

GroundGuard 解决的是“最终回答是否被工具事实支持”。AgentTrust Runtime 站在更前面：它治理工具调用本身，然后把工具结果送进 GroundGuard 做最终事实门禁。

换句话说：

1. Agent 想做事，先生成 `ToolIntent`。
2. Runtime 判断权限、hook、skill scope 和路径沙箱。
3. 允许执行的工具会产生 `ToolResult`、trace、facts、backup。
4. 最终回答必须引用这些 facts，GroundGuard 才能验证通过。
5. replay/report/restore 可以复盘和恢复这次 run。

## 快速开始

```bash
git clone https://github.com/chasen2041maker/AgentTrust-Runtime.git
cd AgentTrust-Runtime
python -m pip install -e ".[test]"
agenttrust init
python -m pytest
```

初始化后会生成：

```text
.agenttrust/
  policy.yaml
  runs/
  skills/code-review/
```

10 秒 demo：

```bash
agenttrust run-fixture verified_answer
agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format html
```

典型输出路径：

```text
.agenttrust/runs/{run_id}/
  trace.jsonl
  decisions.json
  facts.jsonl
  final-answer.md
  groundguard-report.json
  report.md
  report.html
```

## 当前能力

- `ToolIntent` / `ToolResult` schema：所有输入源都先规范化成同一种工具调用协议。
- Permission Engine：支持 `allow`、`ask`、`deny`，并处理 interactive / noninteractive / test 三种模式。
- Path Sandbox：限制读写在 `project_root` 内，阻止 `.env`、PEM、SSH key 和系统路径。
- Tool Gateway：统一执行 `read_file`、`write_file`、安全 `shell`、显式 `unsafe_shell_command`、`git_diff`、`mcp_tool`、`skill_context`。
- Hash-linked trace：每个 run 写入可复盘、可独立校验的 `trace.jsonl`。
- Fact Mapper：从显式 `AGENTTRUST_FACTS` block 和工具 metadata 映射结构化 facts。
- GroundGuard adapter：优先调用真实 `groundguard.FactGate`，无法抽取 Lite 演示事实时回退到确定性 `[fact:key]` 校验。
- Replay / Report：生成 timeline、Markdown report 和 HTML report。
- MCP Lite：解析本地 MCP config，隐藏 env value，汇总 tool schema hash，并把 MCP call 包装为受治理的 `ToolIntent`。
- Skill Lite：加载本地 `SKILL.md` 和 `policy.yaml`，记录 allowed tools、blocked tools、required facts 和 output contract。
- Recovery Lite：`write_file` 前备份，支持 `restore <run_id>`、`--dry-run` 和 restore trace。
- Tool Registry Lite：列出工具 schema、scope、source 和默认权限。
- Hook Lite：支持受限 `pre_tool` hook，只能收紧决策。
- Memory / Context Lite：显式本地 memory、run summary、deterministic context pack 和 budget trimming。

## 核心概念

| 概念 | 含义 | 为什么重要 |
| --- | --- | --- |
| `ToolIntent` | Agent 请求执行某个工具的标准化对象。 | 让 fixture、live adapter、MCP wrapper、Skill run 都进入同一条治理链。 |
| `PermissionDecision` | policy 对工具请求的初步判断：`allow` / `ask` / `deny`。 | 把“能不能做”变成可审计事件。 |
| `PathSandbox` | 对读写路径做 project root、secret、system path 检查。 | 防止 Agent 读 secret 或写出项目边界。 |
| `HookDecision` | policy 之外的轻量 pre-tool 扩展点。 | 只允许进一步 deny，不能绕过权限。 |
| `ToolResult` | 工具执行结果、metadata、digest 和错误信息。 | 后续 facts、report、restore 都从这里来。 |
| `Fact` | 从工具结果中显式记录的可验证事实。 | GroundGuard 只把已记录 facts 当作最终回答的证据。 |
| `Run Artifact` | `.agenttrust/runs/{run_id}/` 下的 trace、facts、report、backup、context。 | 每次 Agent 行为都能复盘、审计和恢复。 |

## 工作流

```mermaid
flowchart LR
    A["Fixture / Live Adapter / MCP / Skill"] --> B["ToolIntent"]
    B --> C["Skill Scope"]
    C --> D["Permission Engine"]
    D --> E["Pre-tool Hook"]
    E --> F["Path Sandbox"]
    F --> G["Tool Gateway"]
    G --> H["ToolResult"]
    H --> I["Trace + Facts + Backup"]
    I --> J["GroundGuard Check"]
    J --> K["Replay / Report / Restore"]
```

AgentTrust Runtime 的原则和 GroundGuard 一样：确定性、本地优先、可测试、不依赖第二个 LLM 做裁判。它不猜测任意工具输出里的“事实”，只接受显式 fact block 和明确的工具 metadata。

## CLI

### 核心 run / replay / report

```bash
agenttrust fixtures
agenttrust run-fixture verified_answer
agenttrust run-fixture contradicted_answer
agenttrust run-fixture unverified_answer

agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format html
```

### 权限与沙箱

```bash
agenttrust run-fixture blocked_secret
agenttrust run-fixture ask_noninteractive --non-interactive
agenttrust run-fixture ask_noninteractive --mode test
agenttrust policy validate .agenttrust/policy.yaml
```

### MCP Lite

```bash
agenttrust mcp inspect .mcp.json
agenttrust run-fixture mcp_tool_denied --non-interactive
agenttrust run-fixture mcp_tool_approved --mode test
```

`mcp inspect` 只输出 env key，不输出 env value。`mcp_tool` 的默认权限是 `ask`，即使用户删掉 policy 里的 MCP rule，Tool Registry 默认 effect 也会兜底。

### Skill Lite

```bash
agenttrust skills list
agenttrust skills inspect code-review
agenttrust run --skill code-review "review this repository"
agenttrust run-fixture skill_code_review
agenttrust run-fixture skill_blocked_tool --mode test
```

当前 `run --skill` 是 Lite/demo 入口：它加载本地 skill policy，把 skill scope 写入 trace，并用 deterministic fixture 证明 allowed/blocked tools 生效。它不是完整 coding assistant。

### Recovery Lite

```bash
agenttrust run-fixture write_and_restore --mode test
agenttrust restore <run_id> --dry-run
agenttrust restore <run_id>
```

`restore` 会把已有文件恢复到 `write_file` 前的备份；如果该 run 新建了文件，则恢复时会删除这个新建文件。restore 只信任 project root 内路径和当前 run 的 `backups/` 目录。

### Hook / Tool Registry / Memory / Context

```bash
agenttrust tools list
agenttrust tools inspect shell
agenttrust tools inspect mcp_tool

agenttrust hooks list
agenttrust run-fixture blocked_by_hook --mode test

agenttrust memory add project "GroundGuard verifies final numeric claims."
agenttrust memory add decision "Noninteractive ask is denied by default."
agenttrust memory inspect

agenttrust context build --skill code-review
agenttrust context preview --skill code-review --budget 4000
agenttrust context export --run <run_id>
agenttrust run-fixture memory_context_pack
```

## 与 GroundGuard 的关系

| 层级 | GroundGuard | AgentTrust Runtime |
| --- | --- | --- |
| 核心问题 | 最终回答是否被工具事实支持。 | 工具调用是否被允许、可审计、可恢复，并能产出事实证据。 |
| 关键对象 | `FactGate`、`Ledger`、`CoverageReport`、`Policy`。 | `ToolIntent`、`ToolResult`、`PermissionDecision`、`TraceRecorder`。 |
| 默认立场 | 不用第二个 LLM judge，做确定性 fact gate。 | 不让工具裸跑，先过 permission、sandbox、hook、skill scope。 |
| 产物 | coverage report、assertion JSON、Markdown/HTML/GitHub report。 | trace、decisions、facts、backup、context pack、GroundGuard report。 |

AgentTrust 不是 GroundGuard 的替代品；它是 GroundGuard 前面的 runtime 治理层。GroundGuard 守住“答案里的事实”，AgentTrust 守住“Agent 做事的路径”。

## 运行产物

每次 run 会写入 `.agenttrust/runs/{run_id}/`：

- `trace.jsonl`：append-only 事件流
- `decisions.json`：permission、hook、skill、sandbox 决策
- `facts.jsonl`：从工具结果映射出的结构化事实
- `final-answer.md`：fixture 或 run 的最终回答
- `groundguard-report.json`：最终回答事实覆盖报告
- `report.md` / `report.html`：人类可读报告
- `backups/`：`write_file` 执行前备份
- `context-pack.md` / `context-manifest.json`：受控上下文包

## AgentTrust 不是做什么

- 不是完整企业治理平台。
- 不是 MCP proxy 或 MCP scanner 的替代品。
- 不是 skill marketplace，也不做远程 skill 安装。
- 不是完整 coding assistant、TUI 或 git worktree manager。
- 不是 tracing/observability dashboard。
- 不是通用 hallucination detector。
- 不提供远程托管或第三方信任服务；本地 evidence chain 可通过 `agenttrust evidence verify <run_id>` 校验。

它刻意保持小而硬：只展示本地 Agent runtime 最关键的治理闭环。

## 文档

- [Docs home](docs/index.md)
- [Getting started](docs/getting-started.md)
- [CLI reference](docs/cli.md)
- [Core concepts](docs/concepts.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Enterprise architecture upgrade](docs/enterprise-architecture.md)
- [Refactor roadmap](docs/refactor-roadmap.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Related work and scope](docs/RELATED_WORK.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [最终实施方案](AgentTrust-Runtime-%E6%9C%80%E7%BB%88%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md)

## 安全说明

Run artifacts 可能包含 prompt、工具输出、文件路径和业务事实。AgentTrust 默认本地运行，不上传数据。公开分享 `.agenttrust/runs/`、fixtures、reports 或 screenshots 前，请先脱敏。

## 贡献

欢迎贡献：

- 脱敏后的 Agent 工具越权/事实遗漏案例
- 新的 deterministic fixture
- 更好的 fact mapper
- 更严格的 sandbox / recovery 测试
- MCP / Skill / Context Lite 的真实项目接入反馈

较大的改动请先开 issue 说明动机和建议 API。

## License

AgentTrust Runtime 基于 MIT License 发布。
