"""
slimy-policyd — SlimyOS Policy Engine

The most important component of SlimyOS.
Decides what is allowed, blocked, escalated, logged, sandboxed, or approval-gated.

Design rules:
- Boring, strict, deterministic, inspectable, testable.
- Does NOT rely on model judgment or "AI decided it was safe."
- Fail-closed: unknown actions are blocked by default.
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Disposition(Enum):
    ALLOW = "allowed"
    BLOCK = "blocked"
    APPROVE_REQUIRED = "approval_required"
    SANDBOX = "sandbox"
    SNAPSHOT_FIRST = "snapshot_first"


@dataclass
class PolicyDecision:
    disposition: Disposition
    rule: str  # Which rule triggered this decision
    tool_name: str
    tool_args: dict = field(default_factory=dict)
    reason: str = ""
    requires_snapshot: bool = False
    
    def to_dict(self):
        return {
            "disposition": self.disposition.value,
            "rule": self.rule,
            "tool_name": self.tool_name,
            "reason": self.reason,
            "requires_snapshot": self.requires_snapshot,
        }


class PolicyEngine:
    """
    Deterministic policy engine for SlimyOS.
    
    Evaluates tool requests against a policy file and returns
    a disposition: ALLOW, BLOCK, APPROVE_REQUIRED, SANDBOX, or SNAPSHOT_FIRST.
    
    Evaluation order (first match wins):
    1. Is the tool in blocked_actions? → BLOCK
    2. Is the path in blocked_paths? → BLOCK  
    3. Is there a tool_override with explicit disposition? → use it
    4. Does the tool require approval per policy? → APPROVE_REQUIRED
    5. Does the tool require snapshot per policy? → SNAPSHOT_FIRST
    6. Is the tool in dangerous_actions? → APPROVE_REQUIRED
    7. Is the path outside allowed_project_roots? → BLOCK
    8. Budget check: over limit? → BLOCK
    9. Default mode applies
    """

    def __init__(self, policy_path: str):
        self.policy_path = policy_path
        self.policy = self._load_policy(policy_path)
        self._call_counts: dict[str, int] = {}  # task_id -> count
        self._daily_calls: int = 0

    def _load_policy(self, path: str) -> dict:
        with open(path, "r") as f:
            policy = json.load(f)
        # Validate required fields
        required = ["version", "default_mode", "dangerous_actions", "blocked_paths", "allowed_project_roots"]
        for key in required:
            if key not in policy:
                raise ValueError(f"Policy missing required field: {key}")
        return policy

    def reload(self):
        """Hot-reload policy from disk."""
        self.policy = self._load_policy(self.policy_path)

    def evaluate(self, tool_name: str, tool_args: dict, task_id: str = "default",
                 manifest: Optional[dict] = None) -> PolicyDecision:
        """
        Evaluate a tool request against the loaded policy.
        Returns a PolicyDecision with disposition and rule that triggered it.
        """
        p = self.policy

        # 1. Blocked actions — hard block, no override
        blocked_actions = p.get("blocked_actions", [])
        if tool_name in blocked_actions:
            return PolicyDecision(
                disposition=Disposition.BLOCK,
                rule="blocked_actions",
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' is in the blocked_actions list.",
            )

        # 2. Path checks — blocked paths
        paths_to_check = self._extract_paths(tool_args)
        for path_str in paths_to_check:
            expanded = self._expand_path(path_str)
            for blocked in p.get("blocked_paths", []):
                blocked_exp = self._expand_path(blocked)
                if expanded.startswith(blocked_exp) or expanded == blocked_exp:
                    return PolicyDecision(
                        disposition=Disposition.BLOCK,
                        rule="blocked_paths",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reason=f"Path '{path_str}' is within blocked path '{blocked}'.",
                    )

        # 3. Tool-specific overrides
        overrides = p.get("tool_overrides", {})
        if tool_name in overrides:
            override = overrides[tool_name]
            
            # Check allowed_args constraints
            if "allowed_args" in override:
                for arg_key, allowed_values in override["allowed_args"].items():
                    actual_value = tool_args.get(arg_key)
                    if actual_value is not None and actual_value not in allowed_values:
                        return PolicyDecision(
                            disposition=Disposition.BLOCK,
                            rule=f"tool_overrides.{tool_name}.allowed_args.{arg_key}",
                            tool_name=tool_name,
                            tool_args=tool_args,
                            reason=f"Argument '{arg_key}={actual_value}' not in allowed values: {allowed_values}",
                        )
            
            # Check per-tool call limit
            if "max_calls_per_task" in override:
                task_tool_key = f"{task_id}:{tool_name}"
                count = self._call_counts.get(task_tool_key, 0)
                if count >= override["max_calls_per_task"]:
                    return PolicyDecision(
                        disposition=Disposition.BLOCK,
                        rule=f"tool_overrides.{tool_name}.max_calls_per_task",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reason=f"Tool '{tool_name}' exceeded max calls per task ({override['max_calls_per_task']}).",
                    )
            
            # Explicit disposition
            if "disposition" in override:
                disp_str = override["disposition"]
                disp_map = {
                    "allow": Disposition.ALLOW,
                    "block": Disposition.BLOCK,
                    "approve": Disposition.APPROVE_REQUIRED,
                    "sandbox": Disposition.SANDBOX,
                }
                disp = disp_map.get(disp_str, Disposition.BLOCK)
                return PolicyDecision(
                    disposition=disp,
                    rule=f"tool_overrides.{tool_name}.disposition",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reason=f"Tool override: {disp_str}",
                )

        # 4. Approval-required list
        if tool_name in p.get("require_approval", []):
            snapshot = tool_name in p.get("require_snapshot_before", [])
            return PolicyDecision(
                disposition=Disposition.APPROVE_REQUIRED,
                rule="require_approval",
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' requires human approval.",
                requires_snapshot=snapshot,
            )

        # 5. Snapshot-required list
        if tool_name in p.get("require_snapshot_before", []):
            return PolicyDecision(
                disposition=Disposition.SNAPSHOT_FIRST,
                rule="require_snapshot_before",
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' requires snapshot before execution.",
                requires_snapshot=True,
            )

        # 6. Dangerous actions → approval required
        if tool_name in p.get("dangerous_actions", []):
            return PolicyDecision(
                disposition=Disposition.APPROVE_REQUIRED,
                rule="dangerous_actions",
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' is classified as dangerous.",
            )

        # 7. Path outside allowed roots (for tools that write/modify)
        write_tools = {"write_file", "delete_file", "move_file", "git_commit", "git_push"}
        if tool_name in write_tools:
            for path_str in paths_to_check:
                expanded = self._expand_path(path_str)
                in_allowed = any(
                    expanded.startswith(self._expand_path(root))
                    for root in p.get("allowed_project_roots", [])
                )
                if not in_allowed:
                    return PolicyDecision(
                        disposition=Disposition.BLOCK,
                        rule="allowed_project_roots",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reason=f"Path '{path_str}' is outside allowed project roots.",
                    )

        # 8. Budget check
        budget = p.get("budget", {})
        if budget:
            max_per_task = budget.get("max_tool_calls_per_task", float("inf"))
            task_count = self._call_counts.get(task_id, 0)
            if task_count >= max_per_task:
                return PolicyDecision(
                    disposition=Disposition.BLOCK,
                    rule="budget.max_tool_calls_per_task",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reason=f"Task '{task_id}' exceeded max tool calls ({max_per_task}).",
                )
            
            max_daily = budget.get("max_tool_calls_per_day", float("inf"))
            if self._daily_calls >= max_daily:
                return PolicyDecision(
                    disposition=Disposition.BLOCK,
                    rule="budget.max_tool_calls_per_day",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reason=f"Daily tool call limit reached ({max_daily}).",
                )

        # 9. Manifest-level checks
        if manifest:
            if manifest.get("requires_approval"):
                return PolicyDecision(
                    disposition=Disposition.APPROVE_REQUIRED,
                    rule="manifest.requires_approval",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reason=f"Tool manifest requires approval.",
                    requires_snapshot=manifest.get("requires_snapshot", False),
                )

        # 10. Default mode
        default_mode = p.get("default_mode", "block")
        mode_map = {
            "block": Disposition.BLOCK,
            "draft": Disposition.APPROVE_REQUIRED,
            "approve": Disposition.APPROVE_REQUIRED,
            "allow": Disposition.ALLOW,
        }
        return PolicyDecision(
            disposition=mode_map.get(default_mode, Disposition.BLOCK),
            rule="default_mode",
            tool_name=tool_name,
            tool_args=tool_args,
            reason=f"No specific rule matched. Default mode: {default_mode}",
        )

    def record_call(self, tool_name: str, task_id: str = "default"):
        """Record a tool call for budget tracking."""
        task_tool_key = f"{task_id}:{tool_name}"
        self._call_counts[task_tool_key] = self._call_counts.get(task_tool_key, 0) + 1
        task_key = task_id
        self._call_counts[task_key] = self._call_counts.get(task_key, 0) + 1
        self._daily_calls += 1

    def reset_task(self, task_id: str):
        """Reset call counts for a task."""
        keys = [k for k in self._call_counts if k.startswith(f"{task_id}:") or k == task_id]
        for k in keys:
            del self._call_counts[k]

    def _extract_paths(self, args: dict) -> list[str]:
        """Extract filesystem paths from tool arguments."""
        paths = []
        for key in ("path", "file_path", "repo_path", "project_path", "directory", "target"):
            if key in args and isinstance(args[key], str):
                paths.append(args[key])
        return paths

    def _expand_path(self, path: str) -> str:
        """Expand ~ and resolve to absolute path."""
        return str(Path(os.path.expanduser(path)).resolve())
