# 🐌 SlimyOS Habitat

**A supervised autonomous Linux control plane where agents can research, code, browse, sandbox, assist, create proof packs, learn from failures, and be stopped or rolled back instantly.**

SlimyOS is not an AI desktop. It is not a chatbot shell. It is not a YOLO agent box.

SlimyOS is a **command center for trustworthy autonomy.**

## Core Principle

> The OS does not care which model is thinking.
> The OS only cares what the agent is allowed to do.

## What SlimyOS Is

A portable Linux overlay (runs on Mint, Ubuntu, Arch, NixOS) that provides:

| Component | Purpose |
|---|---|
| `slimy-policyd` | Deterministic policy engine — what is allowed, blocked, escalated, or sandboxed |
| `slimy-toold` | Tool broker — named, scoped, audited actions instead of raw shell |
| `slimy-auditd` | Append-only event logging with tamper detection |
| `slimy-proofd` | HTML proof pack generator — screenshots, diffs, timelines, pass/fail |
| `slimy-panicd` | Emergency stop — halt all agents, dump state, snapshot (future) |
| `slimy-snapshotd` | Btrfs/ZFS snapshot management before destructive ops (future) |
| `slimy-dashboard` | Mission Control web UI (future) |
| `slimy-phone` | Phone approval PWA (future) |

## What SlimyOS Is Not

- Not a new kernel or init system
- Not hardwired to any specific model or framework
- Not a self-modifying OS
- Not an unrestricted agent runtime

## Supported Agent Runtimes (all replaceable)

Hermes Agent, Claude Code, Codex CLI, OpenCode, Goose, Ollama, browser-use, trycua/cua, LangGraph, CrewAI, custom scripts.

None of these are the core. They are clients.

## Quick Start

```bash
# Clone
git clone https://github.com/slimyai/slimyos.git
cd slimyos

# Install (Python 3.10+)
pip install -e .

# Run smoke test
./scripts/smoke-test.sh

# See example proof pack
open examples/proof-pack/index.html
```

## Project Structure

```
slimyos/
├── docs/              # Architecture, threat model, roadmap
├── schemas/           # JSON schemas for all data types
├── services/          # Core services (policyd, toold, auditd, proofd)
├── policies/          # Policy files (default, dev-machine, nuc-agent)
├── tools/manifests/   # Tool definitions
├── gates/             # CI/CD safety gates
├── scripts/           # Install, smoke test, utilities
├── examples/          # Example proof packs
└── tests/             # Integration tests
```

## Phased Roadmap

| Phase | What | Status |
|---|---|---|
| 0 | Planning + threat model + schemas | ✅ |
| 1 | Portable overlay skeleton | ✅ |
| 2 | Policy engine + tool broker | ✅ |
| 3 | Coding Room | 🔲 |
| 4 | Browser Room | 🔲 |
| 5 | Sandbox Room | 🔲 |
| 6 | Mission Control Dashboard | 🔲 |
| 7 | Phone Supervisor | 🔲 |
| 8 | Host Desktop Room | 🔲 |
| 9 | Arch/Hyprland SlimyOS Edition | 🔲 |

## License

MIT
