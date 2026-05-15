#!/bin/bash
# ═══════════════════════════════════════
# SlimyOS Habitat — Portable Overlay Install
# ═══════════════════════════════════════
#
# Installs SlimyOS control plane on any existing Linux.
# Does NOT replace your OS. Does NOT need root for core.
# Does NOT modify system config.
#
# Works on: Ubuntu, Mint, Arch, Fedora, NixOS
#
# Usage: ./install-overlay.sh
# ═══════════════════════════════════════

set -euo pipefail

SLIMYOS_HOME="${SLIMYOS_HOME:-$HOME/.slimyos}"
SLIMYOS_REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "═══════════════════════════════════════"
echo "  🐌 SlimyOS Habitat — Overlay Install"
echo "═══════════════════════════════════════"
echo ""
echo "  Install location: $SLIMYOS_HOME"
echo "  Source: $SLIMYOS_REPO"
echo ""

# ═══ Create directory structure ═══
echo "── Creating directories ──"
mkdir -p "$SLIMYOS_HOME"/{config,audit,proofs,memory,secrets,logs}
mkdir -p "$SLIMYOS_HOME"/bin

# ═══ Copy core services ═══
echo "── Installing services ──"
cp -r "$SLIMYOS_REPO/services" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/tools" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/policies" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/schemas" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/dashboard" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/phone" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/adapters" "$SLIMYOS_HOME/"
cp -r "$SLIMYOS_REPO/gates" "$SLIMYOS_HOME/"

# ═══ Default policy ═══
echo "── Setting up default policy ──"
if [ ! -f "$SLIMYOS_HOME/config/policy.json" ]; then
    cp "$SLIMYOS_REPO/policies/default.policy.json" "$SLIMYOS_HOME/config/policy.json"
    echo "  Created default policy at $SLIMYOS_HOME/config/policy.json"
    echo "  Edit this file to customize agent permissions."
else
    echo "  Policy already exists, skipping."
fi

# ═══ Create launcher scripts ═══
echo "── Creating launcher scripts ──"

cat > "$SLIMYOS_HOME/bin/slimyos-dashboard" << 'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")/../dashboard"
exec python3 mission_control.py "$@"
LAUNCHER

cat > "$SLIMYOS_HOME/bin/slimyos-panic" << 'LAUNCHER'
#!/bin/bash
# Emergency stop — halt all SlimyOS services
echo "🚨 SlimyOS PANIC STOP"
curl -s -X POST http://localhost:3002/api/panic 2>/dev/null && echo "  Agents halted via dashboard." || true
# Also stop systemd user services if they exist
systemctl --user stop slimyos-hub.service 2>/dev/null || true
systemctl --user stop slimyos-hermes.service 2>/dev/null || true
echo "  Panic stop complete. Check dashboard for status."
LAUNCHER

cat > "$SLIMYOS_HOME/bin/slimyos-status" << 'LAUNCHER'
#!/bin/bash
echo "🐌 SlimyOS Habitat Status"
echo "========================="
echo ""
echo "Dashboard: $(curl -s http://localhost:3002/health 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status","offline"))' 2>/dev/null || echo 'offline')"
echo "Config:    $HOME/.slimyos/config/policy.json"
echo "Audit:     $HOME/.slimyos/audit/"
echo "Proofs:    $HOME/.slimyos/proofs/"
echo "Memory:    $HOME/.slimyos/memory/"
echo ""
echo "Tools:     $(ls $HOME/.slimyos/tools/manifests/*.tool.json 2>/dev/null | wc -l) registered"
echo "Failures:  $(wc -l < $HOME/.slimyos/memory/failures.jsonl 2>/dev/null || echo 0) recorded"
echo "Rules:     $(python3 -c 'import json;print(len(json.load(open("'$HOME'/.slimyos/memory/learned_rules.json"))))' 2>/dev/null || echo 0) learned"
LAUNCHER

cat > "$SLIMYOS_HOME/bin/slimyos-test" << 'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")/.."
exec python3 -m pytest tests/ -v "$@" 2>/dev/null || python3 tests/test_integration.py "$@"
LAUNCHER

chmod +x "$SLIMYOS_HOME/bin/"*

# ═══ Add to PATH ═══
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q "slimyos" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# SlimyOS Habitat" >> "$SHELL_RC"
        echo 'export PATH="$HOME/.slimyos/bin:$PATH"' >> "$SHELL_RC"
        echo "  Added to PATH in $SHELL_RC"
    fi
fi

# ═══ Discover host ═══
echo ""
echo "── Host Discovery ──"
echo "  OS:       $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"' || uname -s)"
echo "  Kernel:   $(uname -r)"
echo "  Python:   $(python3 --version 2>/dev/null || echo 'NOT FOUND')"
echo "  Git:      $(git --version 2>/dev/null || echo 'NOT FOUND')"
echo "  Docker:   $(docker --version 2>/dev/null || echo 'not installed')"
echo "  ydotool:  $(which ydotool 2>/dev/null || echo 'not installed')"
echo "  Hyprland: $(Hyprland --version 2>&1 | head -1 2>/dev/null || echo 'not installed')"

# ═══ Done ═══
echo ""
echo "═══════════════════════════════════════"
echo "  🐌 SlimyOS Habitat installed!"
echo ""
echo "  Commands:"
echo "    slimyos-dashboard  — Start Mission Control"
echo "    slimyos-status     — Check system status"
echo "    slimyos-panic      — Emergency stop all agents"
echo "    slimyos-test       — Run integration tests"
echo ""
echo "  Start dashboard:"
echo "    slimyos-dashboard"
echo "    → http://localhost:3002"
echo "═══════════════════════════════════════"
