"""Minimal JSON-RPC stdio client for a local MCP server."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from queue import Queue
import subprocess
from threading import Thread
from typing import Mapping


class McpTransportError(RuntimeError):
    """Raised when a local MCP stdio transport cannot complete a request."""


class McpProtocolError(RuntimeError):
    """Raised when a local MCP server returns an invalid JSON-RPC response."""


@dataclass(frozen=True)
class McpServerConfig:
    """A launchable local MCP server configuration discovered from disk."""

    name: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    config_path: Path


@dataclass(frozen=True)
class McpToolDescriptor:
    """The trusted subset of a `tools/list` entry."""

    name: str
    description: str
    input_schema: dict[str, object]


class McpStdioClient:
    """Launch one local MCP server only after an outer trust gate permits it."""

    def __init__(self, config: McpServerConfig, timeout_seconds: float = 10.0) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._request_id = 0

    def __enter__(self) -> McpStdioClient:
        environment = {**_base_environment(), **self._config.env}
        try:
            self._process = subprocess.Popen(
                [self._config.command, *self._config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                shell=False,
                env=environment,
            )
        except OSError as exc:
            raise McpTransportError(f"failed to launch MCP server {self._config.name}: {exc}") from exc
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agenttrust-runtime", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1)
        self._process = None

    def list_tools(self) -> list[McpToolDescriptor]:
        result = self.request("tools/list", {})
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise McpProtocolError("MCP tools/list response requires a tools array")
        descriptors: list[McpToolDescriptor] = []
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                continue
            name = raw_tool.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = raw_tool.get("description", "")
            schema = raw_tool.get("inputSchema", {})
            descriptors.append(
                McpToolDescriptor(
                    name=name,
                    description=str(description),
                    input_schema=dict(schema) if isinstance(schema, dict) else {},
                )
            )
        return descriptors

    def call_tool(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)})

    def notify(self, method: str, params: Mapping[str, object]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def request(self, method: str, params: Mapping[str, object]) -> dict[str, object]:
        self._request_id += 1
        request_id = self._request_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        while True:
            response = self._read_response()
            if response.get("id") != request_id:
                continue
            error = response.get("error")
            if isinstance(error, dict):
                raise McpProtocolError(str(error.get("message", "MCP JSON-RPC error")))
            result = response.get("result")
            if not isinstance(result, dict):
                raise McpProtocolError(f"MCP {method} response requires an object result")
            return dict(result)

    def _write(self, payload: Mapping[str, object]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise McpTransportError("MCP server stdin is unavailable")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise McpTransportError(f"MCP server write failed: {exc}") from exc

    def _read_response(self) -> dict[str, object]:
        process = self._require_process()
        stdout = process.stdout
        if stdout is None:
            raise McpTransportError("MCP server stdout is unavailable")
        lines: Queue[str] = Queue(maxsize=1)
        reader = Thread(target=lambda: lines.put(stdout.readline()), daemon=True)
        reader.start()
        reader.join(self._timeout_seconds)
        if reader.is_alive():
            raise McpTransportError(f"MCP server timed out after {self._timeout_seconds:g} seconds")
        line = lines.get()
        if not line:
            return_code = process.poll()
            raise McpTransportError(f"MCP server closed stdout (return code: {return_code})")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpProtocolError("MCP server returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise McpProtocolError("MCP server returned an invalid JSON-RPC message")
        return dict(payload)

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None:
            raise McpTransportError("MCP server has not been started")
        return self._process


def _base_environment() -> dict[str, str]:
    import os

    return dict(os.environ)
