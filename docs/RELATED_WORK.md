# 相关工作与项目边界

AgentTrust Runtime 借鉴了 Agent Governance Toolkit 的低摩擦治理接入、AgentOps 的 session 生命周期、OpenAI Agents 与 LangGraph 的暂停/恢复理念、MCP 安全实践的 consent/trust 模型，以及 Phoenix、Jaeger、Tempo、Langfuse 使用 OpenTelemetry 的方式。

它不试图替代这些项目。AgentTrust 的定位更窄：为已有 Agent 框架提供一个本地、可嵌入、可审计的工具执行控制层。

## 已实现

- 多工具调用共享的 session、身份、策略快照、facts 和 evidence。
- 持久化审批、参数摘要绑定、取消、超时与重启后恢复。
- 安全 shell 默认值、未知工具 fail-closed、文件沙箱与写入恢复。
- OpenAI Agents、LangGraph、Pydantic AI 的 session-scoped tool wrapper。
- 真实 stdio MCP、静态发现、显式 consent、tool trust 与 schema drift 失效。
- JSONL hash chain、SQLite 投影重建、OTel evidence exporter。
- GroundGuard 最终答案核验与公开的 100 例安全基准。

## 刻意不做

- Agent 编排或模型调用框架。
- Web Dashboard、云端数据存储或 SIEM 产品。
- 远程 policy server、用户/组织管理、跨租户隔离。
- React 前端、多语言 SDK、skill marketplace、远程 memory service。
- 通用 LLM judge 或“自动判断一切真伪”的能力。

这些边界使项目可以把工程强度集中在可验证的本地执行控制，而不是扩张成另一个全栈 Agent 平台。
