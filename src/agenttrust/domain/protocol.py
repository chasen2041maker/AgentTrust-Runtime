"""Versioned, portable governance request and response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from agenttrust.domain.models import ToolIntent
from agenttrust.domain.sessions import arguments_digest


POLICY_PROTOCOL_VERSION = "agenttrust.policy/v1"


@dataclass(frozen=True)
class Principal:
    """The human and agent identities behind one governed action."""

    actor_id: str
    agent_id: str | None = None
    roles: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"actor_id": self.actor_id, "agent_id": self.agent_id, "roles": list(self.roles)}


@dataclass(frozen=True)
class Action:
    """The portable description of a requested operation."""

    type: str
    tool: str
    risk_level: str = "unknown"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "tool": self.tool, "risk_level": self.risk_level}


@dataclass(frozen=True)
class Resource:
    """The primary resource affected by a governed action."""

    type: str
    id: str
    classification: str = "unclassified"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id, "classification": self.classification}


@dataclass(frozen=True)
class DecisionContext:
    """Execution context that may influence portable policy evaluation."""

    session_id: str | None = None
    runtime_mode: str = "normal"
    sandbox_profile: str = "standard"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "session_id": self.session_id,
            "runtime_mode": self.runtime_mode,
            "sandbox_profile": self.sandbox_profile,
        }


@dataclass(frozen=True)
class Obligation:
    """An enforcement requirement attached to a policy decision."""

    type: str
    parameters: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class DecisionRequest:
    """A versioned request accepted by policy evaluators beyond the built-in YAML engine."""

    protocol_version: str
    run_id: str
    tool_call_id: str
    principal: Principal
    action: Action
    resource: Resource
    context: DecisionContext
    arguments_digest: str
    attributes: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_intent(
        cls,
        intent: ToolIntent,
        *,
        actor_id: str = "local-user",
        agent_id: str | None = None,
        session_id: str | None = None,
        roles: tuple[str, ...] = (),
        sandbox_profile: str = "standard",
    ) -> "DecisionRequest":
        attributes = _policy_attributes(intent.arguments)
        resource = _resource_for(intent.tool_name, attributes)
        return cls(
            protocol_version=POLICY_PROTOCOL_VERSION,
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            principal=Principal(actor_id=actor_id, agent_id=agent_id, roles=roles),
            action=Action(type="tool.execute", tool=intent.tool_name),
            resource=resource,
            context=DecisionContext(session_id=session_id, runtime_mode=intent.runtime_mode, sandbox_profile=sandbox_profile),
            arguments_digest=arguments_digest(intent.arguments),
            attributes=attributes,
        )

    def to_intent(self) -> ToolIntent:
        """Provide the compatibility view required by the built-in YAML matcher."""

        return ToolIntent(
            run_id=self.run_id,
            tool_call_id=self.tool_call_id,
            tool_name=self.action.tool,
            arguments=dict(self.attributes),
            source="policy_protocol",
            runtime_mode=self.context.runtime_mode,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "principal": self.principal.to_dict(),
            "action": self.action.to_dict(),
            "resource": self.resource.to_dict(),
            "context": self.context.to_dict(),
            "arguments_digest": self.arguments_digest,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class DecisionResponse:
    """A portable policy evaluation result with explainable precedence metadata."""

    protocol_version: str
    effect: str
    reason: str
    policy_rule_id: str | None = None
    matched_rule_ids: tuple[str, ...] = ()
    obligations: tuple[Obligation, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "effect": self.effect,
            "reason": self.reason,
            "policy_rule_id": self.policy_rule_id,
            "matched_rule_ids": list(self.matched_rule_ids),
            "obligations": [obligation.to_dict() for obligation in self.obligations],
        }


def _policy_attributes(arguments: Mapping[str, Any]) -> dict[str, object]:
    allowed = {"path", "command", "argv", "server", "tool", "sandbox_profile"}
    return {key: value for key, value in arguments.items() if key in allowed}


def _resource_for(tool_name: str, attributes: Mapping[str, object]) -> Resource:
    path = attributes.get("path")
    if isinstance(path, str) and path:
        return Resource(type="file", id=path, classification="project-file")
    server = attributes.get("server")
    tool = attributes.get("tool")
    if isinstance(server, str) and isinstance(tool, str):
        return Resource(type="mcp_tool", id=f"{server}/{tool}")
    return Resource(type="tool", id=tool_name)
