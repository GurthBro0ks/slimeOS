# SlimyOS MCP for Claude Code

Use this MCP server command:

`/home/mint/Projects/slimeOS/scripts/run-mcp-server.sh`

Environment:
- `SLIMYOS_TOOLD_URL=http://localhost:3003`
- `SLIMYOS_MCP_AGENT_ID=claude-code`
- `SLIMYOS_MCP_AGENT_RUNTIME=claude-code`

All tool calls still flow through Tool Broker policy and audit.

Status: MANUAL_REQUIRED if no safe file-based config path is detected.