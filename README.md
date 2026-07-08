# AgentTrust Runtime

AgentTrust Runtime 是一个 local-first 的 Python runtime 设计，用来治理 Agent 工具调用。

项目目标不是做一个大而全的平台，而是实现一条小、确定、可测试的核心控制链路：把每一次 Agent 工具请求转换成可审计的 `ToolIntent`，在执行前经过权限判断和路径沙箱，记录可复盘的 trace，并用 GroundGuard 校验最终回答里的结构化事实是否有证据支持。

## 当前状态

当前仓库已经包含合并后的最终实施方案，并已完成 MVP runtime：

- `agenttrust init`
- `agenttrust run-fixture`
- `agenttrust run-live fake_tool_request`
- ToolIntent / ToolResult
- Tool Gateway
- Permission Engine
- Path Sandbox
- append-only `trace.jsonl`
- `read_file` / `write_file` / `shell` / `git_diff`
- explicit fact block mapper
- tool metadata facts
- GroundGuard-style coverage report
- `replay` / markdown `report` / HTML `report`
- pytest 和 GitHub Actions CI

完整 MVP 范围和 Roadmap 见：[最终实施方案](AgentTrust-Runtime-%E6%9C%80%E7%BB%88%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md)。

## 核心链路

```text
Input Source
  -> ToolIntent
  -> Tool Gateway
  -> Permission Engine
  -> Path Sandbox
  -> Tool Execution
  -> Append-only Trace
  -> Fact Mapper
  -> GroundGuard FactGate
  -> Replay / Report
```

fixture 和极简 live adapter 必须走同一套 Gateway、Permission Engine、Sandbox、Trace Recorder 和 FactGate。fixture 只是输入源，不是绕过 runtime 的独立 demo 脚本。

## MVP 范围

MVP 范围刻意收窄，只做核心链路：

- ToolIntent 和 ToolResult schema
- Tool Gateway
- 支持 `allow`、`ask`、`deny` 的 Permission Engine
- Path Sandbox
- 内置工具：`read_file`、`write_file`、`shell`、`git_diff`
- append-only `trace.jsonl`
- deterministic fixtures
- GroundGuard adapter
- replay 和 report 生成
- 极简 live adapter：`run-live fake_tool_request`
- README、Threat Model、Related Work、测试和 CI

MVP 不做完整企业治理平台，不做完整 MCP scanner，不做 coding assistant，不做 SaaS，也不试图替代已有的 Agent observability / governance 工具。

## 目标 CLI

计划中的 MVP 命令如下：

```bash
agenttrust init

agenttrust run-fixture blocked_secret
agenttrust run-fixture ask_noninteractive --non-interactive
agenttrust run-fixture verified_answer
agenttrust run-fixture contradicted_answer
agenttrust run-fixture unverified_answer

agenttrust run-live fake_tool_request

agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format markdown
agenttrust report <run_id> --format html

agenttrust policy validate .agenttrust/policy.yaml
```

## Demo Fixtures

MVP demo 必须确定、可复现、可测试：

- `blocked_secret`：Agent 请求读取 `.env`，runtime 拒绝访问。
- `ask_noninteractive`：写文件请求命中 `ask`，在 noninteractive 模式下转成 `deny`。
- `verified_answer`：最终回答被已记录事实支持。
- `contradicted_answer`：最终回答和已记录事实矛盾。
- `unverified_answer`：最终回答缺少 required fact 的证据支持。

## 为什么接 GroundGuard

AgentTrust Runtime 不尝试解决通用 hallucination detection。它只校验工具输出中显式记录的结构化事实，尤其是数字声明、工具元数据和 run artifacts。

MVP 会复用 GroundGuard 的 fact recording、coverage check 和 report 能力。AgentTrust 只补 runtime 侧 adapter，把 ToolResult 和 fixture output 映射成 GroundGuard 能理解的结构化事实。

## Roadmap

以下能力刻意不进入 MVP：

- MCP Lite：inspect 本地 MCP config，并把已知 MCP tool call 包装成 ToolIntent。
- Skill Lite：把本地 `SKILL.md` instruction、tool scope、required facts 和 output contract 绑定到一次 run。
- Recovery Lite：在 `write_file` 前备份文件，并支持按 run id 恢复。
- Tool Registry Lite：列出和 inspect 工具 schema、scope 和 default effect。
- Hook Lite：增加受限的 `pre_tool` 扩展点，只允许收紧决策。
- Memory Lite / Context Lite：显式本地项目记忆、run summary、确定性 context pack 和 budget trimming。

这些能力必须服从核心 runtime 链路。如果一个功能不能强化 permission、sandbox、trace、FactGate 或 report，就不进入 MVP。

## Related Work and Scope

AgentTrust Runtime 是一个用于学习和作品集展示的小型 local-first 实现。它不是 Microsoft Agent Governance Toolkit、Invariant MCP-Scan、Cisco MCP Scanner、Snyk Agent Scan、AgentOps、Braintrust 或 Phoenix 的替代品。这些项目覆盖更完整的生产治理、MCP/skills scanning 或 observability 场景。

本项目只聚焦一条窄路径：policy-gated local tool execution、replayable traces，以及同一个 run artifact 中由 GroundGuard 支撑的 fact verification。

## 下一步

后续进入 Roadmap，而不是继续扩大 MVP：

- MCP Lite
- Skill Lite
- Recovery Lite
- Tool Registry Lite
- Hook Lite
- Memory Lite / Context Lite
