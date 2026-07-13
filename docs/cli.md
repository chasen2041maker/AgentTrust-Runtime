# CLI 参考

所有命令可附带 `--project-root <path>`。运行相关命令默认使用当前目录的 `.agenttrust/`。

## 初始化与示例

```powershell
agenttrust init
agenttrust fixtures
agenttrust run-fixture verified_answer --mode test
agenttrust run-live fake_tool_request --mode interactive
```

`run-fixture` 提供可重复的权限、沙箱、事实、恢复、MCP 和上下文测试路径。模式为 `interactive`、`noninteractive` 或 `test`；只有 `test` 使用 mock approver。

## Run 与证据

```powershell
agenttrust replay <run_id>
agenttrust report <run_id> [--format markdown|html]
agenttrust evidence verify <run_id>
agenttrust evidence export <run_id>
agenttrust evidence export-otel <run_id> --endpoint <otlp-http-url>
agenttrust state rebuild
```

- `verify` 独立验证 JSONL hash chain。
- `export` 写出便于摄取的 NDJSON。
- `export-otel` 需要安装 `.[otel]`，从已有 evidence 重建 `agenttrust.session`、工具阶段和最终答案 span。
- `state rebuild` 只从已验证 trace 重建 SQLite 投影。

## 审批、恢复与策略

```powershell
agenttrust approvals list
agenttrust approvals inspect <approval_id>
agenttrust approvals approve <approval_id> --reason "reviewed" [--approver alice]
agenttrust approvals deny <approval_id> --reason "unsafe"
agenttrust run resume <run_id>
agenttrust run cancel <run_id>
agenttrust restore <run_id> [--file path] [--dry-run]
agenttrust policy validate .agenttrust/policy.yaml
```

审批决定写回 evidence 与 SQLite，且绑定原始 `arguments_digest`。`resume` 拒绝无效证据、缺失策略快照、未决审批或摘要不匹配的 run。

## 工具与本地上下文

```powershell
agenttrust tools list
agenttrust tools inspect shell
agenttrust hooks list
agenttrust skills list
agenttrust skills inspect code-review
agenttrust memory add project "Local policy is explicit."
agenttrust memory inspect
agenttrust context build --skill code-review --budget 4000
agenttrust context preview --skill code-review --budget 4000
agenttrust context export --run <run_id>
```

工具注册表提供默认 effect。未知工具在权限阶段被拒绝；`shell` 默认 `ask`，安全实现仅接受 argv。

## MCP

```powershell
agenttrust mcp discover
agenttrust mcp inspect <server-or-config-path>
agenttrust mcp consent grant <server>
agenttrust mcp trust <server> --tool read_file --tool search_docs
agenttrust mcp consent revoke <server>
```

`discover` 和 `inspect` 只静态读取 Claude Code、Codex、Cursor、VS Code 与项目范围的配置；输出只列出环境变量 key。`trust` 在发现的真实 server 上先要求 consent，再使用 `tools/list` 保存允许工具的 command/schema 指纹。漂移会变成 `trust_stale` 并拒绝工具调用。

## 安全基准

```powershell
agenttrust benchmark security --output benchmark-report.json
```

命令运行公开的 `security-v1` 100 例数据集，输出逐例结果和聚合安全指标。当出现 false negative 或 critical bypass 时退出码为 `2`。
