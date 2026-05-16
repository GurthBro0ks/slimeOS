#!/usr/bin/env python3
"""
slimy-toold HTTP API Server

Starts the tool broker as an HTTP API that any agent runtime can call.

  GET  /health           → health check
  GET  /tools            → list all tools with manifests
  GET  /tools/<name>     → get single tool manifest
  POST /tools/<name>     → call a tool (policy-checked, audited)
  GET  /audit/recent     → recent audit events
  GET  /state            → broker+hub state (tasks, agents, approvals)
  GET  /approvals        → list approval requests
  POST /panic            → panic stop
  POST /approve          → approve a pending request
  POST /deny             → deny a pending request

Start: python3 serve.py
Default: http://0.0.0.0:3003
"""

import http.server
import json
import os
import sys
import importlib.util
from urllib.parse import parse_qs, urlparse

SLIMYOS_HOME = os.environ.get("SLIMYOS_HOME", os.path.expanduser("~/.slimyos"))
# If running from repo, use repo root; if installed, use SLIMYOS_HOME
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(SCRIPT_DIR, "services")):
    PROJECT_ROOT = SCRIPT_DIR
elif os.path.exists(os.path.join(SLIMYOS_HOME, "services")):
    PROJECT_ROOT = SLIMYOS_HOME
else:
    PROJECT_ROOT = SCRIPT_DIR

sys.path.insert(0, PROJECT_ROOT)


def load_mod(name, relpath):
    path = os.path.join(PROJECT_ROOT, relpath)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Module not found: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load all services
engine_mod  = load_mod("services.slimy_policyd.engine", "services/slimy-policyd/engine.py")
logger_mod  = load_mod("services.slimy_auditd.logger", "services/slimy-auditd/logger.py")
broker_mod  = load_mod("services.slimy_toold.broker", "services/slimy-toold/broker.py")
safe_mod    = load_mod("services.slimy_toold.tools.safe_tools", "services/slimy-toold/tools/safe_tools.py")
coding_mod  = load_mod("services.slimy_toold.tools.coding_room", "services/slimy-toold/tools/coding_room.py")
browser_mod = load_mod("services.slimy_toold.tools.browser_room", "services/slimy-toold/tools/browser_room.py")
sandbox_mod = load_mod("services.slimy_toold.tools.sandbox_room", "services/slimy-toold/tools/sandbox_room.py")
desktop_mod = load_mod("services.slimy_toold.tools.desktop_room", "services/slimy-toold/tools/desktop_room.py")
ops_mod     = load_mod("services.slimy_toold.tools.ops_room", "services/slimy-toold/tools/ops_room.py")
hub_mod     = load_mod("services.slimy_hub", "services/slimy-hub/__init__.py")
memory_mod  = load_mod("services.slimy_memoryd", "services/slimy-memoryd/__init__.py")

# Initialize
policy_path = os.path.join(PROJECT_ROOT, "policies", "default.policy.json")
if os.path.exists(os.path.join(SLIMYOS_HOME, "config", "policy.json")):
    policy_path = os.path.join(SLIMYOS_HOME, "config", "policy.json")

policy = engine_mod.PolicyEngine(policy_path)
audit = logger_mod.AuditLogger(log_dir=os.path.join(SLIMYOS_HOME, "audit"))
broker = broker_mod.ToolBroker(
    policy_engine=policy, audit_logger=audit,
    manifests_dir=os.path.join(PROJECT_ROOT, "tools", "manifests"),
)
hub = hub_mod.Hub()
memory = memory_mod.FailureMemory(store_path=os.path.join(SLIMYOS_HOME, "memory"))

# Register all tool handlers
ALL_TOOLS = {}
for mod in [safe_mod, coding_mod, browser_mod, sandbox_mod, desktop_mod, ops_mod]:
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, dict) and all(callable(v) for v in obj.values()):
            ALL_TOOLS.update(obj)

for name, handler in ALL_TOOLS.items():
    broker.register_handler(name, handler)


class ToolAPIHandler(http.server.BaseHTTPRequestHandler):

    @staticmethod
    def _state_payload() -> dict:
        state = hub.snapshot()
        state["memory"] = memory.get_failure_summary()

        approval_state = broker.approvals_state()
        state["pending_approvals"] = approval_state["pending_approvals"]
        state["approvals_recent"] = approval_state["approvals_recent"]
        state["approvals"] = approval_state["approvals"]

        stats = state.get("stats", {})
        stats["pending_approvals"] = approval_state["approvals"]["pending_count"]
        stats["waiting_approval"] = approval_state["approvals"]["pending_count"]
        state["stats"] = stats
        return state

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._json({"status": "ok", "service": "slimy-toold", "tools": len(broker.list_tools()),
                         "panicked": hub.is_panicked})

        elif parsed.path == "/tools":
            tools = []
            for name in broker.list_tools():
                m = broker.get_manifest(name)
                tools.append({
                    "name": name,
                    "description": m.get("description", ""),
                    "risk_level": m.get("risk_level", ""),
                    "work_room": m.get("work_room", ""),
                    "requires_approval": m.get("requires_approval", False),
                    "action_level": m.get("action_level", 0),
                })
            self._json({"tools": tools, "count": len(tools)})

        elif parsed.path.startswith("/tools/"):
            name = parsed.path.split("/tools/")[1].split("?")[0]
            m = broker.get_manifest(name)
            if m:
                self._json(m)
            else:
                self._json({"error": f"Tool not found: {name}"}, 404)

        elif parsed.path == "/audit/recent":
            events = audit.get_events()[-50:]
            self._json({"events": events, "count": len(events)})

        elif parsed.path == "/state":
            self._json(self._state_payload())

        elif parsed.path == "/approvals":
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            limit_param = query.get("limit", ["100"])[0]
            try:
                limit = max(1, min(int(limit_param), 500))
            except ValueError:
                limit = 100
            approvals = broker.get_approvals(status=status, limit=limit)
            self._json({"approvals": approvals, "count": len(approvals), "status_filter": status or "all"})

        elif parsed.path == "/failures":
            self._json({"failures": memory.get_all_failures(), "rules": memory.get_learned_rules()})

        elif parsed.path == "/mcp/tools":
            # MCP-compatible tool list for Claude Code / Cursor
            tools = []
            for name in broker.list_tools():
                m = broker.get_manifest(name)
                if not m:
                    continue
                tools.append({
                    "name": f"slimyos_{name}",
                    "description": (
                        f"[SlimyOS {m.get('work_room','')}] {m.get('description', name)}. "
                        f"Risk: {m.get('risk_level','')}. "
                        f"{'Requires approval.' if m.get('requires_approval') else ''}"
                    ),
                    "input_schema": m.get("parameters", {"type": "object"}),
                })
            self._json({"tools": tools})

        else:
            self._json({"error": "Not found", "endpoints": [
                "GET /health", "GET /tools", "GET /tools/<name>",
                "POST /tools/<name>", "GET /audit/recent", "GET /state",
                "GET /approvals", "GET /failures", "GET /mcp/tools",
                "POST /panic", "POST /approve", "POST /deny",
            ]}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path.startswith("/tools/"):
            name = self.path.split("/tools/")[1].split("?")[0]
            # Strip slimyos_ prefix if present (from MCP calls)
            if name.startswith("slimyos_"):
                name = name[len("slimyos_"):]

            agent_id = body.get("agent_id", self.headers.get("X-Agent-Id", "http-client"))
            agent_runtime = body.get("agent_runtime", self.headers.get("X-Agent-Runtime", "http"))
            task_id = body.get("task_id", self.headers.get("X-Task-Id", "default"))
            tool_args = body.get("args", body.get("input", body.get("parameters", {})))
            client_identity = body.get("client_identity", {})

            result = broker.call(
                tool_name=name, tool_args=tool_args,
                agent_id=agent_id, agent_runtime=agent_runtime, task_id=task_id,
                client_identity=client_identity,
            )

            # Record failure if tool failed
            if not result.success and result.disposition == "allowed":
                memory.record_failure(
                    what_was_tried=f"Tool call: {name}({json.dumps(tool_args)[:200]})",
                    what_failed=result.error,
                    how_detected="runtime_error",
                    task_id=task_id, agent_id=agent_id, agent_runtime=agent_runtime,
                )

            self._json(result.to_dict())

        elif self.path == "/panic":
            reason = body.get("reason", "API panic stop")
            if hub.is_panicked:
                hub.resume()
                self._json({"ok": True, "action": "resumed"})
            else:
                hub.panic_stop(reason)
                self._json({"ok": True, "action": "panicked"})

        elif self.path == "/approve":
            approval_id = body.get("approval_id", body.get("request_id", ""))
            approved = body.get("approved", True)
            decided_by = body.get("decided_by", "api")
            req = broker.decide_approval(approval_id, bool(approved), decided_by)
            if req is None:
                self._json({"ok": False, "error": "unknown_approval_id", "approval_id": approval_id}, 404)
            else:
                self._json({"ok": True, "approval": req})

        elif self.path == "/deny":
            approval_id = body.get("approval_id", body.get("request_id", ""))
            decided_by = body.get("decided_by", "api")
            req = broker.decide_approval(approval_id, False, decided_by)
            if req is None:
                self._json({"ok": False, "error": "unknown_approval_id", "approval_id": approval_id}, 404)
            else:
                self._json({"ok": True, "approval": req})

        elif self.path == "/tasks":
            task = hub.create_task(
                task_id=body.get("task_id", ""),
                description=body.get("description", ""),
                agent_id=body.get("agent_id", ""),
                agent_runtime=body.get("agent_runtime", ""),
                work_room=body.get("work_room", "code"),
            )
            self._json(task.to_dict())

        elif self.path == "/agents/register":
            agent = hub.register_agent(
                agent_id=body.get("agent_id", ""),
                runtime=body.get("runtime", "unknown"),
            )
            self._json(agent.to_dict())

        else:
            self._json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Id, X-Agent-Runtime, X-Task-Id")
        self.end_headers()

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def log_message(self, format, *args):
        # Quiet by default; uncomment for debug
        # print(f"[toold] {args[0]}")
        pass


def main():
    port = int(os.environ.get("SLIMYOS_TOOLD_PORT", 3003))
    server = http.server.HTTPServer(("0.0.0.0", port), ToolAPIHandler)

    tool_count = len(broker.list_tools())
    print(f"""
═══════════════════════════════════════
  🐌 SlimyOS Tool Broker API
  http://localhost:{port}
═══════════════════════════════════════

  {tool_count} tools loaded
  Policy: {policy_path}
  Audit:  {audit.log_path}

  Endpoints:
    GET  /health          — status check
    GET  /tools           — list all tools
    POST /tools/<name>    — call a tool
    GET  /state           — broker + hub state
    GET  /approvals       — approval queue
    POST /panic           — emergency stop
    POST /approve         — approve request
    POST /deny            — deny request
    GET  /mcp/tools       — MCP-compatible tool list

  Press Ctrl+C to stop.
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTool broker stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
