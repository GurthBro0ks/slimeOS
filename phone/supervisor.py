"""
SlimyOS Phone Supervisor — PWA for remote approval/control.

This is the same Mission Control API consumed by a mobile-optimized
PWA interface. Key features:
- Approve/deny pending actions
- Panic stop from phone
- View task screenshots
- Open proof reports
- Send new prompts to agents

Implementation: thin wrapper that serves a mobile-optimized HTML
pointing at the same /api/* endpoints as Mission Control.
"""

PHONE_PWA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0a0e1a">
<title>SlimyOS</title>
<link rel="manifest" href="/phone/manifest.json">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, 'JetBrains Mono', monospace;
  background: #0a0e1a; color: #e2e8f0;
  -webkit-user-select: none; user-select: none;
  min-height: 100vh; padding-bottom: env(safe-area-inset-bottom, 20px);
}

.header {
  background: #111827; padding: 16px 20px; padding-top: max(16px, env(safe-area-inset-top));
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 2px solid #1e293b; position: sticky; top: 0; z-index: 10;
}
.header h1 { font-size: 18px; color: #06d6a0; font-weight: 800; }
.header .dot { width:8px; height:8px; border-radius:50%; background:#06d6a0; }
.header .dot.panic { background:#ef4444; animation: blink 1s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }

.panic-bar {
  padding: 16px; display: flex; gap: 12px;
}
.panic-btn {
  flex: 1; padding: 16px; border-radius: 12px; font-weight: 800;
  font-size: 16px; font-family: inherit; cursor: pointer; border: none;
  text-transform: uppercase; letter-spacing: 1px;
}
.panic-btn.stop { background: #ef4444; color: white; }
.panic-btn.resume { background: #064e3b; color: #06d6a0; border: 2px solid #06d6a0; }

.section { padding: 0 16px; margin-bottom: 16px; }
.section-title {
  font-size: 13px; color: #64748b; font-weight: 700;
  text-transform: uppercase; letter-spacing: 1px;
  padding: 12px 0 8px;
}

.approval-item {
  background: #1a2236; border: 1px solid #f59e0b44; border-radius: 12px;
  padding: 16px; margin-bottom: 12px;
}
.approval-item .tool { color: #f59e0b; font-weight: 700; font-size: 15px; }
.approval-item .detail { color: #94a3b8; font-size: 12px; margin: 8px 0; line-height: 1.5; }
.approval-btns { display: flex; gap: 10px; }
.approval-btns button {
  flex: 1; padding: 14px; border-radius: 10px; font-weight: 700;
  font-size: 15px; font-family: inherit; cursor: pointer; border: none;
}
.btn-yes { background: #06d6a0; color: #0a0e1a; }
.btn-no { background: #ef444433; color: #ef4444; border: 1px solid #ef444466; }

.task-item {
  background: #111827; border: 1px solid #1e293b; border-radius: 10px;
  padding: 14px; margin-bottom: 8px;
}
.task-item .name { font-weight: 700; font-size: 14px; }
.task-item .meta { color: #64748b; font-size: 11px; margin-top: 4px; }

.empty { color: #64748b; font-size: 13px; padding: 20px 0; text-align: center; }
.badge {
  display: inline-block; padding: 3px 8px; border-radius: 4px;
  font-size: 10px; font-weight: 700; margin-left: 6px;
}
.b-g { background:#06d6a022; color:#06d6a0; }
.b-y { background:#f59e0b22; color:#f59e0b; }
.b-r { background:#ef444422; color:#ef4444; }
</style>
</head>
<body>

<div class="header">
  <h1>🐌 SlimyOS</h1>
  <div class="dot" id="dot"></div>
</div>

<div class="panic-bar">
  <button class="panic-btn stop" id="panic-btn" onclick="togglePanic()">🚨 PANIC STOP</button>
</div>

<div class="section">
  <div class="section-title">Pending Approvals <span id="a-count"></span></div>
  <div id="approvals"></div>
</div>

<div class="section">
  <div class="section-title">Active Tasks</div>
  <div id="tasks"></div>
</div>

<script>
const API = window.location.origin.replace(':3003', ':3002');

async function load() {
  try {
    const r = await fetch(API + '/api/state');
    const d = await r.json();
    
    const dot = document.getElementById('dot');
    const btn = document.getElementById('panic-btn');
    if (d.panicked) {
      dot.classList.add('panic');
      btn.className = 'panic-btn resume';
      btn.textContent = '✅ RESUME';
    } else {
      dot.classList.remove('panic');
      btn.className = 'panic-btn stop';
      btn.textContent = '🚨 PANIC STOP';
    }
    
    const pa = d.pending_approvals || [];
    document.getElementById('a-count').textContent = pa.length ? `(${pa.length})` : '';
    document.getElementById('approvals').innerHTML = pa.length ? pa.map(a => `
      <div class="approval-item">
        <div class="tool">${a.tool_name} <span class="badge b-y">${a.risk_level}</span></div>
        <div class="detail">${a.reason}<br>Agent: ${a.agent_id} · Task: ${a.task_id}</div>
        <div class="approval-btns">
          <button class="btn-yes" onclick="decide('${a.request_id}',true)">✓ Approve</button>
          <button class="btn-no" onclick="decide('${a.request_id}',false)">✕ Deny</button>
        </div>
      </div>
    `).join('') : '<div class="empty">No pending approvals ✓</div>';
    
    const badgeMap = {running:'b-g',completed:'b-g',waiting_approval:'b-y',failed:'b-r',panicked:'b-r'};
    document.getElementById('tasks').innerHTML = (d.tasks||[]).map(t => `
      <div class="task-item">
        <div class="name">${t.task_id} <span class="badge ${badgeMap[t.state]||'b-g'}">${t.state}</span></div>
        <div class="meta">${t.description}</div>
        <div class="meta">Agent: ${t.agent_id} · Room: ${t.work_room} · Calls: ${t.tool_calls}</div>
      </div>
    `).join('') || '<div class="empty">No tasks</div>';
  } catch(e) { console.error(e); }
}

async function decide(id, approved) {
  await fetch(API + '/api/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({request_id:id, approved}),
  });
  load();
  if (navigator.vibrate) navigator.vibrate(approved ? [50] : [50,50,50]);
}

async function togglePanic() {
  await fetch(API + '/api/panic', {method:'POST'});
  load();
  if (navigator.vibrate) navigator.vibrate([200,100,200]);
}

load();
setInterval(load, 2000);
</script>
</body>
</html>"""

PWA_MANIFEST = {
    "name": "SlimyOS Supervisor",
    "short_name": "SlimyOS",
    "start_url": "/phone/",
    "display": "standalone",
    "background_color": "#0a0e1a",
    "theme_color": "#0a0e1a",
    "description": "Remote supervisor for SlimyOS autonomous agents",
    "icons": []
}
