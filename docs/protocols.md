# 协议与异步运行时

## 版本化工件

仓库根目录的 `schemas/` 提供独立 JSON Schema：

- `decision-v1.schema.json`：策略决策请求。
- `policy-v1.schema.json`：YAML/JSON policy 的可移植子集。
- `evidence-v1.schema.json`：evidence envelope。
- `tool-spec-v1.schema.json`：工具注册表描述。

相应的正向 conformance fixtures 位于 `tests/fixtures/conformance/`。它们适合被外部校验器、策略仓库或发布流水线直接读取。

## DecisionRequest 与 DecisionResponse

```python
from agenttrust.domain.models import ToolIntent
from agenttrust.domain.protocol import DecisionRequest
from agenttrust.permissions.engine import PermissionEngine

intent = ToolIntent("run_001", "call_001", "write_file", {"path": "src/app.py"}, "adapter")
request = DecisionRequest.from_intent(intent, actor_id="alice", agent_id="coding-agent")
response = PermissionEngine(policy).evaluate(request)
```

`DecisionRequest.from_intent()` 对旧 `ToolIntent` 保持兼容，同时只把策略匹配需要的属性放入 `attributes`。`DecisionResponse.obligations` 在 `ask` 时包含 `require_approval`。

## 解释与测试策略

`agenttrust policy explain` 的输出可作为 code review artifact：它同时显示 request、命中规则、工具默认值、优先级列表和选择后的 response。`policy test` fixture 使用确定性输入，不需要执行真实工具。

```json
[
  {
    "id": "source-write",
    "tool": "write_file",
    "arguments": {"path": "src/app.py"},
    "expected_effect": "ask"
  }
]
```

## 异步集成

```python
async with runtime.async_session(actor_id="alice") as session:
    result = await session.execute_async("read_file", {"path": "README.md"})
```

动态 async 工具使用 `govern_async()` 或 `session.register_async_tool()`。同步工具不会改变其既有 API；async gateway 为它们提供兼容执行路径。恢复已决定审批时，使用 `async with await runtime.async_resume(run_id, tool_call_id="call_002") as session` 和 `await session.resume_pending_approval_async("call_002")`。
