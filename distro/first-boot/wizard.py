#!/usr/bin/env python3
"""
SlimyOS First-Boot Wizard

Runs after first install. Guides the user through:
1. Welcome + voice introduction (optional, via Piper TTS)
2. Network check
3. Ollama model pull
4. API key setup (OpenAI / Anthropic / OpenRouter)
5. Permission tier selection
6. First agent conversation
7. Dashboard launch

For now this is a skeleton — real TTS and Ollama integration
come when deployed on actual hardware.
"""

import os, sys, json

SLIMYOS_HOME = os.path.expanduser("~/.slimyos")

def main():
    print()
    print("═" * 50)
    print("  🐌 Welcome to SlimyOS Habitat")
    print("  A command center for trustworthy autonomy.")
    print("═" * 50)
    print()
    print("  This wizard will set up your environment.")
    print()
    
    # Step 1: Check Python
    print("  ✅ Python:", sys.version.split()[0])
    
    # Step 2: Check directories
    for d in ["config", "audit", "proofs", "memory", "secrets"]:
        p = os.path.join(SLIMYOS_HOME, d)
        os.makedirs(p, exist_ok=True)
    print("  ✅ Directories created")
    
    # Step 3: API keys (placeholder)
    print()
    print("  To use cloud AI models, add API keys to:")
    print(f"    {SLIMYOS_HOME}/secrets/api_keys.json")
    print()
    print("  Format:")
    print("  {")
    print("    \"anthropic\": \"sk-ant-...\"," )
    print("    \"openai\": \"sk-...\"," )
    print("    \"openrouter\": \"sk-or-...\"")
    print("  }")
    print()
    
    # Step 4: Permission tier
    print("  Default permission tier: APPROVE (all dangerous actions need approval)")
    print("  Change in: {}/config/policy.json".format(SLIMYOS_HOME))
    print()
    
    # Step 5: Launch dashboard
    print("  To start Mission Control:")
    print("    slimyos-dashboard")
    print("    → http://localhost:3002")
    print()
    print("═" * 50)
    print("  🐌 Setup complete. Welcome to SlimyOS.")
    print("═" * 50)

if __name__ == "__main__":
    main()
