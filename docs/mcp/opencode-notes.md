# OpenCode MCP Notes

To wire OpenCode to SlimyOS MCP:

1. Start Tool Broker (`python3 serve.py`) and Dashboard (`python3 dashboard/mission_control.py`).
2. Configure OpenCode MCP with command:

```bash
/home/mint/Projects/slimeOS/scripts/run-mcp-server.sh
```

Optional environment values:
- `SLIMYOS_TOOLD_URL=http://localhost:3003`
- `SLIMYOS_MCP_AGENT_ID=opencode`
- `SLIMYOS_MCP_AGENT_RUNTIME=opencode`

Security behavior:
- No raw shell is exposed by this bridge.
- All actions still flow through: policy -> broker -> audit.
- Blocked/approval-required responses are returned transparently.

Hermes note:
- Hermes login/proxy auth is optional and not required for MCP bridging.

Recommended dry-run validation:

```bash
./scripts/slimyos-mcp-doctor.sh
./scripts/slimyos-mcp-healthline.sh
```
