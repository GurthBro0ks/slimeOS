"""
slimy-memoryd — SlimyOS Failure Memory

The most important memory in SlimyOS is failure memory.

Every time something goes wrong, the system records:
- What was tried
- What failed  
- How it was detected
- How it was fixed
- What rule prevents it next time

This is how SlimyOS improves — not by rewriting itself,
but by accumulating operational wisdom.
"""

import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path


class FailureMemory:
    """Persistent failure memory store."""

    def __init__(self, store_path: str = "~/.slimyos/memory"):
        self.store_path = Path(os.path.expanduser(store_path))
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._failures_file = self.store_path / "failures.jsonl"
        self._rules_file = self.store_path / "learned_rules.json"
        self._rules: list[dict] = self._load_rules()

    def _load_rules(self) -> list[dict]:
        if self._rules_file.exists():
            with open(self._rules_file) as f:
                return json.load(f)
        return []

    def _save_rules(self):
        with open(self._rules_file, "w") as f:
            json.dump(self._rules, f, indent=2)

    def record_failure(
        self,
        what_was_tried: str,
        what_failed: str,
        how_detected: str,
        task_id: str = "",
        agent_id: str = "",
        agent_runtime: str = "",
        work_room: str = "",
        error_output: str = "",
        severity: str = "medium",
        linked_proof_pack: str = "",
    ) -> dict:
        """Record a failure. Returns the failure record."""
        failure = {
            "failure_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_runtime": agent_runtime,
            "work_room": work_room,
            "what_was_tried": what_was_tried,
            "what_failed": what_failed,
            "error_output": error_output[:2000],
            "how_detected": how_detected,
            "how_fixed": "",
            "severity": severity,
            "new_rule": None,
            "linked_proof_pack": linked_proof_pack,
            "recurrence_count": self._count_similar(what_failed),
        }

        with open(self._failures_file, "a") as f:
            f.write(json.dumps(failure) + "\n")

        return failure

    def record_fix(self, failure_id: str, how_fixed: str,
                   new_rule: dict | None = None) -> dict | None:
        """Record how a failure was fixed and optionally add a learned rule."""
        # Read all failures, update the matching one
        failures = self.get_all_failures()
        updated = None
        for f in failures:
            if f["failure_id"] == failure_id:
                f["how_fixed"] = how_fixed
                f["new_rule"] = new_rule
                updated = f
                break

        if updated:
            # Rewrite file
            with open(self._failures_file, "w") as fh:
                for f in failures:
                    fh.write(json.dumps(f) + "\n")

            # Add learned rule if provided
            if new_rule:
                self._rules.append({
                    "rule_id": str(uuid.uuid4())[:8],
                    "created_from_failure": failure_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    **new_rule,
                })
                self._save_rules()

        return updated

    def get_all_failures(self) -> list[dict]:
        if not self._failures_file.exists():
            return []
        failures = []
        with open(self._failures_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    failures.append(json.loads(line))
        return failures

    def get_learned_rules(self) -> list[dict]:
        return list(self._rules)

    def check_rules(self, tool_name: str, tool_args: dict) -> list[dict]:
        """Check if any learned rules apply to this tool call."""
        matching = []
        for rule in self._rules:
            if rule.get("tool") == tool_name:
                matching.append(rule)
            elif rule.get("constraint") and tool_name in rule.get("constraint", ""):
                matching.append(rule)
        return matching

    def _count_similar(self, what_failed: str) -> int:
        """Count how many times similar failures have occurred."""
        count = 0
        key_words = set(what_failed.lower().split()[:5])
        for f in self.get_all_failures():
            existing_words = set(f.get("what_failed", "").lower().split()[:5])
            if len(key_words & existing_words) >= 3:
                count += 1
        return count

    def get_failure_summary(self) -> dict:
        """Summary stats for dashboard."""
        failures = self.get_all_failures()
        return {
            "total_failures": len(failures),
            "unfixed": len([f for f in failures if not f.get("how_fixed")]),
            "learned_rules": len(self._rules),
            "by_severity": {
                "low": len([f for f in failures if f.get("severity") == "low"]),
                "medium": len([f for f in failures if f.get("severity") == "medium"]),
                "high": len([f for f in failures if f.get("severity") == "high"]),
                "critical": len([f for f in failures if f.get("severity") == "critical"]),
            },
            "recurring": len([f for f in failures if f.get("recurrence_count", 0) > 0]),
        }
