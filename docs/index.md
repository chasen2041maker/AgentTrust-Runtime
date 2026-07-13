# AgentTrust Runtime 文档

AgentTrust Runtime 是本地优先的 Agent 工具执行控制层：它为现有 Agent 框架补上会话状态、策略、审批、沙箱、真实 MCP 信任、可验证 evidence 与最终答案事实核验。

## 从这里开始

- [快速入门](getting-started.md)：安装、首个可验证 run 与 Session API。
- [CLI 参考](cli.md)：命令、审批恢复、MCP 和 OTel 导出。
- [核心概念](concepts.md)：领域对象和状态机。
- [运行时架构](ARCHITECTURE.md)：控制路径、存储职责和包边界。
- [威胁模型](THREAT_MODEL.md)：攻击者模型、覆盖控制与残余风险。
- [相关工作与边界](RELATED_WORK.md)：项目定位与刻意不做的内容。
- [架构演进方案](enterprise-architecture.md)：已落地能力与下一阶段边界。
- [重构路线图](refactor-roadmap.md)：架构迁移的完成状态。
- [Security Regression Suite](../benchmarks/README.md)：公开的 107 个确定性控制检查（100 个攻击用例与 7 个安全基线）。
- [变更记录](../CHANGELOG.md)：版本演进。
- [贡献指南](../CONTRIBUTING.md) 与 [安全策略](../SECURITY.md)。

## 当前保证

1. 同一 session 的多次工具调用共享身份、策略快照、facts 与 hash-linked evidence。
2. `ask` 在 noninteractive 运行中 fail closed；审批恢复绑定原始参数摘要。
3. JSONL 是证据源，SQLite 可从已验证 trace 重建。
4. MCP config 的 inspect 不启动 server；真实调用需要 consent、tool trust 和未漂移的 fingerprint。
5. OpenTelemetry 从 evidence 重建 span；项目不托管 Dashboard。
6. `security-v1` 用 107 个确定性控制检查（100 个预期拦截与 7 个预期允许）回归上述控制。
