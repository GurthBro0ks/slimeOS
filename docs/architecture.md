# SlimyOS Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                   Agent Runtimes (replaceable)            │
│  Hermes │ Claude Code │ Codex │ OpenCode │ Goose │ ...   │
└────────────────────────┬─────────────────────────────────┘
                         │ tool calls (JSON-RPC / MCP)
┌────────────────────────▼─────────────────────────────────┐
│                    slimy-toold (Tool Broker)              │
│  Receives tool requests → checks policy → executes →     │
│  audits → returns result                                 │
└──────┬──────────┬──────────┬──────────┬──────────────────┘
       │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼─────┐
  │ Policy │ │ Audit  │ │Proof │ │ Memory  │
  │ Engine │ │ Logger │ │ Pack │ │ Store   │
  └────────┘ └────────┘ └──────┘ └─────────┘

┌──────────────────────────────────────────────────────────┐
│                      Work Rooms                          │
│  Research │ Code │ Browser │ Sandbox │ Desktop │ Ops     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                   Recovery Layer                         │
│  Btrfs snapshots │ Rollback │ Panic stop │ Remote audit  │
└──────────────────────────────────────────────────────────┘
```

## Data Flow

1. Agent runtime sends a tool call to `slimy-toold`
2. `slimy-toold` loads the tool manifest
3. `slimy-toold` asks `slimy-policyd` if the action is allowed
4. Policy returns: ALLOW, BLOCK, APPROVE_REQUIRED, SANDBOX, or SNAPSHOT_FIRST
5. If ALLOW: tool executes, result returned, audit event written
6. If BLOCK: rejection returned, audit event written
7. If APPROVE_REQUIRED: approval request queued, agent waits
8. On task completion: proof pack generated from audit trail

## Key Design Rules

- **No raw shell.** Every action goes through slimy-toold.
- **No freeform sudo.** Privileged actions use scoped wrappers.
- **Append-only audit.** Agents cannot edit their own history.
- **Snapshot before destroy.** Destructive ops require filesystem snapshot.
- **Fail closed.** Unknown actions are blocked by default.

## Work Rooms

Each room is a permission boundary with its own tools, risk level, and proof requirements.

| Room | Risk | Tools | Proof Required |
|---|---|---|---|
| Research | Low | browser-use (read-only), PDF reader, search | Minimal |
| Code | Medium | git, gh, tests, linters, editors | Full (diff, tests, screenshots) |
| Browser | Medium | browser-use, Playwright, approved profiles | Screenshots, form audit |
| Sandbox | Medium | trycua/cua, containers, bubblewrap | Trajectory capture |
| Desktop | High | ydotool, PipeWire, Hyprland IPC, AT-SPI2 | Full session recording |
| Ops | High | service wrappers, Docker, PM2 | Before/after proof |

## Action Levels

| Level | What | Example |
|---|---|---|
| 0 | Observe | Read file, list directory, check status |
| 1 | Draft | Create plan, suggest changes |
| 2 | Edit workspace | Modify files in approved paths |
| 3 | Run tests | Execute test suites, builds |
| 4 | Use browser | Search, read pages, fill drafts |
| 5 | Use sandbox | GUI tasks in isolated container |
| 6 | Use host desktop | Real mouse/keyboard on host |
| 7 | Request sudo wrapper | Scoped privileged action |
