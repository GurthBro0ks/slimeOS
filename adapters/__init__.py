"""
SlimyOS Runtime Adapters — How external agents connect.

SlimyOS doesn't care which model is thinking.
It only cares what the agent is allowed to do.

Every agent runtime connects through the same interface:
  POST /tool/call  →  slimy-toold  →  policy check  →  execute  →  audit  →  result

Supported patterns:
1. Direct Python import (fastest — for agents running on same machine)
2. HTTP API (for remote agents, Hermes gateway, etc.)
3. MCP Server (for Claude Code, Cursor, any MCP client)
4. stdin/stdout JSON-RPC (for CLI agents like Codex)
"""

import json
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SlimyToolAPI:
    """
    Unified API that all adapters call.
    Wraps the tool broker with a clean interface.
    """

    def __init__(self, broker):
        self.broker = broker

    def call_tool(self, tool_name: str, tool_args: dict,
                  agent_id: str = "unknown", agent_runtime: str = "unknown",
                  task_id: str = "default") -> dict:
        result = self.broker.call(
            tool_name=tool_name, tool_args=tool_args,
            agent_id=agent_id, agent_runtime=agent_runtime, task_id=task_id,
        )
        return result.to_dict()

    def list_tools(self) -> list[str]:
        return self.broker.list_tools()

    def get_manifest(self, tool_name: str) -> dict | None:
        return self.broker.get_manifest(tool_name)


class HTTPAdapter(BaseHTTPRequestHandler):
    """
    HTTP API adapter for slimy-toold.
    
    Endpoints:
      GET  /tools          — list available tools
      GET  /tools/<name>   — get tool manifest
      POST /tools/<name>   — call a tool
      GET  /health         — health check
    """
    api: SlimyToolAPI = None

    def do_GET(self):
        if self.path == "/tools":
            self._json({"tools": self.api.list_tools()})
        elif self.path.startswith("/tools/"):
            name = self.path.split("/tools/")[1]
            manifest = self.api.get_manifest(name)
            if manifest:
                self._json(manifest)
            else:
                self._json({"error": f"Tool not found: {name}"}, 404)
        elif self.path == "/health":
            self._json({"status": "ok", "service": "slimy-toold"})
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path.startswith("/tools/"):
            name = self.path.split("/tools/")[1]
            body = self._read_body()
            result = self.api.call_tool(
                tool_name=name,
                tool_args=body.get("args", {}),
                agent_id=body.get("agent_id", "http-client"),
                agent_runtime=body.get("agent_runtime", "http"),
                task_id=body.get("task_id", "default"),
            )
            self._json(result)
        else:
            self._json({"error": "Not found"}, 404)

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length > 0 else {}

    def log_message(self, *a):
        pass


def mcp_tool_definitions(api: SlimyToolAPI) -> list[dict]:
    """
    Generate MCP-compatible tool definitions from slimy-toold manifests.
    
    This allows Claude Code, Cursor, or any MCP client to discover
    and call SlimyOS tools through the MCP protocol.
    
    Usage: register these as an MCP server in claude_desktop_config.json
    """
    tools = []
    for name in api.list_tools():
        manifest = api.get_manifest(name)
        if not manifest:
            continue
        tools.append({
            "name": f"slimyos_{name}",
            "description": f"[SlimyOS {manifest.get('work_room', '')}] {manifest.get('description', name)}. Risk: {manifest.get('risk_level', 'unknown')}. {'⚠️ Requires approval.' if manifest.get('requires_approval') else ''}",
            "input_schema": manifest.get("parameters", {"type": "object"}),
        })
    return tools


def jsonrpc_adapter(api: SlimyToolAPI):
    """
    stdin/stdout JSON-RPC adapter for CLI agents.
    
    Protocol:
      → {"method": "call", "params": {"tool": "read_file", "args": {"path": "..."}}, "id": 1}
      ← {"result": {"success": true, "output": "..."}, "id": 1}
      
      → {"method": "list", "id": 2}
      ← {"result": ["read_file", "write_file", ...], "id": 2}
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            method = msg.get("method", "")
            params = msg.get("params", {})
            msg_id = msg.get("id", 0)

            if method == "call":
                result = api.call_tool(
                    tool_name=params.get("tool", ""),
                    tool_args=params.get("args", {}),
                    agent_id=params.get("agent_id", "jsonrpc"),
                    agent_runtime=params.get("agent_runtime", "cli"),
                    task_id=params.get("task_id", "default"),
                )
                print(json.dumps({"result": result, "id": msg_id}), flush=True)
            elif method == "list":
                print(json.dumps({"result": api.list_tools(), "id": msg_id}), flush=True)
            elif method == "manifest":
                m = api.get_manifest(params.get("tool", ""))
                print(json.dumps({"result": m, "id": msg_id}), flush=True)
            else:
                print(json.dumps({"error": f"Unknown method: {method}", "id": msg_id}), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON"}), flush=True)
