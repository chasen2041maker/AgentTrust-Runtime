# CLI 参考

所有命令都可附带 `--project-root <path>`。运行数据默认位于当前目录的 `.agenttrust/`；JSONL evidence 是事实来源，`state.db` 只是可重建查询投影。

## 初始化与确定性验证

```powershell
agenttrust init
agenttrust fixtures
agenttrust run-fixture verified_answer --mode test
agenttrust run-live fake_tool_request --mode interactive
agenttrust benchmark security --output benchmark-report.json
```

`runtime_mode` 为 `interactive`、`noninteractive` 或 `test`。它与审批模式分离：SDK 会话默认使用 `deferred`，只有显式指定 `inline_prompt` 才会读取终端输入；`mock` 仅允许 test 模式。

## Run、证据与状态

```powershell
agenttrust replay <run_id>
agenttrust report <run_id> [--format markdown|html]
agenttrust evidence verify <run_id>
agenttrust evidence export <run_id>
agenttrust evidence export-otel <run_id> --endpoint <otlp-http-url>
agenttrust state rebuild
```

- `verify` 独立验证 JSONL hash chain。
- `export` 写出面向 SIEM 或离线分析的 NDJSON。
- `export-otel` 需要安装 `.[otel]`，并且只从已验证 evidence 重建 span。
- `state rebuild` 扫描全部已验证 run；普通 session 与单个恢复流程只增量维护或修复目标 run。

## 审批、恢复与取消

```powershell
agenttrust approvals list
agenttrust approvals inspect <approval_id>
agenttrust approvals approve <approval_id> --reason "reviewed" [--approver alice]
agenttrust approvals deny <approval_id> --reason "unsafe"
agenttrust run resume <run_id> [--tool-call-id call_002]
agenttrust run cancel <run_id>
```

审批记录绑定原始 `arguments_digest`，`inspect` 只显示脱敏参数。默认 TTL 为一小时，可由策略或 session 覆盖。一个 run 可以有多个 `waiting_approval` 调用；多个候选同时存在时，必须传 `--tool-call-id` 精确恢复。恢复拒绝无效 evidence、缺失策略快照、未决/过期审批和摘要不匹配。

## 策略协议工具

```powershell
agenttrust policy validate .agenttrust/policy.yaml
agenttrust policy lint .agenttrust/policy.yaml
agenttrust policy test .agenttrust/policy.yaml policy-fixtures.json
agenttrust policy explain .agenttrust/policy.yaml --tool write_file --path src/report.py
agenttrust policy explain .agenttrust/policy.yaml --tool shell --argv-json '["git", "status"]'
```

- `validate` 解析策略文件。
- `lint` 报告重复规则 ID、空原因和完全同范围但 effect 冲突的规则。
- `test` 执行 JSON fixture。fixture 可以是数组，或 `{ "cases": [...] }`；每个 case 包含 `tool`、可选 `arguments` 和 `expected_effect`。
- `explain` 输出协议请求、全部命中规则、工具默认 effect、优先级顺序与最终 `DecisionResponse`。

## 恢复受控写入

```powershell
agenttrust restore <run_id> [--file path]
agenttrust restore <run_id> --apply
agenttrust restore <run_id> --apply --force
```

恢复默认预览。只有已验证 evidence 中成功写入后记录的恢复点可以被应用；如果目标文件的写后摘要已变化，除非提供 `--force`，否则会跳过。

## 工具、上下文与 MCP

```powershell
agenttrust tools list
agenttrust tools inspect shell
agenttrust hooks list
agenttrust skills list
agenttrust memory inspect
agenttrust context build --skill code-review --budget 4000

agenttrust mcp discover
agenttrust mcp inspect <server-or-config-path>
agenttrust mcp consent grant <server>
agenttrust mcp trust <server> --tool read_file --tool search_docs
agenttrust mcp consent revoke <server>
```

`discover` 与 `inspect` 是静态读取，不启动 server，也不会输出环境变量值。真实 MCP 调用需要 consent、逐工具 trust 与未漂移的 command/schema fingerprint。
