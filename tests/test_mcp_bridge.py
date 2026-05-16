import json
import os
import unittest
from unittest.mock import patch

from adapters.mcp_server import BrokerUnavailableError, SlimyMCPServer


class MCPBridgeTests(unittest.TestCase):
    def test_initialize_shape(self):
        server = SlimyMCPServer()
        response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertIn("result", response)
        self.assertIn("serverInfo", response["result"])
        self.assertIn("capabilities", response["result"])
        self.assertIn("protocolVersion", response["result"])

    def test_initialize_string_id_preserved(self):
        server = SlimyMCPServer()
        response = server.handle_request({"jsonrpc": "2.0", "id": "abc-123", "method": "initialize", "params": {}})
        self.assertEqual(response["id"], "abc-123")

    def test_initialize_numeric_id_preserved(self):
        server = SlimyMCPServer()
        response = server.handle_request({"jsonrpc": "2.0", "id": 42, "method": "initialize", "params": {}})
        self.assertEqual(response["id"], 42)

    def test_tools_list_shape(self):
        server = SlimyMCPServer()

        with patch.object(
            server,
            "_http_get_json",
            return_value={
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read file",
                        "risk_level": "low",
                        "requires_approval": False,
                        "work_room": "code",
                        "action_level": 0,
                    }
                ]
            },
        ):
            response = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        tools = response["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "slimyos_read_file")
        self.assertIn("inputSchema", tools[0])
        self.assertNotIn("x_slimyos", tools[0])

    def test_tools_list_has_no_extra_keys(self):
        server = SlimyMCPServer()
        with patch.object(
            server,
            "_http_get_json",
            return_value={
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read",
                        "risk_level": "low",
                        "requires_approval": False,
                        "work_room": "code",
                    }
                ]
            },
        ):
            response = server.handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}})

        tool = response["result"]["tools"][0]
        allowed = {"name", "description", "inputSchema"}
        extra = set(tool.keys()) - allowed
        self.assertEqual(extra, set(), f"Tool has extra keys: {extra}")

    def test_fail_closed_when_broker_unreachable(self):
        server = SlimyMCPServer()
        with patch.object(server, "_http_get_json", side_effect=BrokerUnavailableError("down")):
            response = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32001)

    def test_fail_closed_call_when_broker_unreachable(self):
        server = SlimyMCPServer()
        with patch.object(server, "_http_post_json", side_effect=BrokerUnavailableError("down")):
            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 33,
                    "method": "tools/call",
                    "params": {"name": "slimyos_read_file", "arguments": {"path": "README.md"}},
                }
            )
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32001)

    def test_blocked_response_preserved(self):
        server = SlimyMCPServer()
        blocked = {
            "success": False,
            "disposition": "blocked",
            "policy_rule": "unknown_tool",
            "error": "Unknown tool",
        }
        with patch.object(server, "_http_post_json", return_value=blocked):
            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "slimyos_raw_shell", "arguments": {"command": "rm -rf /"}},
                }
            )
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("structuredContent", result)
        content_text = result["content"][0]["text"]
        content_data = json.loads(content_text)
        self.assertEqual(content_data["disposition"], "blocked")

    def test_approval_required_response_preserved(self):
        server = SlimyMCPServer()
        gated = {
            "success": False,
            "disposition": "approval_required",
            "policy_rule": "require_approval",
            "error": "APPROVAL REQUIRED",
        }
        with patch.object(server, "_http_post_json", return_value=gated):
            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "slimyos_git_commit", "arguments": {"repo_path": ".", "message": "x"}},
                }
            )
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("structuredContent", result)
        content_text = result["content"][0]["text"]
        content_data = json.loads(content_text)
        self.assertEqual(content_data["disposition"], "approval_required")

    def test_notification_returns_none(self):
        server = SlimyMCPServer()
        response = server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        self.assertIsNone(response)

    def test_ping(self):
        server = SlimyMCPServer()
        response = server.handle_request({"jsonrpc": "2.0", "id": "p1", "method": "ping"})
        self.assertEqual(response["id"], "p1")
        self.assertIn("result", response)

    def test_unknown_method_returns_jsonrpc_error(self):
        server = SlimyMCPServer()
        response = server.handle_request({"jsonrpc": "2.0", "id": 99, "method": "foo/bar"})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)
        self.assertIn("message", response["error"])
        allowed_error_keys = {"code", "message", "data"}
        extra = set(response["error"].keys()) - allowed_error_keys
        self.assertEqual(extra, set(), f"Error has extra keys: {extra}")

    def test_tools_call_content_shape(self):
        server = SlimyMCPServer()
        success_result = {"success": True, "output": "hello"}
        with patch.object(server, "_http_post_json", return_value=success_result):
            response = server.handle_request({
                "jsonrpc": "2.0",
                "id": 50,
                "method": "tools/call",
                "params": {"name": "slimyos_read_file", "arguments": {"path": "/tmp/test"}},
            })
        result = response["result"]
        self.assertIn("content", result)
        self.assertIn("isError", result)
        self.assertNotIn("structuredContent", result)
        self.assertIsInstance(result["content"], list)
        self.assertEqual(result["content"][0]["type"], "text")

    def test_tools_call_normalizes_claude_desktop_identity(self):
        server = SlimyMCPServer(agent_id="claude-desktop", agent_runtime="claude-desktop")
        captured = {}

        def fake_post(_url, payload):
            captured["payload"] = payload
            return {"success": False, "disposition": "approval_required", "policy_rule": "require_approval"}

        with patch.dict(
            os.environ,
            {
                "SLIMYOS_MCP_AGENT_ID": "claude-desktop",
                "SLIMYOS_MCP_AGENT_NAME": "claude-desktop",
            },
            clear=False,
        ), patch.object(server, "_http_post_json", side_effect=fake_post):
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 77,
                    "method": "tools/call",
                    "params": {"name": "slimyos_git_commit", "arguments": {"repo_path": ".", "message": "x"}},
                }
            )

        ci = captured["payload"]["client_identity"]
        self.assertEqual(ci["client_id"], "claude_desktop")
        self.assertEqual(ci["client_name"], "Claude Desktop")
        self.assertEqual(ci["transport"], "mcp_stdio")


if __name__ == "__main__":
    unittest.main()
