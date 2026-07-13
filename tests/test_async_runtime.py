from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agenttrust import AgentTrustRuntime, ApprovalPending, govern_async, governed_async_tool
from agenttrust.adapters.evidence.jsonl_store import read_trace, verify_trace
from agenttrust.cli import main


def test_async_session_executes_native_async_governed_tool(tmp_path: Path) -> None:
    async def scenario() -> tuple[Path, str, int]:
        runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
        callback_loop_id: int | None = None

        async with runtime.async_session(actor_id="alice") as session:
            async def add(left: int, right: int) -> int:
                nonlocal callback_loop_id
                callback_loop_id = id(asyncio.get_running_loop())
                await asyncio.sleep(0)
                return left + right

            governed_add = govern_async(add, session=session, tool_name="async_add", default_effect="allow")
            assert await governed_add(20, 22) == 42

        assert callback_loop_id == id(asyncio.get_running_loop())
        return session.run_dir, session.session.status, callback_loop_id

    run_dir, status, _ = asyncio.run(scenario())

    assert status == "completed"
    events = read_trace(run_dir / "trace.jsonl")
    assert next(event for event in events if event["event_type"] == "tool_intent")["source"] == "govern_async"
    assert verify_trace(run_dir / "trace.jsonl")["valid"] is True


def test_runtime_execute_async_supports_the_existing_sync_tool_gateway(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("async sdk\n", encoding="utf-8")

    result = asyncio.run(AgentTrustRuntime(tmp_path, runtime_mode="test").execute_async("read_file", {"path": "README.md"}))

    assert result.outcome.final_permission.final_effect == "allow"
    assert result.outcome.result is not None
    assert result.outcome.result.status == "ok"
    assert verify_trace(result.run_dir / "trace.jsonl")["valid"] is True


def test_governed_async_tool_decorator_uses_a_fresh_async_session(tmp_path: Path) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")

    @governed_async_tool(runtime=runtime, name="async_multiply", default_effect="allow")
    async def multiply(left: int, right: int) -> int:
        return left * right

    assert asyncio.run(multiply(6, 7)) == 42


def test_async_resume_executes_the_selected_approved_call(tmp_path: Path, capsys) -> None:
    async def create_pending():
        runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
        async with runtime.async_session() as session:
            pending = await session.execute_async("write_file", {"path": "async-resume.txt", "content": "done"})
        return runtime, session, pending

    runtime, session, pending = asyncio.run(create_pending())
    assert pending.approval_request is not None
    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "approvals",
                "approve",
                pending.approval_request.approval_id,
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    capsys.readouterr()

    async def resume() -> str:
        async with await runtime.async_resume(session.run_id, tool_call_id=pending.tool_call.tool_call_id) as resumed:
            tool_run = await resumed.resume_pending_approval_async(pending.tool_call.tool_call_id)
            assert tool_run.tool_call.status == "succeeded"
        return resumed.session.status

    assert asyncio.run(resume()) == "completed"
    assert (tmp_path / "async-resume.txt").read_text(encoding="utf-8") == "done"


def test_async_resume_reregisters_a_custom_async_governed_tool(tmp_path: Path, capsys) -> None:
    runtime = AgentTrustRuntime(tmp_path, runtime_mode="noninteractive")
    called = False

    async def send(address: str) -> str:
        nonlocal called
        called = True
        return address.upper()

    async def create_pending():
        async with runtime.async_session(actor_id="alice") as session:
            guarded_send = govern_async(send, session=session, tool_name="async_send", default_effect="ask")
            with pytest.raises(ApprovalPending) as pending:
                await guarded_send("alice@example.com")
        return session, guarded_send, pending.value.approval_id

    session, guarded_send, approval_id = asyncio.run(create_pending())
    assert main(
        [
            "--project-root",
            str(tmp_path),
            "approvals",
            "approve",
            approval_id,
            "--reason",
            "reviewed",
        ]
    ) == 0
    capsys.readouterr()

    async def resume() -> str:
        async with await runtime.async_resume(
            session.run_id,
            resume_tools=[guarded_send],
        ) as resumed:
            outcome = await resumed.resume_pending_approval_async()
            assert outcome.outcome.result is not None
            assert outcome.outcome.result.output_preview == "'ALICE@EXAMPLE.COM'"
        return resumed.session.status

    assert asyncio.run(resume()) == "completed"
    assert called is True


def test_async_cancellation_records_a_failed_tool_call(tmp_path: Path) -> None:
    async def scenario() -> tuple[Path, str]:
        runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
        started = asyncio.Event()
        release = asyncio.Event()

        async with runtime.async_session() as session:
            async def wait_forever() -> str:
                started.set()
                await release.wait()
                return "done"

            guarded_wait = govern_async(wait_forever, session=session, tool_name="wait_forever", default_effect="allow")
            task = asyncio.create_task(guarded_wait())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert session.session.status == "failed"
            return session.run_dir, session.session.status

    run_dir, status = asyncio.run(scenario())

    assert status == "failed"
    statuses = [
        event["status"]
        for event in read_trace(run_dir / "trace.jsonl")
        if event["event_type"] == "tool_call_status_changed"
    ]
    assert statuses[-1] == "failed"


def test_async_session_rejects_sync_mutation_entry_points(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = AgentTrustRuntime(tmp_path, runtime_mode="test")
        async with runtime.async_session() as session:
            with pytest.raises(RuntimeError, match="execute_async"):
                session.execute("read_file", {"path": "README.md"})

    asyncio.run(scenario())
