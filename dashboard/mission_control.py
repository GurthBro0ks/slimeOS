"""
SlimyOS Mission Control — The Signature Dashboard

A real HTTP server that shows:
- System status (normal / panicked)
- Active agents and their state
- Running tasks with current tool
- Pending approvals with approve/deny buttons
- Live event stream
- Proof pack links
- PANIC STOP button
- Stats overview

Start: python3 dashboard/mission_control.py
Open:  http://localhost:3002

Designed for desktop and phone — responsive layout.
Phone can approve/deny/panic from anywhere.
"""

import http.server
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

# Add project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Import hub (lazy — created on first access)
_hub = None

def get_hub():
    global _hub
    if _hub is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "services.slimy_hub",
            os.path.join(PROJECT_ROOT, "services", "slimy-hub", "__init__.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _hub = mod.Hub()
        # Seed demo data
        _seed_demo_data(_hub)
    return _hub


def _seed_demo_data(hub):
    """Pre-populate with realistic demo data."""
    hub.register_agent("coding-agent-01", "claude-code")
    hub.register_agent("research-agent-01", "hermes")
    hub.register_agent("ops-agent-01", "codex")
    
    t1 = hub.create_task("fix-hero-accent", "Fix dashboard hero accent line #00ff00 → #06d6a0",
                         "coding-agent-01", "claude-code", "code")
    hub.complete_task("fix-hero-accent", "completed", "/proofs/fix-hero-accent/index.html")
    
    t2 = hub.create_task("research-hyprland", "Research Hyprland v0.53 breaking changes",
                         "research-agent-01", "hermes", "research")
    hub.update_task("research-hyprland", current_tool="browser_read_page", tool_calls=12)
    
    hub.request_approval("research-hyprland", "research-agent-01", "browser_submit",
                         {"url": "https://github.com/issues/new", "form_id": "issue-form"},
                         "Browser submit requires approval", "high")
    
    hub.request_approval("fix-nuc2-pm2", "ops-agent-01", "restart_service",
                         {"service_name": "slimy-bot-v2"},
                         "Service restart requires approval", "high")


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SlimyOS Mission Control</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  background: #0a0e1a; color: #e2e8f0; min-height: 100vh;
}
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&display=swap');

.topbar {
  background: #111827; border-bottom: 2px solid #1e293b;
  padding: 12px 20px; display: flex; align-items: center;
  justify-content: space-between; position: sticky; top: 0; z-index: 100;
}
.topbar .logo { display:flex; align-items:center; gap:10px; }
.topbar .logo-icon {
  width:36px; height:36px; border-radius:8px; display:flex;
  align-items:center; justify-content:center; font-size:18px;
  background: linear-gradient(135deg, #06d6a0, #7c3aed);
}
.topbar h1 { font-size:16px; font-weight:800; color:#06d6a0; }
.topbar .status { font-size:11px; color:#64748b; }

.panic-btn {
  background: #ef4444; color: white; border: 2px solid #dc2626;
  padding: 10px 24px; border-radius: 8px; font-weight: 800;
  font-size: 14px; cursor: pointer; font-family: inherit;
  text-transform: uppercase; letter-spacing: 2px;
  animation: pulse-red 2s infinite;
}
.panic-btn:hover { background: #dc2626; }
.panic-btn.panicked { background: #064e3b; border-color: #06d6a0; color: #06d6a0; animation: none; }

@keyframes pulse-red { 0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,0.4)} 50%{box-shadow:0 0 0 8px rgba(239,68,68,0)} }

.panic-banner {
  background: #ef444433; border-bottom: 2px solid #ef4444;
  padding: 12px 20px; text-align: center; font-weight: 700;
  color: #ef4444; font-size: 14px; display: none;
}
.panic-banner.active { display: block; }

.grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px; padding: 16px; max-width: 1400px; margin: 0 auto;
}

.card {
  background: #111827; border: 1px solid #1e293b; border-radius: 10px;
  overflow: hidden;
}
.card-header {
  padding: 12px 16px; border-bottom: 1px solid #1e293b;
  display: flex; justify-content: space-between; align-items: center;
}
.card-header h2 { font-size: 13px; color: #06d6a0; font-weight: 700; }
.card-header .count {
  background: #06d6a022; color: #06d6a0; padding: 2px 8px;
  border-radius: 6px; font-size: 11px; font-weight: 700;
}
.card-body { padding: 12px 16px; max-height: 400px; overflow-y: auto; }

.stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: 8px; padding: 16px; max-width: 1400px; margin: 0 auto;
}
.stat {
  background: #111827; border: 1px solid #1e293b; border-radius: 8px;
  padding: 12px; text-align: center;
}
.stat .num { font-size: 24px; font-weight: 800; color: #06d6a0; }
.stat .lbl { font-size: 9px; color: #64748b; text-transform: uppercase; margin-top: 2px; }

.agent-row, .task-row, .event-row {
  padding: 10px 0; border-bottom: 1px solid #1e293b15;
  font-size: 12px;
}
.agent-row:last-child, .task-row:last-child, .event-row:last-child { border:none; }

.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 10px; font-weight: 700;
}
.badge-green { background:#06d6a022; color:#06d6a0; }
.badge-red { background:#ef444422; color:#ef4444; }
.badge-yellow { background:#f59e0b22; color:#f59e0b; }
.badge-purple { background:#7c3aed22; color:#7c3aed; }
.badge-gray { background:#64748b22; color:#64748b; }

.approval-card {
  background: #1a2236; border: 1px solid #f59e0b44; border-radius: 8px;
  padding: 12px; margin-bottom: 10px;
}
.approval-card .tool { color: #f59e0b; font-weight: 700; }
.approval-card .reason { color: #94a3b8; font-size: 11px; margin: 6px 0; }
.approval-btns { display: flex; gap: 8px; margin-top: 8px; }
.btn-approve {
  background: #06d6a0; color: #0a0e1a; border: none; padding: 8px 20px;
  border-radius: 6px; font-weight: 700; cursor: pointer; font-family: inherit;
  font-size: 12px; flex: 1;
}
.btn-deny {
  background: #ef444433; color: #ef4444; border: 1px solid #ef444466;
  padding: 8px 20px; border-radius: 6px; font-weight: 700; cursor: pointer;
  font-family: inherit; font-size: 12px; flex: 1;
}
.btn-approve:hover { background: #05c090; }
.btn-deny:hover { background: #ef444455; }

.event-row .time { color: #64748b; }
.event-row .type { color: #7c3aed; font-weight: 600; }

::-webkit-scrollbar { width:5px } 
::-webkit-scrollbar-track { background:transparent }
::-webkit-scrollbar-thumb { background:#1e293b; border-radius:3px }
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">
    <div class="logo-icon">🐌</div>
    <div>
      <h1>SlimyOS Mission Control</h1>
      <div class="status" id="status-text">Loading...</div>
    </div>
  </div>
  <button class="panic-btn" id="panic-btn" onclick="togglePanic()">
    🚨 PANIC STOP
  </button>
</div>

<div class="panic-banner" id="panic-banner">
  🚨 PANIC STOP ACTIVE — All agents halted. Click RESUME to continue.
</div>

<div class="stats" id="stats"></div>

<div class="grid">
  <!-- Pending Approvals -->
  <div class="card" style="border-color:#f59e0b44">
    <div class="card-header">
      <h2>⏳ Pending Approvals</h2>
      <span class="count" id="approval-count">0</span>
    </div>
    <div class="card-body" id="approvals"></div>
  </div>

  <!-- Active Tasks -->
  <div class="card">
    <div class="card-header">
      <h2>📋 Tasks</h2>
      <span class="count" id="task-count">0</span>
    </div>
    <div class="card-body" id="tasks"></div>
  </div>

  <!-- Agents -->
  <div class="card">
    <div class="card-header">
      <h2>🤖 Agents</h2>
      <span class="count" id="agent-count">0</span>
    </div>
    <div class="card-body" id="agents"></div>
  </div>

  <!-- Event Stream -->
  <div class="card" style="grid-column: span 2;">
    <div class="card-header">
      <h2>📡 Event Stream</h2>
      <span class="count" id="event-count">0</span>
    </div>
    <div class="card-body" id="events" style="max-height:300px"></div>
  </div>
</div>

<script>
const STATE_BADGE = {
  running: '<span class="badge badge-green">running</span>',
  completed: '<span class="badge badge-green">completed</span>',
  waiting_approval: '<span class="badge badge-yellow">⏳ waiting</span>',
  failed: '<span class="badge badge-red">failed</span>',
  panicked: '<span class="badge badge-red">🚨 panicked</span>',
  pending: '<span class="badge badge-gray">pending</span>',
  idle: '<span class="badge badge-gray">idle</span>',
  working: '<span class="badge badge-green">working</span>',
  stopped: '<span class="badge badge-red">stopped</span>',
};

function render(data) {
  // Stats
  const s = data.stats;
  document.getElementById('stats').innerHTML = [
    stat(s.total_tasks, 'Tasks'), stat(s.running, 'Running', '#06d6a0'),
    stat(s.waiting_approval, 'Awaiting', '#f59e0b'), stat(s.completed, 'Done', '#06d6a0'),
    stat(s.failed, 'Failed', '#ef4444'), stat(s.pending_approvals, 'Approvals', '#f59e0b'),
    stat(s.total_agents, 'Agents'),
  ].join('');

  // Status
  const statusEl = document.getElementById('status-text');
  if (data.panicked) {
    statusEl.textContent = '🚨 PANIC STOP ACTIVE';
    statusEl.style.color = '#ef4444';
    document.getElementById('panic-banner').classList.add('active');
    document.getElementById('panic-btn').classList.add('panicked');
    document.getElementById('panic-btn').textContent = '✅ RESUME';
  } else {
    statusEl.textContent = `Online — ${s.running} running, ${s.pending_approvals} pending`;
    statusEl.style.color = '#64748b';
    document.getElementById('panic-banner').classList.remove('active');
    document.getElementById('panic-btn').classList.remove('panicked');
    document.getElementById('panic-btn').textContent = '🚨 PANIC STOP';
  }

  // Approvals
  const approvalsEl = document.getElementById('approvals');
  const pendingApprovals = data.pending_approvals || [];
  document.getElementById('approval-count').textContent = pendingApprovals.length;
  if (pendingApprovals.length === 0) {
    approvalsEl.innerHTML = '<div style="color:#64748b;font-size:12px;padding:8px">No pending approvals</div>';
  } else {
    approvalsEl.innerHTML = pendingApprovals.map(a => `
      <div class="approval-card">
        <div><span class="tool">${a.tool_name}</span> <span class="badge badge-yellow">${a.risk_level}</span></div>
        <div class="reason">${a.reason}</div>
        <div style="font-size:10px;color:#64748b">Agent: ${a.agent_id} · Task: ${a.task_id}</div>
        <div style="font-size:10px;color:#64748b;margin-top:4px">Args: ${JSON.stringify(a.tool_args).substring(0,80)}</div>
        <div class="approval-btns">
          <button class="btn-approve" onclick="decide('${a.request_id}',true)">✓ Approve</button>
          <button class="btn-deny" onclick="decide('${a.request_id}',false)">✕ Deny</button>
        </div>
      </div>
    `).join('');
  }

  // Tasks
  document.getElementById('task-count').textContent = data.tasks.length;
  document.getElementById('tasks').innerHTML = data.tasks.map(t => `
    <div class="task-row">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong style="color:#e2e8f0">${t.task_id}</strong>
        ${STATE_BADGE[t.state] || t.state}
      </div>
      <div style="color:#94a3b8;font-size:11px;margin-top:4px">${t.description}</div>
      <div style="font-size:10px;color:#64748b;margin-top:4px">
        Agent: ${t.agent_id} · Room: ${t.work_room} · Calls: ${t.tool_calls}
        ${t.current_tool ? ' · Current: <span style="color:#7c3aed">' + t.current_tool + '</span>' : ''}
        ${t.proof_pack_path ? ' · <a href="'+t.proof_pack_path+'" style="color:#06d6a0">📋 Proof</a>' : ''}
      </div>
    </div>
  `).join('') || '<div style="color:#64748b;font-size:12px">No tasks</div>';

  // Agents
  document.getElementById('agent-count').textContent = data.agents.length;
  document.getElementById('agents').innerHTML = data.agents.map(a => `
    <div class="agent-row">
      <div style="display:flex;justify-content:space-between">
        <strong>${a.agent_id}</strong>
        ${STATE_BADGE[a.state] || a.state}
      </div>
      <div style="font-size:10px;color:#64748b">Runtime: ${a.runtime} · Calls: ${a.total_calls}</div>
    </div>
  `).join('');

  // Events
  const events = data.recent_events || [];
  document.getElementById('event-count').textContent = events.length;
  document.getElementById('events').innerHTML = events.slice().reverse().map(e => `
    <div class="event-row">
      <span class="time">${(e.timestamp||'').substring(11,19)}</span>
      <span class="type">${e.type}</span>
      <span style="color:#94a3b8;font-size:11px">${JSON.stringify(e.data||{}).substring(0,120)}</span>
    </div>
  `).join('') || '<div style="color:#64748b;font-size:12px">No events yet</div>';
}

function stat(n, label, color) {
  return `<div class="stat"><div class="num" style="color:${color||'#06d6a0'}">${n||0}</div><div class="lbl">${label}</div></div>`;
}

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const data = await r.json();
    render(data);
  } catch(e) { console.error(e); }
}

async function decide(requestId, approved) {
  await fetch('/api/approve', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({request_id: requestId, approved: approved}),
  });
  fetchState();
}

async function togglePanic() {
  await fetch('/api/panic', {method:'POST'});
  fetchState();
}

// Poll every 2 seconds
fetchState();
setInterval(fetchState, 2000);
</script>
</body>
</html>"""


class MissionControlHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for Mission Control."""
    
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == "/api/state":
            hub = get_hub()
            self.send_json(hub.snapshot())
        elif self.path.startswith("/api/proofs"):
            self.send_json({"proofs": []})  # Future: list proof packs
        else:
            self.send_error(404)
    
    def do_POST(self):
        if self.path == "/api/approve":
            body = self._read_body()
            hub = get_hub()
            req = hub.decide_approval(
                body.get("request_id", ""),
                body.get("approved", False),
                "dashboard",
            )
            self.send_json({"ok": req is not None, "request": req.to_dict() if req else None})
        elif self.path == "/api/panic":
            hub = get_hub()
            if hub.is_panicked:
                hub.resume()
                self.send_json({"ok": True, "action": "resumed"})
            else:
                hub.panic_stop("Dashboard panic button pressed")
                self.send_json({"ok": True, "action": "panicked"})
        else:
            self.send_error(404)
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())
    
    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))
    
    def log_message(self, format, *args):
        # Suppress default logging noise
        pass


def main():
    port = int(os.environ.get("SLIMYOS_PORT", 3002))
    server = http.server.HTTPServer(("0.0.0.0", port), MissionControlHandler)
    print(f"""
═══════════════════════════════════════
  🐌 SlimyOS Mission Control
  http://localhost:{port}
═══════════════════════════════════════
  
  Dashboard ready. Open in your browser.
  Press Ctrl+C to stop.
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMission Control stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
