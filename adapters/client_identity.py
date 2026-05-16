"""Client identity model for SlimyOS.

A small, stable identity envelope for tool calls that answers:
- who/what called the tool?
- through what transport?
- from what source?

Privacy rule: never include private chat text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClientIdentity:
    """Identity envelope for a tool-calling client."""

    client_id: str = "unknown"
    client_name: str = "Unknown Client"
    client_kind: str = "unknown"
    transport: str = "unknown"
    session_id: str = ""
    request_id: str = ""
    user_visible_source: str = ""
    started_at: str = ""
    repo_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "client_kind": self.client_kind,
            "transport": self.transport,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "user_visible_source": self.user_visible_source,
            "started_at": self.started_at,
            "repo_path": self.repo_path,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClientIdentity":
        return cls(
            client_id=d.get("client_id", "unknown"),
            client_name=d.get("client_name", "Unknown Client"),
            client_kind=d.get("client_kind", "unknown"),
            transport=d.get("transport", "unknown"),
            session_id=d.get("session_id", ""),
            request_id=d.get("request_id", ""),
            user_visible_source=d.get("user_visible_source", ""),
            started_at=d.get("started_at", ""),
            repo_path=d.get("repo_path", ""),
            metadata=dict(d.get("metadata", {})),
        )

    @classmethod
    def from_env(cls) -> "ClientIdentity":
        """Build identity from environment variables (MCP bridge context)."""
        import os
        return cls(
            client_id=os.environ.get("SLIMYOS_MCP_AGENT_ID", "mcp-client"),
            client_name=os.environ.get("SLIMYOS_MCP_AGENT_NAME", "MCP Client"),
            client_kind=os.environ.get("SLIMYOS_MCP_AGENT_KIND", "bridge"),
            transport=os.environ.get("SLIMYOS_MCP_TRANSPORT", "mcp_stdio"),
            session_id=os.environ.get("SLIMYOS_MCP_SESSION_ID", ""),
            request_id=os.environ.get("SLIMYOS_MCP_REQUEST_ID", ""),
            user_visible_source=os.environ.get("SLIMYOS_MCP_USER_VISIBLE_SOURCE", ""),
            started_at=os.environ.get("SLIMYOS_MCP_STARTED_AT", ""),
            repo_path=os.environ.get("SLIMYOS_REPO_PATH", ""),
        )


# Predefined identities for known clients
CLAUDE_DESKTOP = ClientIdentity(
    client_id="claude_desktop",
    client_name="Claude Desktop",
    client_kind="desktop_app",
    transport="mcp_stdio",
    user_visible_source="Claude Desktop MCP",
)

CLAUDE_CODE = ClientIdentity(
    client_id="claude_code",
    client_name="Claude Code",
    client_kind="cli",
    transport="mcp_stdio",
    user_visible_source="Claude Code MCP",
)

OPENCODE = ClientIdentity(
    client_id="opencode",
    client_name="OpenCode",
    client_kind="cli",
    transport="mcp_stdio",
    user_visible_source="OpenCode MCP",
)

CODEX = ClientIdentity(
    client_id="codex",
    client_name="Codex CLI",
    client_kind="cli",
    transport="mcp_stdio",
    user_visible_source="Codex CLI MCP",
)
