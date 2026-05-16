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
import subprocess
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
    execution_status: str = "not_executed"
    execution_started_at: str = ""
    execution_finished_at: str = ""
    execution_result_summary: str = ""
    execution_audit_event_id: str = ""
    execution_proof_ref: str = ""
    execution_error: str = ""
    one_time_use: bool = True
    used: bool = False
    execution_args: dict = field(default_factory=dict)
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
            "execution_status": self.execution_status,
            "execution_started_at": self.execution_started_at,
            "execution_finished_at": self.execution_finished_at,
            "execution_result_summary": self.execution_result_summary,
            "execution_audit_event_id": self.execution_audit_event_id,
            "execution_proof_ref": self.execution_proof_ref,
            "execution_error": self.execution_error,
            "one_time_use": self.one_time_use,
            "used": self.used,
            "execute_test_lane_eligible": self._is_test_lane_eligible(),
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_runtime": self.agent_runtime,
        }

    def _is_test_lane_eligible(self) -> bool:
        repo_path = str(self.execution_args.get("repo_path", ""))
        if self.tool_name != "git_commit":
            return False
        return repo_path.startswith("/tmp/proof_slimyos_approved_execution_") or repo_path.startswith("/tmp/slimyos_approved_execution_demo_")


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
        self._approved_execution_allowlist: set[str] = {"git_commit"}
        self._approved_execution_lane_prefixes: tuple[str, ...] = (
            "/tmp/proof_slimyos_approved_execution_",
            "/tmp/slimyos_approved_execution_demo_",
        )
        self._load_manifests()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _run_git(repo_path: str, *args: str, timeout: int = 15) -> tuple[bool, str, str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, "", str(exc)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()

    def _is_test_lane_path(self, repo_path: str) -> bool:
        if not repo_path:
            return False
        expanded = str(Path(os.path.expanduser(repo_path)).resolve())
        return any(expanded.startswith(prefix) for prefix in self._approved_execution_lane_prefixes)

    def _extract_execution_args(self, tool_name: str, raw_tool_args: dict) -> dict:
        if tool_name == "git_commit":
            return {
                "repo_path": raw_tool_args.get("repo_path", ""),
                "message": raw_tool_args.get("message", ""),
            }
        return {}

    def _args_match_snapshot(self, approval: ApprovalRequest, caller_args: Optional[dict]) -> bool:
        if caller_args is None:
            return True
        safe_caller_args = self._sanitize_tool_args(caller_args)
        expected = dict(approval.requested_args_redacted)
        safe_caller_args.pop("private_fields_omitted", None)
        expected.pop("private_fields_omitted", None)
        return safe_caller_args == expected

    def _write_execution_proof(self, approval: ApprovalRequest, result: dict, status: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = Path(f"/tmp/proof_slimyos_approved_execution_runtime_{ts}")
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": self._now_iso(),
            "approval": approval.to_dict(),
            "execution_status": status,
            "result": result,
        }
        out = root / "execution.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(out)

    def _refuse_execution(self, approval: ApprovalRequest, reason: str, decided_by: str) -> dict:
        with self._lock:
            approval.execution_status = "execution_refused"
            approval.execution_started_at = approval.execution_started_at or self._now_iso()
            approval.execution_finished_at = self._now_iso()
            approval.execution_error = reason
            approval.execution_result_summary = "execution_refused"
            approval.decided_by = approval.decided_by or decided_by

        refusal_event = self.audit.log(
            event_type="approval_execution_refused",
            agent_id=approval.agent_id or "unknown",
            agent_runtime=approval.agent_runtime or "unknown",
            tool_name=approval.tool_name,
            task_id=approval.task_id,
            tool_args=approval.requested_args_redacted,
            disposition="execution_refused",
            policy_rule=approval.policy_rule,
            risk_level=approval.risk_level,
            metadata={
                "approval_id": approval.approval_id,
                "reason": reason,
            },
            client_identity=approval.client_identity,
        )
        approval.execution_audit_event_id = refusal_event.get("event_id", "")
        return {
            "ok": False,
            "error": reason,
            "approval": approval.to_dict(),
        }

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
            execution_status="not_executed",
            one_time_use=True,
            used=False,
            execution_args=self._extract_execution_args(tool_name, tool_args),
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

            approval.status = "approved" if approved else "denied"
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

    def execute_approved(self, approval_id: str, confirm: str, caller_args: Optional[dict] = None, decided_by: str = "api") -> dict:
        if not approval_id:
            return {"ok": False, "error": "missing_approval_id"}

        with self._lock:
            approval = self._approvals.get(approval_id)

        if not approval:
            return {"ok": False, "error": "unknown_approval_id", "approval_id": approval_id}

        if confirm != "execute-approved-test-lane":
            return self._refuse_execution(approval, "confirm_token_required", decided_by)

        if approval.status != "approved":
            return self._refuse_execution(approval, f"approval_not_executable_status:{approval.status}", decided_by)

        if approval.one_time_use and approval.used:
            return self._refuse_execution(approval, "already_used", decided_by)

        if approval.execution_status == "executed":
            return self._refuse_execution(approval, "already_executed", decided_by)

        if approval.tool_name not in self._approved_execution_allowlist:
            return self._refuse_execution(approval, f"tool_not_in_approved_execution_allowlist:{approval.tool_name}", decided_by)

        if not self._args_match_snapshot(approval, caller_args):
            return self._refuse_execution(approval, "args_mismatch", decided_by)

        execution_args = dict(approval.execution_args or {})
        repo_path = str(execution_args.get("repo_path", ""))
        if not self._is_test_lane_path(repo_path):
            return self._refuse_execution(approval, "repo_outside_test_lane", decided_by)

        if not os.path.isdir(repo_path):
            return self._refuse_execution(approval, "repo_path_missing", decided_by)

        ok_repo, _, _ = self._run_git(repo_path, "rev-parse", "--is-inside-work-tree")
        if not ok_repo:
            return self._refuse_execution(approval, "repo_not_git", decided_by)

        ok_status, status_out, status_err = self._run_git(repo_path, "status", "--porcelain")
        if not ok_status:
            return self._refuse_execution(approval, f"git_status_failed:{status_err}", decided_by)

        status_lines = [line for line in status_out.splitlines() if line.strip()]
        if not status_lines:
            return self._refuse_execution(approval, "repo_clean_no_staged_changes", decided_by)

        for line in status_lines:
            if line.startswith("??"):
                return self._refuse_execution(approval, "unexpected_untracked_files", decided_by)
            if len(line) >= 2 and line[1] != " ":
                return self._refuse_execution(approval, "unexpected_unstaged_changes", decided_by)
            if len(line) >= 1 and line[0] == " ":
                return self._refuse_execution(approval, "missing_staged_change", decided_by)

        with self._lock:
            approval.execution_status = "execution_pending"
            approval.execution_started_at = self._now_iso()
            approval.execution_error = ""
            approval.execution_result_summary = ""

        start_event = self.audit.log(
            event_type="approval_execution_start",
            agent_id=approval.agent_id or "unknown",
            agent_runtime=approval.agent_runtime or "unknown",
            tool_name=approval.tool_name,
            task_id=approval.task_id,
            tool_args=self._sanitize_tool_args(execution_args),
            disposition="execution_pending",
            policy_rule=approval.policy_rule,
            risk_level=approval.risk_level,
            metadata={
                "approval_id": approval.approval_id,
                "request_id": approval.request_id,
            },
            client_identity=approval.client_identity,
        )
        approval.execution_audit_event_id = start_event.get("event_id", "")

        handler = self._handlers.get(approval.tool_name)
        if handler is None:
            return self._refuse_execution(approval, "approved_tool_handler_missing", decided_by)

        try:
            execution_result = handler(execution_args)
            success = not execution_result.get("error")
            summary = str(execution_result.get("output", ""))[:240]

            with self._lock:
                approval.execution_finished_at = self._now_iso()
                approval.execution_status = "executed" if success else "execution_failed"
                approval.execution_result_summary = summary or ("executed" if success else "execution_failed")
                approval.execution_error = str(execution_result.get("error", ""))
                if success and approval.one_time_use:
                    approval.used = True

            proof_ref = self._write_execution_proof(approval, execution_result, approval.execution_status)
            approval.execution_proof_ref = proof_ref

            finish_event = self.audit.log(
                event_type="approval_execution_finish",
                agent_id=approval.agent_id or "unknown",
                agent_runtime=approval.agent_runtime or "unknown",
                tool_name=approval.tool_name,
                task_id=approval.task_id,
                tool_args=self._sanitize_tool_args(execution_args),
                disposition=approval.execution_status,
                policy_rule=approval.policy_rule,
                risk_level=approval.risk_level,
                result={
                    "success": success,
                    "output": summary,
                    "error": approval.execution_error,
                },
                metadata={
                    "approval_id": approval.approval_id,
                    "request_id": approval.request_id,
                    "proof_ref": proof_ref,
                },
                client_identity=approval.client_identity,
            )
            approval.execution_audit_event_id = finish_event.get("event_id", approval.execution_audit_event_id)

            return {
                "ok": success,
                "approval": approval.to_dict(),
                "result": execution_result,
                "proof_ref": proof_ref,
            }
        except Exception as exc:
            with self._lock:
                approval.execution_finished_at = self._now_iso()
                approval.execution_status = "execution_failed"
                approval.execution_error = str(exc)
                approval.execution_result_summary = "execution_failed"

            finish_event = self.audit.log(
                event_type="approval_execution_finish",
                agent_id=approval.agent_id or "unknown",
                agent_runtime=approval.agent_runtime or "unknown",
                tool_name=approval.tool_name,
                task_id=approval.task_id,
                tool_args=self._sanitize_tool_args(execution_args),
                disposition="execution_failed",
                policy_rule=approval.policy_rule,
                risk_level=approval.risk_level,
                result={"success": False, "error": str(exc)},
                metadata={
                    "approval_id": approval.approval_id,
                    "request_id": approval.request_id,
                },
                client_identity=approval.client_identity,
            )
            approval.execution_audit_event_id = finish_event.get("event_id", approval.execution_audit_event_id)
            return {"ok": False, "error": str(exc), "approval": approval.to_dict()}

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
