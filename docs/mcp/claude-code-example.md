# Claude Code MCP Example

Use the SlimyOS MCP bridge as a local stdio server:

```json
{
  "mcpServers": {
    "slimyos": {
      "command": "/home/mint/Projects/slimeOS/scripts/run-mcp-server.sh",
      "args": [],
      "env": {
        "SLIMYOS_TOOLD_URL": "http://localhost:3003",
        "SLIMYOS_MCP_AGENT_ID": "claude-code",
        "SLIMYOS_MCP_AGENT_RUNTIME": "claude-code"
      }
    }
  }
}
```

Notes:
- This MCP server does not execute tools directly.
- Every tool call proxies to SlimyOS Tool Broker (`slimy-toold`).
- Policy enforcement remains active.
- Blocked tools remain blocked.
- Approval-gated tools remain approval-gated.
- Hermes auth/proxy state is unrelated to MCP bridge startup.

Operator sanity checks:

```bash
./scripts/slimyos-mcp-doctor.sh
./scripts/slimyos-mcp-healthline.sh
```

Both commands are dry-run checks and do not overwrite client configs by default.
