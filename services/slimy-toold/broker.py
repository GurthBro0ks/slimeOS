"""
slimy-toold — SlimyOS Tool Broker

Receives tool requests from agent runtimes.
Routes through policy engine before execution.
Audits every call. Produces proof data.

Agents do NOT get raw shell access.
They get named, scoped, audited tool calls.
"""

import json
import os
import re
import uuid
import threading
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Any

from services.slimy_policyd.engine import PolicyEngine, Disposition, PolicyDecision
from services.slimy_auditd.logger import AuditLogger


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    disposition: str = ""
    policy_rule: str = ""
    files_changed: list = field(default_factory=list)
    approval_id: str = ""
    request_id: str = ""
    approval_status: str = ""

    def to_dict(self):
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "disposition": self.disposition,
            "policy_rule": self.policy_rule,
            "files_changed": self.files_changed,
            "approval_id": self.approval_id,
            "request_id": self.request_id,
            "approval_status": self.approval_status,
        }


@dataclass
class ApprovalRequest:
    approval_id: str
    request_id: str
    client_identity: dict
    tool_name: str
    requested_args_summary: str
    requested_args_redacted: dict
    disposition: str
    policy_rule: str
    risk_level: str
    created_at: str
    expires_at: str = ""
    status: str = "pending"
    decision_at: str = ""
    decided_by: str = ""
    audit_event_id: str = ""
    proof_ref: str = ""
    task_id: str = ""
    agent_id: str = ""
    agent_runtime: str = ""

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "request_id": self.request_id,
            "client_identity": self.client_identity,
            "tool_name": self.tool_name,
            "requested_args_summary": self.requested_args_summary,
            "requested_args_redacted": self.requested_args_redacted,
            "disposition": self.disposition,
            "policy_rule": self.policy_rule,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "decision_at": self.decision_at,
            "decided_by": self.decided_by,
            "audit_event_id": self.audit_event_id,
            "proof_ref": self.proof_ref,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_runtime": self.agent_runtime,
        }


class ToolBroker:
    """
    Central tool broker for SlimyOS.
    
    All agent tool calls go through here.
    
    Flow:
    1. Load tool manifest
    2. Check policy
    3. If allowed: execute via registered handler
    4. Audit the call
    5. Return result
    """

    def __init__(self, policy_engine: PolicyEngine, audit_logger: AuditLogger,
                 manifests_dir: str = "tools/manifests"):
        self.policy = policy_engine
        self.audit = audit_logger
        self.manifests_dir = Path(manifests_dir)
        self._handlers: dict[str, Callable] = {}
        self._manifests: dict[str, dict] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._approval_order: list[str] = []
        self._lock = threading.Lock()
        self._load_manifests()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _looks_secret_key(key: str) -> bool:
        lowered = key.lower()
        keywords = (
            "secret",
            "token",
            "password",
            "passwd",
            "api_key",
            "apikey",
            "credential",
            "private_key",
            "bearer",
            "cookie",
            "session",
        )
        return any(word in lowered for word in keywords)

    @staticmethod
    def _looks_chat_key(key: str) -> bool:
        lowered = key.lower()
        keywords = ("chat", "conversation", "prompt", "messages", "history")
        return any(word in lowered for word in keywords)

    def _redact_value(self, key: str, value: Any) -> Any:
        if self._looks_secret_key(key):
            return "[REDACTED]"

        if isinstance(value, dict):
            sanitized, _ = self._sanitize_mapping(value)
            return sanitized
        if isinstance(value, list):
            sanitized_list = []
            for item in value:
                if isinstance(item, dict):
                    nested, _ = self._sanitize_mapping(item)
                    sanitized_list.append(nested)
                else:
                    sanitized_list.append(self._redact_value(key, item))
            return sanitized_list
        if isinstance(value, str):
            if len(value) > 500:
                return f"{value[:120]}...[truncated]"
            tokenish = bool(re.search(r"[A-Za-z0-9_\-]{32,}", value))
            if tokenish and any(ch.isdigit() for ch in value):
                return "[REDACTED]"
            return value
        return value

    def _sanitize_mapping(self, mapping: dict[str, Any]) -> tuple[dict[str, Any], int]:
        sanitized: dict[str, Any] = {}
        omitted_private_fields = 0

        for key, value in mapping.items():
            if self._looks_chat_key(key):
                omitted_private_fields += 1
                continue

            if isinstance(value, dict):
                nested, nested_omitted = self._sanitize_mapping(value)
                omitted_private_fields += nested_omitted
                sanitized[key] = nested
            elif isinstance(value, list):
                out_list = []
                for item in value:
                    if isinstance(item, dict):
                        nested, nested_omitted = self._sanitize_mapping(item)
                        omitted_private_fields += nested_omitted
                        out_list.append(nested)
                    else:
                        out_list.append(self._redact_value(key, item))
                sanitized[key] = out_list
            else:
                sanitized[key] = self._redact_value(key, value)

        return sanitized, omitted_private_fields

    def _sanitize_tool_args(self, tool_args: dict) -> dict:
        if not isinstance(tool_args, dict):
            return {}
        sanitized, omitted_private_fields = self._sanitize_mapping(tool_args)
        if omitted_private_fields:
            sanitized["private_fields_omitted"] = omitted_private_fields
        return sanitized

    @staticmethod
    def _summarize_args(redacted_args: dict) -> str:
        if not redacted_args:
            return "(no args)"

        parts = []
        for key in sorted(redacted_args.keys())[:6]:
            value = redacted_args[key]
            if isinstance(value, str):
                preview = value[:48]
            elif isinstance(value, (int, float, bool)):
                preview = str(value)
            elif isinstance(value, list):
                preview = f"list[{len(value)}]"
            elif isinstance(value, dict):
                preview = f"object[{len(value)}]"
            else:
                preview = type(value).__name__
            parts.append(f"{key}={preview}")

        if len(redacted_args) > 6:
            parts.append(f"+{len(redacted_args) - 6} more")
        return ", ".join(parts)

    def _create_approval_request(
        self,
        tool_name: str,
        tool_args: dict,
        decision: PolicyDecision,
        manifest: Optional[dict],
        task_id: str,
        agent_id: str,
        agent_runtime: str,
        client_identity: Optional[dict],
    ) -> ApprovalRequest:
        redacted_args = self._sanitize_tool_args(tool_args)
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(hours=1)).isoformat()
        approval_id = str(uuid.uuid4())
        request_id = (
            (client_identity or {}).get("request_id")
            or f"req-{approval_id[:8]}"
        )

        approval = ApprovalRequest(
            approval_id=approval_id,
            request_id=str(request_id),
            client_identity=client_identity or {},
            tool_name=tool_name,
            requested_args_summary=self._summarize_args(redacted_args),
            requested_args_redacted=redacted_args,
            disposition="approval_required",
            policy_rule=decision.rule,
            risk_level=(manifest or {}).get("risk_level", "unknown"),
            created_at=created_at,
            expires_at=expires_at,
            status="pending",
            task_id=task_id,
            agent_id=agent_id,
            agent_runtime=agent_runtime,
        )

        with self._lock:
            self._approvals[approval.approval_id] = approval
            self._approval_order.append(approval.approval_id)

        approval_event = self.audit.log(
            event_type="approval_requested",
            agent_id=agent_id,
            agent_runtime=agent_runtime,
            tool_name=tool_name,
            task_id=task_id,
            tool_args=redacted_args,
            disposition="approval_required",
            policy_rule=decision.rule,
            risk_level=(manifest or {}).get("risk_level", ""),
            metadata={
                "approval_id": approval.approval_id,
                "request_id": approval.request_id,
                "requested_args_summary": approval.requested_args_summary,
                "risk_level": approval.risk_level,
                "expires_at": approval.expires_at,
            },
            client_identity=client_identity,
        )

        approval.audit_event_id = approval_event.get("event_id", "")
        return approval

    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        with self._lock:
            return self._approvals.get(approval_id)

    def get_approvals(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self._lock:
            approvals = [self._approvals[k] for k in self._approval_order if k in self._approvals]
        if status:
            approvals = [a for a in approvals if a.status == status]
        approvals = approvals[-limit:]
        return [a.to_dict() for a in approvals]

    def get_pending_approvals(self) -> list[dict]:
        return self.get_approvals(status="pending")

    def decide_approval(self, approval_id: str, approved: bool, decided_by: str = "user") -> Optional[dict]:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if not approval:
                return None

            if approval.status != "pending":
                return approval.to_dict()

            approval.status = "approved_pending_manual_execution" if approved else "denied"
            approval.decision_at = self._now_iso()
            approval.decided_by = decided_by

        self.audit.log(
            event_type="approval_decided",
            agent_id=approval.agent_id or "unknown",
            agent_runtime=approval.agent_runtime or "unknown",
            tool_name=approval.tool_name,
            task_id=approval.task_id,
            tool_args=approval.requested_args_redacted,
            disposition=approval.status,
            policy_rule=approval.policy_rule,
            risk_level=approval.risk_level,
            metadata={
                "approval_id": approval.approval_id,
                "request_id": approval.request_id,
                "decided_by": decided_by,
                "decision": "approved" if approved else "denied",
            },
            client_identity=approval.client_identity,
        )
        return approval.to_dict()

    def approvals_state(self) -> dict:
        pending = self.get_pending_approvals()
        recent = self.get_approvals(limit=50)
        return {
            "pending_approvals": pending,
            "approvals_recent": recent,
            "approvals": {
                "pending_count": len(pending),
                "total_count": len(recent),
            },
        }

    def _load_manifests(self):
        """Load all tool manifests from the manifests directory."""
        if not self.manifests_dir.exists():
            return
        for f in self.manifests_dir.glob("*.tool.json"):
            with open(f) as fh:
                manifest = json.load(fh)
                self._manifests[manifest["name"]] = manifest

    def register_handler(self, tool_name: str, handler: Callable):
        """Register a handler function for a tool."""
        self._handlers[tool_name] = handler

    def get_manifest(self, tool_name: str) -> Optional[dict]:
        return self._manifests.get(tool_name)

    def list_tools(self) -> list[str]:
        return list(self._manifests.keys())

    def call(
        self,
        tool_name: str,
        tool_args: dict,
        agent_id: str = "unknown",
        agent_runtime: str = "unknown",
        task_id: str = "default",
        client_identity: Optional[dict] = None,
    ) -> ToolResult:
        """
        Execute a tool call through the full policy → execute → audit pipeline.
        """
        manifest = self._manifests.get(tool_name)
        safe_tool_args = self._sanitize_tool_args(tool_args)

        # Log the request
        self.audit.log(
            event_type="tool_request",
            agent_id=agent_id,
            agent_runtime=agent_runtime,
            tool_name=tool_name,
            task_id=task_id,
            tool_args=safe_tool_args,
            work_room=manifest.get("work_room", "") if manifest else "",
            risk_level=manifest.get("risk_level", "") if manifest else "",
            client_identity=client_identity,
        )

        # Unknown tool → block
        if tool_name not in self._manifests:
            self.audit.log(
                event_type="tool_blocked",
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                tool_name=tool_name,
                task_id=task_id,
                tool_args=safe_tool_args,
                disposition="blocked",
                policy_rule="unknown_tool",
                client_identity=client_identity,
            )
            return ToolResult(
                success=False,
                error=f"Unknown tool: '{tool_name}'. Not in manifest registry.",
                disposition="blocked",
                policy_rule="unknown_tool",
            )

        # Check policy
        decision = self.policy.evaluate(
            tool_name=tool_name,
            tool_args=tool_args,
            task_id=task_id,
            manifest=manifest,
        )

        # Log the policy decision
        self.audit.log(
            event_type=f"tool_{decision.disposition.value}",
            agent_id=agent_id,
            agent_runtime=agent_runtime,
            tool_name=tool_name,
            task_id=task_id,
            tool_args=safe_tool_args,
            disposition=decision.disposition.value,
            policy_rule=decision.rule,
            work_room=manifest.get("work_room", ""),
            risk_level=manifest.get("risk_level", ""),
            client_identity=client_identity,
        )

        # Handle non-ALLOW dispositions
        if decision.disposition == Disposition.BLOCK:
            return ToolResult(
                success=False,
                error=f"BLOCKED by policy: {decision.reason}",
                disposition="blocked",
                policy_rule=decision.rule,
            )

        if decision.disposition == Disposition.APPROVE_REQUIRED:
            approval = self._create_approval_request(
                tool_name=tool_name,
                tool_args=tool_args,
                decision=decision,
                manifest=manifest,
                task_id=task_id,
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                client_identity=client_identity,
            )
            return ToolResult(
                success=False,
                error=f"APPROVAL REQUIRED: {decision.reason}",
                disposition="approval_required",
                policy_rule=decision.rule,
                approval_id=approval.approval_id,
                request_id=approval.request_id,
                approval_status=approval.status,
            )

        if decision.disposition == Disposition.SNAPSHOT_FIRST:
            return ToolResult(
                success=False,
                error=f"SNAPSHOT REQUIRED before execution: {decision.reason}",
                disposition="snapshot_first",
                policy_rule=decision.rule,
            )

        # ALLOW → execute
        if tool_name not in self._handlers:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' is allowed but has no registered handler.",
                disposition="allowed",
                policy_rule=decision.rule,
            )

        try:
            handler = self._handlers[tool_name]
            result = handler(tool_args)
            
            # Record the call for budget tracking
            self.policy.record_call(tool_name, task_id)

            # Audit the execution
            self.audit.log(
                event_type="tool_executed",
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                tool_name=tool_name,
                task_id=task_id,
                tool_args=safe_tool_args,
                disposition="allowed",
                policy_rule=decision.rule,
                result={"success": True, "output": str(result.get("output", ""))[:500]},
                files_changed=result.get("files_changed", []),
                work_room=manifest.get("work_room", ""),
                client_identity=client_identity,
            )

            return ToolResult(
                success=True,
                output=str(result.get("output", "")),
                disposition="allowed",
                policy_rule=decision.rule,
                files_changed=result.get("files_changed", []),
            )

        except Exception as e:
            self.audit.log(
                event_type="tool_failed",
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                tool_name=tool_name,
                task_id=task_id,
                tool_args=safe_tool_args,
                disposition="allowed",
                result={"success": False, "error": str(e)},
                client_identity=client_identity,
            )
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {e}",
                disposition="allowed",
                policy_rule=decision.rule,
            )
