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
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

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

    def to_dict(self):
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "disposition": self.disposition,
            "policy_rule": self.policy_rule,
            "files_changed": self.files_changed,
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
        self._load_manifests()

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
    ) -> ToolResult:
        """
        Execute a tool call through the full policy → execute → audit pipeline.
        """
        manifest = self._manifests.get(tool_name)

        # Log the request
        self.audit.log(
            event_type="tool_request",
            agent_id=agent_id,
            agent_runtime=agent_runtime,
            tool_name=tool_name,
            task_id=task_id,
            tool_args=tool_args,
            work_room=manifest.get("work_room", "") if manifest else "",
            risk_level=manifest.get("risk_level", "") if manifest else "",
        )

        # Unknown tool → block
        if tool_name not in self._manifests:
            self.audit.log(
                event_type="tool_blocked",
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                tool_name=tool_name,
                task_id=task_id,
                tool_args=tool_args,
                disposition="blocked",
                policy_rule="unknown_tool",
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
            tool_args=tool_args,
            disposition=decision.disposition.value,
            policy_rule=decision.rule,
            work_room=manifest.get("work_room", ""),
            risk_level=manifest.get("risk_level", ""),
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
            self.audit.log(
                event_type="approval_requested",
                agent_id=agent_id,
                agent_runtime=agent_runtime,
                tool_name=tool_name,
                task_id=task_id,
                tool_args=tool_args,
                disposition="approval_required",
                policy_rule=decision.rule,
            )
            return ToolResult(
                success=False,
                error=f"APPROVAL REQUIRED: {decision.reason}",
                disposition="approval_required",
                policy_rule=decision.rule,
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
                tool_args=tool_args,
                disposition="allowed",
                policy_rule=decision.rule,
                result={"success": True, "output": str(result.get("output", ""))[:500]},
                files_changed=result.get("files_changed", []),
                work_room=manifest.get("work_room", ""),
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
                tool_args=tool_args,
                disposition="allowed",
                result={"success": False, "error": str(e)},
            )
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {e}",
                disposition="allowed",
                policy_rule=decision.rule,
            )
