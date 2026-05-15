# SlimyOS Agent Habitat — Project Direction

## Identity

SlimyOS Habitat is a supervised autonomous Linux workbench where agents can
research, code, browse, use sandboxes, assist with the desktop, operate services
through approved wrappers, create proof packs, learn from failures, and be stopped
or rolled back instantly.

## Core Decisions

1. **Overlay first.** SlimyOS is a portable Linux control plane, not a distro.
2. **Distro later.** Arch/Hyprland edition ships after the control plane proves itself.
3. **Policy is core.** slimy-policyd is the most important component.
4. **Tool broker required.** No raw shell. Named, scoped, audited actions only.
5. **Proof packs are first-class.** HTML reports with screenshots, diffs, timelines.
6. **Panic stop required.** Hardware or software kill switch, instant agent halt.
7. **Phone approval desired.** Remote supervision is a signature feature.
8. **Failure memory is v0.1.** The system improves by remembering what went wrong.
9. **No freeform sudo.** Agents request specific allowed actions from wrappers.
10. **Runtimes are replaceable.** Hermes, Claude, Codex, etc. are clients, not core.

## What Makes This Different

The perfect autonomous environment is not the one where the agent has the most power.

It is the one where the agent has:
- enough power to be useful
- enough limits to be safe
- enough memory to improve
- enough visibility to be trusted
- enough recovery to survive mistakes

## Anti-Patterns (what SlimyOS is NOT)

- An AI-themed desktop skin
- A chatbot pasted onto Linux
- A self-modifying OS
- An unrestricted YOLO agent machine
- A custom kernel or display server
- Hardwired to any single model or framework
