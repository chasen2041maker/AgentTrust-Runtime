# 快速入门

AgentTrust Runtime 是嵌入在 Agent 框架与工具之间的本地控制层。先用确定性 fixture 观察完整路径，再接入自己的 agent loop。

## 安装

```powershell
git clone https://github.com/chasen2041maker/AgentTrust-Runtime.git
cd AgentTrust-Runtime
python -m pip install -e ".[test]"
agenttrust init
```

`init` 创建 `.agenttrust/policy.yaml`、运行目录和示例 skill。默认策略把写代码、shell 和 MCP 视为需要批准的风险动作，并阻断秘密文件与危险 shell 模式。

可选能力保持独立安装：

```powershell
python -m pip install -e ".[otel]"
python -m pip install -e ".[openai]"
python -m pip install -e ".[langgraph]"
python -m pip install -e ".[pydantic-ai]"
```

## 第一个可验证 run

```powershell
agenttrust run-fixture verified_answer --mode test
agenttrust evidence verify <run_id>
agenttrust replay <run_id>
agenttrust report <run_id> --format html
```

该 fixture 经过权限、沙箱、工具网关、事实映射和 GroundGuard 最终答案检查。生成的 `trace.jsonl` 是 hash-linked evidence 源，`report.html` 是便于查看的摘要。

## 使用 Session API

```python
from pathlib import Path

from agenttrust import AgentTrustRuntime

runtime = AgentTrustRuntime(Path("."), runtime_mode="test")
with runtime.session(actor_id="alice", agent_id="demo-agent") as session:
    tool_run = session.execute("read_file", {"path": "README.md"})
    lines = tool_run.outcome.result.metadata["lines"]
    answer = session.finalize_answer(
        f"README has {lines} lines [fact:read_file_lines].",
        required_fact_keys=["read_file_lines"],
    )
    print(answer.status, answer.completed)
```

同一 session 的调用共享 `run_id`、身份、策略快照、事实账本和 evidence chain。`finalize_answer()` 将最终答案交给 GroundGuard，并按 `final_answer.on_incomplete` 策略完成、警告、拒绝完成或要求修订。

## 演示审批与恢复

```powershell
agenttrust run-fixture ask_noninteractive --non-interactive
agenttrust run-fixture write_and_restore --mode test
agenttrust restore <run_id> --dry-run
agenttrust restore <run_id>
```

在 noninteractive 模式，`ask` 必然变成 `deny`，不会悄悄放行。真实 session 等待审批时可查看并决定请求：

```powershell
agenttrust approvals list
agenttrust approvals approve <approval_id> --reason "reviewed"
agenttrust run resume <run_id>
```

恢复会校验 evidence、审批决定和原始参数摘要；SQLite 状态损坏时使用 `agenttrust state rebuild` 从 JSONL 重新投影。

## 接下来

- 阅读 [CLI 参考](cli.md) 获取全部命令。
- 阅读 [运行时架构](ARCHITECTURE.md) 了解控制路径与模块边界。
- 按 [README](../README.md#框架集成) 接入 OpenAI Agents、LangGraph 或 Pydantic AI。
- 用 [安全基准](../benchmarks/README.md) 检查本地运行环境中的 100 条控制样例。
