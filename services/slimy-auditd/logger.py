"""
slimy-auditd — SlimyOS Audit Logger

Append-only event logger. Agents cannot edit their own history.
Writes JSONL (one JSON object per line) for tamper-evident logging.
"""

import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditLogger:
    """
    Append-only audit event logger.
    
    Writes events as JSONL to a log file.
    Each event gets a UUID and timestamp.
    """

    def __init__(self, log_dir: str = "~/.slimyos/audit"):
        self.log_dir = Path(os.path.expanduser(log_dir))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_log = self.log_dir / f"audit-{datetime.now().strftime('%Y%m%d')}.jsonl"
        self._events: list[dict] = []  # In-memory buffer for current session

    def log(
        self,
        event_type: str,
        agent_id: str,
        tool_name: str,
        task_id: str = "",
        agent_runtime: str = "unknown",
        tool_args: Optional[dict] = None,
        disposition: str = "",
        result: Optional[dict] = None,
        policy_rule: str = "",
        work_room: str = "",
        risk_level: str = "",
        files_changed: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Log an audit event. Returns the event dict."""
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_runtime": agent_runtime,
            "tool_name": tool_name,
            "tool_args": tool_args or {},
            "disposition": disposition,
            "result": result,
            "policy_rule": policy_rule,
            "work_room": work_room,
            "risk_level": risk_level,
            "files_changed": files_changed or [],
            "metadata": metadata or {},
        }

        # Append to file (append-only, never overwrite)
        with open(self._current_log, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Keep in memory for proof pack generation
        self._events.append(event)
        return event

    def get_events(self, task_id: Optional[str] = None) -> list[dict]:
        """Get events from memory, optionally filtered by task_id."""
        if task_id:
            return [e for e in self._events if e.get("task_id") == task_id]
        return list(self._events)

    def get_events_from_disk(self, date_str: Optional[str] = None) -> list[dict]:
        """Read events from disk log files."""
        events = []
        if date_str:
            log_file = self.log_dir / f"audit-{date_str}.jsonl"
            files = [log_file] if log_file.exists() else []
        else:
            files = sorted(self.log_dir.glob("audit-*.jsonl"))

        for f in files:
            with open(f, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        return events

    @property
    def log_path(self) -> str:
        return str(self._current_log)
