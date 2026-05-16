"""SlimyOS MCP stdio bridge.

Strict MCP/JSON-RPC 2.0 stdio server compatible with Claude Desktop.

Safety rules:
- stdout contains ONLY valid JSON-RPC 2.0 protocol messages.
- All logs, diagnostics, tracebacks go to stderr.
- Notifications (messages without 'id') produce no stdout response.
- Error responses use strict JSON-RPC shape (code, message, optional data).
- Fail closed when Tool Broker is unreachable.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


class BrokerUnavailableError(RuntimeError):
    pass


def _log_stderr(msg: str) -> None:
    print(f"[slimyos-mcp] {msg}", file=sys.stderr, flush=True)


class SlimyMCPServer:
    def __init__(
        self,
        broker_url: str = "http://localhost:3003",
        agent_id: str = "mcp-client",
        agent_runtime: str = "mcp-stdio",
    ):
        self.broker_url = broker_url.rstrip("/")
        self.agent_id = agent_id
        self.agent_runtime = agent_runtime

    def handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if msg_id is None and "method" in message:
            return self._handle_notification(method, params)

        if method == "initialize":
            return self._result(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "slimyos-mcp-bridge",
                        "version": "0.2.0",
                    },
                },
            )

        if method == "ping":
            return self._result(msg_id, {})

        if method == "tools/list":
            try:
                tools_payload = self._http_get_json(f"{self.broker_url}/tools")
            except BrokerUnavailableError as exc:
                return self._error(msg_id, -32001, f"Broker unreachable: {exc}")

            tools = []
            for tool in tools_payload.get("tools", []):
                name = tool.get("name", "")
                risk = tool.get("risk_level", "unknown")
                approval = bool(tool.get("requires_approval", False))
                work_room = tool.get("work_room", "unknown")
                desc = tool.get("description", name)
                description = (
                    f"[SlimyOS {work_room}] {desc}. "
                    f"Risk: {risk}. "
                    f"{'Requires approval.' if approval else 'Policy-gated.'}"
                )
                tools.append(
                    {
                        "name": f"slimyos_{name}",
                        "description": description,
                        "inputSchema": {"type": "object"},
                    }
                )

            return self._result(msg_id, {"tools": tools})

        if method == "tools/call":
            call_name = params.get("name", "")
            tool_name = call_name.replace("slimyos_", "", 1)
            arguments = params.get("arguments", {})

            # Build client identity from env vars
            client_identity = {
                "client_id": os.environ.get("SLIMYOS_MCP_AGENT_ID", self.agent_id),
                "client_name": os.environ.get("SLIMYOS_MCP_AGENT_NAME", self.agent_id),
                "client_kind": os.environ.get("SLIMYOS_MCP_AGENT_KIND", "bridge"),
                "transport": os.environ.get("SLIMYOS_MCP_TRANSPORT", self.agent_runtime),
                "session_id": os.environ.get("SLIMYOS_MCP_SESSION_ID", ""),
                "request_id": os.environ.get("SLIMYOS_MCP_REQUEST_ID", ""),
                "user_visible_source": os.environ.get("SLIMYOS_MCP_USER_VISIBLE_SOURCE", ""),
                "started_at": os.environ.get("SLIMYOS_MCP_STARTED_AT", ""),
                "repo_path": os.environ.get("SLIMYOS_REPO_PATH", ""),
            }

            payload = {
                "args": arguments,
                "agent_id": self.agent_id,
                "agent_runtime": self.agent_runtime,
                "task_id": "mcp-task",
                "client_identity": client_identity,
            }
            try:
                tool_result = self._http_post_json(
                    f"{self.broker_url}/tools/{tool_name}", payload
                )
            except BrokerUnavailableError as exc:
                return self._error(msg_id, -32001, f"Broker unreachable: {exc}")

            is_error = not bool(tool_result.get("success", False))
            body = {
                "content": [
                    {"type": "text", "text": json.dumps(tool_result)}
                ],
                "isError": is_error,
            }
            return self._result(msg_id, body)

        return self._error(msg_id, -32601, f"Method not found: {method}")

    def _handle_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        _log_stderr(f"notification: {method}")

    @staticmethod
    def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    def _http_get_json(self, url: str) -> dict[str, Any]:
        try:
            with urlrequest.urlopen(url, timeout=3.0) as response:
                return json.loads(response.read())
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BrokerUnavailableError(str(exc)) from exc

    def _http_post_json(
        self, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        request = urlrequest.Request(
            url,
            method="POST",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(request, timeout=5.0) as response:
                return json.loads(response.read())
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BrokerUnavailableError(str(exc)) from exc


def run_stdio_server(server: SlimyMCPServer) -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            print(json.dumps(response), flush=True)
            continue

        try:
            response = server.handle_request(message)
        except Exception as exc:
            _log_stderr(f"handler error: {exc}\n{traceback.format_exc()}")
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": "Internal error"},
            }

        if response is not None:
            print(json.dumps(response), flush=True)


def main() -> None:
    broker_url = os.environ.get("SLIMYOS_TOOLD_URL", "http://localhost:3003")
    agent_id = os.environ.get("SLIMYOS_MCP_AGENT_ID", "mcp-client")
    agent_runtime = os.environ.get("SLIMYOS_MCP_AGENT_RUNTIME", "mcp-stdio")
    server = SlimyMCPServer(
        broker_url=broker_url,
        agent_id=agent_id,
        agent_runtime=agent_runtime,
    )
    _log_stderr(f"starting slimyos-mcp-bridge broker={broker_url}")
    run_stdio_server(server)


if __name__ == "__main__":
    main()
