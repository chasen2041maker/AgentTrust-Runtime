"""Minimal JSON-RPC stdio client for a local MCP server."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
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


@dataclass(frozen=True)
class McpLaunchMetadata:
    """Non-secret metadata describing the stdio process launch boundary."""

    environment_mode: str
    configured_environment_keys: tuple[str, ...]
    inherited_environment_keys: tuple[str, ...]
    working_directory_source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "mcp_environment_mode": self.environment_mode,
            "mcp_configured_env_keys": list(self.configured_environment_keys),
            "mcp_configured_env_count": len(self.configured_environment_keys),
            "mcp_inherited_env_keys": list(self.inherited_environment_keys),
            "mcp_inherited_env_count": len(self.inherited_environment_keys),
            "mcp_working_directory_source": self.working_directory_source,
        }


class McpStdioClient:
    """Launch one local MCP server only after an outer trust gate permits it."""

    def __init__(self, config: McpServerConfig, timeout_seconds: float = 10.0) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._environment, inherited_keys = build_mcp_launch_environment(config.env)
        self._working_directory = config.config_path.parent.resolve()
        self._launch_metadata = McpLaunchMetadata(
            environment_mode="allowlisted",
            configured_environment_keys=tuple(sorted(config.env)),
            inherited_environment_keys=inherited_keys,
            working_directory_source="config_directory",
        )

    @property
    def launch_metadata(self) -> McpLaunchMetadata:
        """Return the non-secret launch policy used for this client process."""

        return self._launch_metadata

    def __enter__(self) -> McpStdioClient:
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
                env=self._environment,
                cwd=self._working_directory,
                close_fds=True,
            )
        except OSError as exc:
            raise McpTransportError(f"failed to launch MCP server {self._config.name}: {exc}") from exc
        try:
            self.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agenttrust-runtime", "version": "0.7.0"},
                },
            )
            self.notify("notifications/initialized", {})
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Terminate a launched process after a failed handshake or completed call."""

        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        except OSError:
            # The process may have exited between poll() and terminate().
            return

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


_MCP_INHERITED_ENVIRONMENT_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
)


def build_mcp_launch_environment(
    configured_environment: Mapping[str, str],
    parent_environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Use only runtime prerequisites plus values explicitly present in MCP config.

    This prevents ambient credentials from the agent host process reaching a
    local MCP subprocess. Server-specific credentials remain an explicit part
    of the inspected MCP configuration instead of an implicit inheritance.
    """

    parent = os.environ if parent_environment is None else parent_environment
    inherited = {
        key: value
        for key, value in parent.items()
        if key.upper() in _MCP_INHERITED_ENVIRONMENT_KEYS
    }
    environment = {**inherited, **dict(configured_environment)}
    return environment, tuple(sorted(inherited))
