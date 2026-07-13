"""Low-friction wrappers for governing ordinary synchronous Python tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from hashlib import sha256
from inspect import isawaitable
import json
from pathlib import Path
from typing import Any, TypeVar

from agenttrust.domain.models import ToolIntent, ToolResult
from agenttrust.interfaces.python_api import AgentTrustRuntime, AgentTrustSession
from agenttrust.tools.registry import ToolSpec


T = TypeVar("T")
_MISSING = object()


class GovernedToolError(RuntimeError):
    """Base error raised when governance prevents a wrapped tool from returning."""


class ApprovalPending(GovernedToolError):
    """A wrapped call stopped safely and now requires a persisted approval decision."""

    def __init__(self, session: AgentTrustSession, approval_id: str) -> None:
        super().__init__(f"tool call is waiting for approval: {approval_id}")
        self.session = session
        self.approval_id = approval_id


class GovernedToolDenied(GovernedToolError):
    """A wrapped call was denied by policy, hooks, or sandbox controls."""


class GovernedToolExecutionError(GovernedToolError):
    """The governed callable executed but returned an error result."""


def govern(
    tool: Callable[..., T],
    *,
    runtime: AgentTrustRuntime | None = None,
    session: AgentTrustSession | None = None,
    tool_name: str | None = None,
    default_effect: str = "ask",
) -> Callable[..., T]:
    """Wrap one Python tool so every invocation passes through AgentTrust governance.

    Pass a `session` to share a run with an existing agent loop, or pass a `runtime`
    to create one governed session per call. Custom tools must use an explicit
    default policy effect rather than bypassing the tool registry.
    """

    if (runtime is None) == (session is None):
        raise ValueError("provide exactly one of runtime or session")
    if default_effect not in {"allow", "ask", "deny"}:
        raise ValueError(f"invalid governed tool default effect: {default_effect}")
    resolved_name = tool_name or tool.__name__
    if not resolved_name:
        raise ValueError("governed tool requires a non-empty name")
    results: dict[str, object] = {}
    spec = ToolSpec(
        name=resolved_name,
        category="custom",
        input_schema={"args": "array", "kwargs": "object"},
        default_effect=default_effect,
        source="govern",
    )

    def handler(intent: ToolIntent, _project_root: Path) -> ToolResult:
        try:
            args, kwargs = _decode_arguments(intent.arguments)
            value = tool(*args, **kwargs)
            if isawaitable(value):
                raise TypeError("govern() supports synchronous tools only")
            results[intent.tool_call_id] = value
            preview = repr(value)
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="ok",
                output_preview=preview[:500],
                output_digest="sha256:" + sha256(preview.encode("utf-8")).hexdigest(),
                metadata={"governed_callable": True, "output_type": type(value).__name__},
            )
        except Exception as exc:
            return ToolResult(
                run_id=intent.run_id,
                tool_call_id=intent.tool_call_id,
                tool_name=intent.tool_name,
                status="error",
                error=f"governed callable failed: {exc}",
                metadata={"governed_callable": True},
            )

    def register(target_session: AgentTrustSession) -> AgentTrustSession:
        target_session.register_tool(spec, handler)
        return target_session

    def invoke(target_session: AgentTrustSession, args: tuple[object, ...], kwargs: dict[str, object]) -> T:
        register(target_session)
        payload: dict[str, object] = {"args": list(args), "kwargs": kwargs}
        _assert_json_serializable(payload)
        run = target_session.execute(resolved_name, payload, source="govern")
        if run.approval_request is not None:
            raise ApprovalPending(target_session, run.approval_request.approval_id)
        if run.outcome.result is None:
            raise GovernedToolDenied(run.outcome.final_permission.reason)
        if run.outcome.result.status != "ok":
            raise GovernedToolExecutionError(run.outcome.result.error or "governed tool execution failed")
        value = results.pop(run.tool_call.tool_call_id, _MISSING)
        if value is _MISSING:
            raise GovernedToolExecutionError("governed tool returned no Python value")
        return value  # type: ignore[return-value]

    @wraps(tool)
    def wrapped(*args: object, **kwargs: object) -> T:
        if session is not None:
            return invoke(session, args, kwargs)
        assert runtime is not None
        with runtime.session() as new_session:
            return invoke(new_session, args, kwargs)

    setattr(wrapped, "register", register)
    return wrapped


def governed_tool(
    *,
    runtime: AgentTrustRuntime | None = None,
    session: AgentTrustSession | None = None,
    name: str | None = None,
    default_effect: str = "ask",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorate an ordinary tool function with the same behavior as `govern()`."""

    def decorate(tool: Callable[..., T]) -> Callable[..., T]:
        return govern(
            tool,
            runtime=runtime,
            session=session,
            tool_name=name,
            default_effect=default_effect,
        )

    return decorate


def _decode_arguments(arguments: dict[str, Any]) -> tuple[list[object], dict[str, object]]:
    raw_args = arguments.get("args")
    raw_kwargs = arguments.get("kwargs")
    if not isinstance(raw_args, list) or not isinstance(raw_kwargs, dict):
        raise ValueError("governed tool requires args array and kwargs object")
    if not all(isinstance(key, str) for key in raw_kwargs):
        raise ValueError("governed tool keyword argument names must be strings")
    return list(raw_args), dict(raw_kwargs)


def _assert_json_serializable(payload: dict[str, object]) -> None:
    try:
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("governed tool arguments must be JSON serializable") from exc
