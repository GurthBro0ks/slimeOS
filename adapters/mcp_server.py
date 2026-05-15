"""SlimyOS MCP stdio bridge.

This adapter exposes Tool Broker tools to MCP clients while preserving
policy outcomes (allowed, blocked, approval_required).
"""

from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


class BrokerUnavailableError(RuntimeError):
    pass


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

    def handle_request(self, message: dict[str, Any]) -> dict[str, Any]:
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if method == "initialize":
            return self._result(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "slimyos-mcp-bridge",
                        "version": "0.1.0",
                    },
                },
            )

        if method == "tools/list":
            try:
                tools_payload = self._http_get_json(f"{self.broker_url}/tools")
            except BrokerUnavailableError as exc:
                return self._error(msg_id, -32001, f"Broker unreachable: {exc}")

            tools = []
            for tool in tools_payload.get("tools", []):
                name = tool.get("name", "")
                metadata = {
                    "risk_level": tool.get("risk_level", "unknown"),
                    "requires_approval": bool(tool.get("requires_approval", False)),
                    "work_room": tool.get("work_room", "unknown"),
                    "action_level": tool.get("action_level", 0),
                }
                desc = tool.get("description", name)
                description = (
                    f"[SlimyOS {metadata['work_room']}] {desc}. "
                    f"Risk: {metadata['risk_level']}. "
                    f"{'Requires approval.' if metadata['requires_approval'] else 'Policy-gated.'}"
                )
                tools.append(
                    {
                        "name": f"slimyos_{name}",
                        "description": description,
                        "inputSchema": {"type": "object"},
                        "x_slimyos": metadata,
                    }
                )

            return self._result(msg_id, {"tools": tools})

        if method == "tools/call":
            call_name = params.get("name", "")
            tool_name = call_name.replace("slimyos_", "", 1)
            arguments = params.get("arguments", {})

            payload = {
                "args": arguments,
                "agent_id": params.get("agent_id", self.agent_id),
                "agent_runtime": params.get("agent_runtime", self.agent_runtime),
                "task_id": params.get("task_id", "mcp-task"),
            }
            try:
                tool_result = self._http_post_json(f"{self.broker_url}/tools/{tool_name}", payload)
            except BrokerUnavailableError as exc:
                return self._error(msg_id, -32001, f"Broker unreachable: {exc}")

            is_error = not bool(tool_result.get("success", False))
            body = {
                "content": [{"type": "text", "text": json.dumps(tool_result)}],
                "structuredContent": tool_result,
                "isError": is_error,
            }
            return self._result(msg_id, body)

        return self._error(msg_id, -32601, f"Method not found: {method}")

    def _http_get_json(self, url: str) -> dict[str, Any]:
        try:
            with urlrequest.urlopen(url, timeout=3.0) as response:
                return json.loads(response.read())
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BrokerUnavailableError(str(exc)) from exc

    def _http_post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
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

    @staticmethod
    def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": code,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hostname": socket.gethostname(),
            },
        }


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

        response = server.handle_request(message)
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
    run_stdio_server(server)


if __name__ == "__main__":
    main()
