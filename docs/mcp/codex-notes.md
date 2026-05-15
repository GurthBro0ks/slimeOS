# Codex MCP Notes

SlimyOS MCP bridge can be used by Codex-compatible MCP clients.

Server command:

```bash
/home/mint/Projects/slimeOS/scripts/run-mcp-server.sh
```

Recommended environment:
- `SLIMYOS_TOOLD_URL=http://localhost:3003`
- `SLIMYOS_MCP_AGENT_ID=codex`
- `SLIMYOS_MCP_AGENT_RUNTIME=codex`

Behavior guarantees:
- MCP bridge is a proxy, not an execution bypass.
- Tool calls continue through Tool Broker policy and audit trail.
- Dangerous actions remain blocked or approval-gated.

Not automated:
- No provider login flows.
- No Hermes auth automation.
- No privileged host changes.
