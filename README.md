# AgentTrust Runtime

AgentTrust Runtime 是一个 local-first 的 Python runtime，用来治理 Agent 工具调用：每一次工具请求都会被规范化为 `ToolIntent`，经过权限判断、路径沙箱、可审计 trace、结构化事实映射，并在最终回答阶段接入 GroundGuard 进行事实覆盖校验。

这个仓库已经完成两层能力：

- 核心 MVP：`ToolIntent -> Tool Gateway -> Permission Engine -> Path Sandbox -> Trace -> Fact Mapper -> GroundGuard -> Replay/Report`
- Roadmap Lite：MCP inspect/wrapper、Skill loader、Recovery、Tool Registry、Hook、Memory、Context pack

完整设计口径见：[最终实施方案](AgentTrust-Runtime-%E6%9C%80%E7%BB%88%E5%AE%9E%E6%96%BD%E6%96%B9%E6%A1%88.md)。

## 安装和初始化

```bash
python -m pip install -e ".[test]"
agenttrust init
```

初始化后会生成：

```text
.agenttrust/
  policy.yaml
  runs/
  skills/code-review/
```

## 快速验证

```bash
agenttrust fixtures
agenttrust run-fixture verified_answer
agenttrust replay <run_id>
agenttrust report <run_id>
agenttrust report <run_id> --format html
```

事实校验 fixtures：

```bash
agenttrust run-fixture verified_answer
agenttrust run-fixture contradicted_answer
agenttrust run-fixture unverified_answer
```

权限与沙箱 fixtures：

```bash
agenttrust run-fixture blocked_secret
agenttrust run-fixture ask_noninteractive --non-interactive
agenttrust run-fixture ask_noninteractive --mode test
```

## Roadmap Lite 命令

工具注册表：

```bash
agenttrust tools list
agenttrust tools inspect shell
agenttrust tools inspect mcp_tool
```

MCP Lite：

```bash
agenttrust mcp inspect .mcp.json
agenttrust run-fixture mcp_tool_denied --non-interactive
agenttrust run-fixture mcp_tool_approved --mode test
```

Skill Lite：

```bash
agenttrust skills list
agenttrust skills inspect code-review
agenttrust run --skill code-review "review this repository"
agenttrust run-fixture skill_code_review
```

Recovery Lite：

```bash
agenttrust run-fixture write_and_restore --mode test
agenttrust restore <run_id> --dry-run
agenttrust restore <run_id>
```

`restore` 会把已有文件恢复到 `write_file` 前的备份；如果该 run 新建了文件，则恢复时会删除这个新建文件。

Hook Lite：

```bash
agenttrust hooks list
agenttrust run-fixture blocked_by_hook --mode test
```

Memory / Context Lite：

```bash
agenttrust memory add project "GroundGuard verifies final numeric claims."
agenttrust memory add decision "Noninteractive ask is denied by default."
agenttrust memory inspect
agenttrust context build --skill code-review
agenttrust context preview --skill code-review --budget 4000
agenttrust context export --run <run_id>
agenttrust run-fixture memory_context_pack
```

## 运行产物

每次 run 会写入 `.agenttrust/runs/{run_id}/`：

- `trace.jsonl`：append-only 事件流
- `decisions.json`：权限、hook、skill 决策
- `facts.jsonl`：从工具结果映射出的结构化事实
- `groundguard-report.json`：最终回答事实覆盖报告
- `report.md` / `report.html`：可读报告
- `backups/`：`write_file` 执行前备份
- `context-pack.md` / `context-manifest.json`：导出的上下文包

## GroundGuard 集成

如果本地安装了 `groundguard`，AgentTrust 会优先使用真实 `FactGate` 和 `report_to_versioned_dict`。当 GroundGuard 无法抽取某类 Lite 演示事实时，会回退到本项目的确定性 `[fact:key]` 校验，保证 fixtures 在离线和 CI 环境中仍然可复现。

## 测试

```bash
python -m pytest
```

当前测试覆盖核心链路、权限模式、路径沙箱、GroundGuard adapter、report、MCP Lite、Skill Lite、Recovery Lite、Hook Lite、Tool Registry Lite、Memory Lite 和 Context Lite。

## 范围边界

AgentTrust Runtime 不是完整企业治理平台，也不是 MCP proxy、skill marketplace、SaaS 或完整 coding assistant。它的目标是用一个小而可审计的 runtime 展示 Agent 工具执行治理的关键控制点：权限、沙箱、trace、恢复、受控上下文和最终回答事实校验。
