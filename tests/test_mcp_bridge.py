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
        self.assertIn("x_slimyos", tools[0])
        self.assertIn("inputSchema", tools[0])

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
        self.assertEqual(result["structuredContent"]["disposition"], "blocked")

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
        self.assertEqual(result["structuredContent"]["disposition"], "approval_required")


if __name__ == "__main__":
    unittest.main()
