# 威胁模型

## 范围

AgentTrust 保护本地开发工作流中的受治理工具调用：文件、shell、git、MCP、动态 Python tool、skill/context 与 `write_file` 恢复。它假设模型输出、工具参数、MCP 描述和最终自然语言答案都是不可信输入。

## 资产与信任边界

- 项目源码、秘密文件与系统路径。
- 策略快照、审批决定、run evidence、facts、恢复备份，以及可选的签名 anchor 与签名密钥。
- MCP server command、环境变量 key、工具描述与输入 schema。
- 最终答案中的事实断言。

JSONL 是运行期 append-only、可独立验证的 evidence 源；SQLite 只是可重建投影。hash chain 能发现普通篡改。可选 Ed25519 anchor 会签名已验证 trace head；当验证方固定使用独立获得的公钥时，攻击者即使重写整条本地链也无法伪造同一签名者的 anchor。它不是外部时间戳或不可变存储，拥有本地写权限的攻击者仍可删除 artifact、替换未固定的公钥，或在获得私钥后重签。AgentTrust 不输出 MCP 环境变量值，也不自动上传本地 artifact。

## 覆盖攻击与控制

| 攻击 | 主控制 | 可验证证据 |
| --- | --- | --- |
| 路径遍历、系统路径或符号链接逃逸 | `PathSandbox` | `sandbox_decision` |
| `.env`、PEM、SSH 秘密读取 | sandbox + secret policy | 拒绝 reason |
| 危险 shell | 默认 `ask` + 危险模式 `deny` | `permission_decision` |
| 非交互模式绕过人工批准 | `ask -> deny` | `approval_required` |
| 批准后替换参数 | approval-bound `arguments_digest` | resume 拒绝 |
| 未注册工具 | registry fail-closed | `unregistered_tool` |
| MCP 未授权、未信任或 schema 漂移 | consent + trust + fingerprints | `trust_stale` / MCP evidence |
| MCP 子进程继承宿主凭据 | allowlisted OS runtime env + 显式 config `env` | `mcp_environment_mode=allowlisted` |
| 损坏或语义不一致的 policy pack | schema version + normalized policy + canonical digest + explicit overwrite | policy pack import rejection |
| 篡改或重写 run history | hash-linked JSONL + 可选 Ed25519 anchor | `event_hash_mismatch` / `trace_head_changed` |
| 事实矛盾或缺失 | GroundGuard fact check | `groundguard-report.json` |
| 越界恢复 | target/backup path constraints | restore trace |

`security-v1` 把其中七类控制编成 107 个公开确定性检查：100 个预期拦截攻击用例和 7 个预期允许基线，详见 [Security Regression Suite](../benchmarks/README.md)。

## 关键安全不变量

1. 未知工具和 noninteractive `ask` 不能到达工具网关。
2. 审批只能恢复原始的 tool call、原始 policy snapshot 和原始参数摘要。
3. 未获 consent 的 MCP server 不启动；未信任或已漂移工具不调用；真实 stdio 进程不继承任意宿主凭据环境变量。
4. 无效 trace 不能用于恢复或状态重建。
5. 不同 session 的 facts 不可混用以核验最终答案。

## 残余风险与非目标

AgentTrust 不能证明模型意图，也不能保护绕过 Tool Gateway 的外部工具。它没有网络 egress sandbox、可信时间戳、远程见证日志、不可变存储、云 policy server、账户/组织权限模型、通用自然语言真伪裁判或完整 OWASP Agentic Top 10 覆盖。policy pack 的 digest 不能认证作者，仍需审查来源或固定可信 digest。local artifact 仍可能包含敏感输出，用户在共享前必须检查和脱敏。
