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

Use the doctor workflow before wiring production configs:

```bash
./scripts/slimyos-mcp-doctor.sh
./scripts/slimyos-mcp-healthline.sh
```

To generate config snippets:

```bash
./scripts/slimyos-mcp-configure.sh --write-snippets
```

To check install status:

```bash
./scripts/slimyos-mcp-configure.sh --status
```

Codex config is classified as MANUAL_REQUIRED since no safe file-based config
path is confidently detected. Use the notes above to configure manually.
