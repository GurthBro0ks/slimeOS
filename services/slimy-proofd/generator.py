"""
slimy-proofd — SlimyOS Proof Pack Generator

Generates HTML proof reports from audit trails.
Every task should produce a readable, visual proof of what happened.

Proof packs contain:
- Timeline of events
- Files changed with diffs
- Screenshots (when available)
- Policy decisions (allowed/blocked/approved)
- Pass/fail badges
- Commands executed
- Approval events
"""

import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services.slimy_auditd.logger import AuditLogger


PROOF_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SlimyOS Proof Pack — {task_id}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    background: #0a0e1a; color: #e2e8f0; padding: 20px;
    max-width: 900px; margin: 0 auto;
  }}
  .header {{
    background: #111827; border: 1px solid #1e293b; border-radius: 12px;
    padding: 24px; margin-bottom: 20px; text-align: center;
  }}
  .header h1 {{ color: #06d6a0; font-size: 22px; margin-bottom: 8px; }}
  .header .subtitle {{ color: #64748b; font-size: 12px; }}
  .badge {{
    display: inline-block; padding: 4px 12px; border-radius: 6px;
    font-size: 12px; font-weight: 700; margin: 4px;
  }}
  .badge-success {{ background: #06d6a022; color: #06d6a0; border: 1px solid #06d6a044; }}
  .badge-failure {{ background: #ef444422; color: #ef4444; border: 1px solid #ef444444; }}
  .badge-blocked {{ background: #f59e0b22; color: #f59e0b; border: 1px solid #f59e0b44; }}
  .badge-pending {{ background: #7c3aed22; color: #7c3aed; border: 1px solid #7c3aed44; }}
  .stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 10px; margin-bottom: 20px;
  }}
  .stat {{
    background: #111827; border: 1px solid #1e293b; border-radius: 8px;
    padding: 16px; text-align: center;
  }}
  .stat .number {{ font-size: 28px; font-weight: 800; color: #06d6a0; }}
  .stat .label {{ font-size: 10px; color: #64748b; margin-top: 4px; text-transform: uppercase; }}
  .section {{
    background: #111827; border: 1px solid #1e293b; border-radius: 10px;
    padding: 16px; margin-bottom: 16px;
  }}
  .section h2 {{
    color: #06d6a0; font-size: 14px; margin-bottom: 12px;
    padding-bottom: 8px; border-bottom: 1px solid #1e293b;
  }}
  .event {{
    padding: 10px; border-left: 3px solid #1e293b; margin-bottom: 8px;
    font-size: 12px; line-height: 1.6;
  }}
  .event.allowed {{ border-left-color: #06d6a0; }}
  .event.blocked {{ border-left-color: #ef4444; }}
  .event.approval_required {{ border-left-color: #f59e0b; }}
  .event .time {{ color: #64748b; }}
  .event .tool {{ color: #7c3aed; font-weight: 700; }}
  .event .disposition {{ font-weight: 700; }}
  .event .disposition.allowed {{ color: #06d6a0; }}
  .event .disposition.blocked {{ color: #ef4444; }}
  .event .disposition.approval_required {{ color: #f59e0b; }}
  .event .rule {{ color: #64748b; font-style: italic; }}
  pre {{
    background: #0a0e1a; border: 1px solid #1e293b; border-radius: 6px;
    padding: 12px; font-size: 11px; overflow-x: auto; color: #94a3b8;
    margin: 8px 0;
  }}
  .footer {{
    text-align: center; padding: 20px; color: #64748b; font-size: 11px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>🐌 SlimyOS Proof Pack</h1>
  <div class="subtitle">Task: {task_id}</div>
  <div class="subtitle">{task_description}</div>
  <div style="margin-top: 12px;">
    <span class="badge badge-{status_class}">{status}</span>
    <span class="badge" style="background:#111827;color:#64748b;border:1px solid #1e293b">{agent_runtime}</span>
  </div>
  <div class="subtitle" style="margin-top: 8px;">
    {created_at} — Duration: {duration}s
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="number">{total_events}</div><div class="label">Events</div></div>
  <div class="stat"><div class="number" style="color:#06d6a0">{total_allowed}</div><div class="label">Allowed</div></div>
  <div class="stat"><div class="number" style="color:#ef4444">{total_blocked}</div><div class="label">Blocked</div></div>
  <div class="stat"><div class="number" style="color:#f59e0b">{total_approval}</div><div class="label">Approval</div></div>
  <div class="stat"><div class="number">{files_changed_count}</div><div class="label">Files Changed</div></div>
</div>

<div class="section">
  <h2>📋 Event Timeline</h2>
  {events_html}
</div>

{files_section}

<div class="section">
  <h2>📊 Raw Audit Data</h2>
  <pre>{raw_json}</pre>
</div>

<div class="footer">
  🐌 SlimyOS Habitat — Proof Pack v0.1<br>
  Generated {generated_at}
</div>

</body>
</html>"""


class ProofPackGenerator:
    """Generates HTML proof packs from audit events."""

    def __init__(self, output_dir: str = "~/.slimyos/proofs"):
        self.output_dir = Path(os.path.expanduser(output_dir))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        task_id: str,
        task_description: str,
        events: list[dict],
        agent_runtime: str = "unknown",
        status: str = "success",
    ) -> str:
        """
        Generate an HTML proof pack from audit events.
        Returns the path to the generated HTML file.
        """
        pack_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc)

        # Compute stats
        allowed = [e for e in events if e.get("disposition") == "allowed"]
        blocked = [e for e in events if e.get("disposition") == "blocked"]
        approval = [e for e in events if e.get("disposition") == "approval_required"]
        
        all_files = []
        for e in events:
            all_files.extend(e.get("files_changed", []))
        unique_files = list(set(all_files))

        # Duration
        if events:
            first_ts = events[0].get("timestamp", "")
            last_ts = events[-1].get("timestamp", "")
            try:
                t0 = datetime.fromisoformat(first_ts)
                t1 = datetime.fromisoformat(last_ts)
                duration = round((t1 - t0).total_seconds(), 1)
            except (ValueError, TypeError):
                duration = 0
        else:
            duration = 0

        # Build events HTML
        events_html_parts = []
        for e in events:
            disp = e.get("disposition", "")
            disp_class = disp if disp in ("allowed", "blocked", "approval_required") else ""
            tool_args_str = json.dumps(e.get("tool_args", {}), indent=None)[:200]
            
            events_html_parts.append(f"""
            <div class="event {disp_class}">
              <span class="time">{e.get('timestamp', '')[11:19]}</span>
              <span class="tool">{e.get('tool_name', '')}</span>
              <span class="disposition {disp_class}">[{disp.upper() if disp else e.get('event_type', '')}]</span>
              <span class="rule">{e.get('policy_rule', '')}</span>
              <div style="color:#64748b;font-size:11px;margin-top:2px;">
                args: {tool_args_str}
              </div>
              {"<div style='color:#ef4444;margin-top:2px;'>error: " + (e.get('result', {}) or {}).get('error', '') + "</div>" if (e.get('result', {}) or {}).get('error') else ""}
            </div>
            """)

        events_html = "\n".join(events_html_parts) if events_html_parts else "<div style='color:#64748b'>No events recorded.</div>"

        # Files section
        if unique_files:
            files_items = "\n".join(f"<li>{f}</li>" for f in unique_files)
            files_section = f"""
            <div class="section">
              <h2>📁 Files Changed</h2>
              <ul style="list-style:none;padding:0;">{files_items}</ul>
            </div>
            """
        else:
            files_section = ""

        # Status class
        status_map = {"success": "success", "failure": "failure", "blocked": "blocked", "approval_pending": "pending", "partial": "pending"}
        status_class = status_map.get(status, "pending")

        # Render
        html = PROOF_HTML_TEMPLATE.format(
            task_id=task_id,
            task_description=task_description or "No description",
            status=status.upper(),
            status_class=status_class,
            agent_runtime=agent_runtime,
            created_at=now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            duration=duration,
            total_events=len(events),
            total_allowed=len(allowed),
            total_blocked=len(blocked),
            total_approval=len(approval),
            files_changed_count=len(unique_files),
            events_html=events_html,
            files_section=files_section,
            raw_json=json.dumps(events, indent=2, default=str)[:5000],
            generated_at=now.isoformat(),
        )

        # Write
        pack_dir = self.output_dir / f"{task_id}-{pack_id}"
        pack_dir.mkdir(parents=True, exist_ok=True)
        
        html_path = pack_dir / "index.html"
        with open(html_path, "w") as f:
            f.write(html)

        # Also write raw JSON
        json_path = pack_dir / "events.jsonl"
        with open(json_path, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        # Write summary
        summary = {
            "pack_id": pack_id,
            "task_id": task_id,
            "task_description": task_description,
            "status": status,
            "created_at": now.isoformat(),
            "total_events": len(events),
            "total_allowed": len(allowed),
            "total_blocked": len(blocked),
            "total_approval": len(approval),
            "files_changed": unique_files,
            "duration_seconds": duration,
        }
        with open(pack_dir / "RESULT.json", "w") as f:
            json.dump(summary, f, indent=2)

        return str(html_path)
