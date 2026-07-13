"""Compatibility exports for the filesystem sandbox adapter."""

from agenttrust.adapters.sandbox.filesystem import PathSandbox
from agenttrust.domain.decisions import SandboxDecision

__all__ = ["PathSandbox", "SandboxDecision"]
