"""
slimy-hub — SlimyOS Central State Manager & Event Bus

The hub is the nervous system. Every service connects here.
It maintains:
- Active tasks and their state
- Agent registry  
- Approval queue
- Live event stream (for dashboard/phone)
- Panic state
- Budget tracking
"""

import json
import uuid
import threading
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable


class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    PANICKED = "panicked"


class AgentState(Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    STOPPED = "stopped"


@dataclass
class Task:
    task_id: str
    description: str
    agent_id: str
    agent_runtime: str
    work_room: str
    state: TaskState = TaskState.PENDING
    created_at: str = ""
    updated_at: str = ""
    tool_calls: int = 0
    tool_calls_allowed: int = 0
    tool_calls_blocked: int = 0
    tool_calls_approval: int = 0
    current_tool: str = ""
    files_changed: list = field(default_factory=list)
    proof_pack_path: str = ""
    error: str = ""

    def to_dict(self):
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class Agent:
    agent_id: str
    runtime: str
    state: AgentState = AgentState.IDLE
    current_task: str = ""
    total_calls: int = 0
    registered_at: str = ""

    def to_dict(self):
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass 
class ApprovalRequest:
    request_id: str
    task_id: str
    agent_id: str
    tool_name: str
    tool_args: dict
    reason: str
    risk_level: str
    status: str = "pending"  # pending, approved, denied, expired
    created_at: str = ""
    decided_at: str = ""
    decided_by: str = ""

    def to_dict(self):
        return asdict(self)


class Hub:
    """Central state manager for SlimyOS Habitat."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._agents: dict[str, Agent] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._event_listeners: list[Callable] = []
        self._panicked = False
        self._lock = threading.Lock()
        self._event_log: list[dict] = []

    # ═══ Panic ═══
    
    @property
    def is_panicked(self) -> bool:
        return self._panicked

    def panic_stop(self, reason: str = "Manual panic stop"):
        """Emergency halt all agents and tasks."""
        with self._lock:
            self._panicked = True
            for task in self._tasks.values():
                if task.state in (TaskState.RUNNING, TaskState.WAITING_APPROVAL, TaskState.PENDING):
                    task.state = TaskState.PANICKED
                    task.error = reason
            for agent in self._agents.values():
                agent.state = AgentState.STOPPED
            self._emit("panic_stop", {"reason": reason})

    def resume(self):
        """Resume after panic — resets panic flag but doesn't restart tasks."""
        with self._lock:
            self._panicked = False
            self._emit("panic_resumed", {})

    # ═══ Tasks ═══

    def create_task(self, task_id: str, description: str, agent_id: str,
                    agent_runtime: str, work_room: str) -> Task:
        now = datetime.now(timezone.utc).isoformat()
        task = Task(
            task_id=task_id, description=description, agent_id=agent_id,
            agent_runtime=agent_runtime, work_room=work_room,
            state=TaskState.RUNNING, created_at=now, updated_at=now,
        )
        with self._lock:
            self._tasks[task_id] = task
        self._emit("task_created", task.to_dict())
        return task

    def update_task(self, task_id: str, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            task.updated_at = datetime.now(timezone.utc).isoformat()
        self._emit("task_updated", task.to_dict())

    def complete_task(self, task_id: str, status: str = "completed", proof_path: str = ""):
        state = TaskState.COMPLETED if status == "completed" else TaskState.FAILED
        self.update_task(task_id, state=state, proof_pack_path=proof_path)
        self._emit("task_completed", {"task_id": task_id, "status": status, "proof": proof_path})

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    # ═══ Agents ═══

    def register_agent(self, agent_id: str, runtime: str) -> Agent:
        agent = Agent(
            agent_id=agent_id, runtime=runtime,
            registered_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._agents[agent_id] = agent
        self._emit("agent_registered", agent.to_dict())
        return agent

    def get_all_agents(self) -> list[dict]:
        return [a.to_dict() for a in self._agents.values()]

    # ═══ Approvals ═══

    def request_approval(self, task_id: str, agent_id: str, tool_name: str,
                         tool_args: dict, reason: str, risk_level: str) -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=str(uuid.uuid4())[:8],
            task_id=task_id, agent_id=agent_id, tool_name=tool_name,
            tool_args=tool_args, reason=reason, risk_level=risk_level,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._approvals[req.request_id] = req
            task = self._tasks.get(task_id)
            if task:
                task.state = TaskState.WAITING_APPROVAL
        self._emit("approval_requested", req.to_dict())
        return req

    def decide_approval(self, request_id: str, approved: bool, decided_by: str = "user") -> Optional[ApprovalRequest]:
        with self._lock:
            req = self._approvals.get(request_id)
            if not req:
                return None
            req.status = "approved" if approved else "denied"
            req.decided_at = datetime.now(timezone.utc).isoformat()
            req.decided_by = decided_by
            task = self._tasks.get(req.task_id)
            if task and approved:
                task.state = TaskState.RUNNING
        self._emit("approval_decided", req.to_dict())
        return req

    def get_pending_approvals(self) -> list[dict]:
        return [a.to_dict() for a in self._approvals.values() if a.status == "pending"]

    # ═══ Event Stream ═══

    def add_listener(self, callback: Callable):
        self._event_listeners.append(callback)

    def _emit(self, event_type: str, data: dict):
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        self._event_log.append(event)
        # Keep last 500 events in memory
        if len(self._event_log) > 500:
            self._event_log = self._event_log[-500:]
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception:
                pass

    def get_recent_events(self, count: int = 50) -> list[dict]:
        return self._event_log[-count:]

    # ═══ State snapshot (for dashboard) ═══

    def snapshot(self) -> dict:
        """Full state snapshot for rendering the dashboard."""
        return {
            "panicked": self._panicked,
            "tasks": self.get_all_tasks(),
            "agents": self.get_all_agents(),
            "pending_approvals": self.get_pending_approvals(),
            "recent_events": self.get_recent_events(30),
            "stats": {
                "total_tasks": len(self._tasks),
                "running": len([t for t in self._tasks.values() if t.state == TaskState.RUNNING]),
                "waiting_approval": len([t for t in self._tasks.values() if t.state == TaskState.WAITING_APPROVAL]),
                "completed": len([t for t in self._tasks.values() if t.state == TaskState.COMPLETED]),
                "failed": len([t for t in self._tasks.values() if t.state == TaskState.FAILED]),
                "pending_approvals": len(self.get_pending_approvals()),
                "total_agents": len(self._agents),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
