"""Corp-Collab: check-in policy and 5-level escalation ladder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Escalation Levels ────────────────────────────────────────────────────────

ESCALATION_LEVELS = {
    1: {"name": "IM", "wait_attr": "im_wait", "action": "send_im"},
    2: {"name": "Email Urgent", "wait_attr": "email_wait", "action": "send_urgent_email"},
    3: {"name": "Investigate", "wait_attr": None, "action": "investigate"},
    4: {"name": "Intervene", "wait_attr": None, "action": "intervene"},
    5: {"name": "Fire + Rehire", "wait_attr": None, "action": "fire_and_rehire"},
}

MAX_LEVEL = 5


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Check-In Policy ─────────────────────────────────────────────────────────


@dataclass
class CheckInPolicy:
    """Configurable check-in timing and escalation parameters."""

    im_wait: int = 120          # seconds to wait after IM before escalating
    email_wait: int = 300       # seconds to wait after email before escalating
    escalation_multiplier: float = 1.4  # threshold = estimate * multiplier

    def should_check_in(
        self,
        estimate: float,
        elapsed: float,
        last_report_ago: float,
    ) -> bool:
        """Return True if a check-in is warranted.

        Args:
            estimate: accepted estimate in minutes.
            elapsed: minutes since task started.
            last_report_ago: minutes since last status report.
        """
        # Check in if elapsed exceeds half the estimate and no recent report
        threshold = estimate * 0.5
        if elapsed >= threshold and last_report_ago >= threshold:
            return True
        # Also check in if overdue
        if elapsed > estimate and last_report_ago >= self.im_wait / 60:
            return True
        return False

    def get_escalation_level(
        self,
        attempts: int,
        last_response: float | None = None,
    ) -> int:
        """Determine escalation level from check-in attempt count.

        Args:
            attempts: number of check-in attempts made.
            last_response: seconds since last response (None = never responded).
        """
        if attempts <= 0:
            return 1
        if attempts == 1:
            return 1
        if attempts == 2:
            return 2
        if attempts == 3:
            return 3
        if attempts == 4:
            return 4
        return MAX_LEVEL

    def generate_check_in_message(
        self,
        level: int,
        name: str,
        task_desc: str,
    ) -> str:
        """Create an escalation-appropriate check-in message."""
        level = min(level, MAX_LEVEL)
        if level <= 1:
            return f"Hey {name}, quick check-in: how's '{task_desc}' going?"
        if level == 2:
            return (
                f"URGENT: {name}, please respond with status on '{task_desc}'. "
                f"This is escalation level {level}."
            )
        if level == 3:
            return (
                f"INVESTIGATING: {name} has not responded regarding '{task_desc}'. "
                f"Checking work artifacts now."
            )
        if level == 4:
            return (
                f"INTERVENTION: Taking direct action on '{task_desc}'. "
                f"{name}, your output will be reviewed."
            )
        return (
            f"TERMINATION: {name} is being terminated for non-responsiveness on "
            f"'{task_desc}'. Initiating rehire process."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "im_wait": self.im_wait,
            "email_wait": self.email_wait,
            "escalation_multiplier": self.escalation_multiplier,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckInPolicy:
        return cls(
            im_wait=data.get("im_wait", 120),
            email_wait=data.get("email_wait", 300),
            escalation_multiplier=data.get("escalation_multiplier", 1.4),
        )


# ── Escalation Tracker ──────────────────────────────────────────────────────


@dataclass
class EscalationTracker:
    """Tracks check-in escalation state for a specific employee/task."""

    task_id: str
    employee_id: str
    employee_name: str
    policy: CheckInPolicy = field(default_factory=CheckInPolicy)
    _check_ins: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _responses: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def record_check_in(self, level: int) -> None:
        """Record that a check-in was sent at the given level."""
        self._check_ins.append({
            "level": level,
            "timestamp": _utcnow_iso(),
        })

    def record_response(self) -> None:
        """Record that the employee responded, resetting escalation."""
        self._responses.append({
            "timestamp": _utcnow_iso(),
            "after_check_ins": len(self._check_ins),
        })

    def current_level(self) -> int:
        """Current escalation level based on unanswered check-ins."""
        if not self._check_ins:
            return 0
        # Count check-ins since last response
        last_response_idx = self._responses[-1]["after_check_ins"] if self._responses else 0
        unanswered = len(self._check_ins) - last_response_idx
        if unanswered <= 0:
            return 0
        return min(unanswered, MAX_LEVEL)

    def next_action(
        self,
        elapsed: float,
        estimate: float,
        last_status_ago: float,
    ) -> dict[str, Any]:
        """Determine the next action to take.

        Args:
            elapsed: minutes since task started.
            estimate: accepted estimate in minutes.
            last_status_ago: minutes since last status report.

        Returns:
            Dict with 'action', 'level', 'message', and 'should_act'.
        """
        should = self.policy.should_check_in(estimate, elapsed, last_status_ago)
        level = self.current_level() + 1
        level = min(level, MAX_LEVEL)

        if not should and self.current_level() == 0:
            return {
                "action": "wait",
                "level": 0,
                "message": "",
                "should_act": False,
            }

        esc_info = ESCALATION_LEVELS.get(level, ESCALATION_LEVELS[MAX_LEVEL])
        message = self.policy.generate_check_in_message(
            level, self.employee_name, f"task-{self.task_id}",
        )

        return {
            "action": esc_info["action"],
            "level": level,
            "message": message,
            "should_act": True,
        }

    def history(self) -> list[dict[str, Any]]:
        """Full chronological history of check-ins and responses."""
        events: list[tuple[str, int, dict[str, Any]]] = []
        for i, ci in enumerate(self._check_ins):
            # Use after_check_ins=i+1 to interleave correctly
            events.append((ci["timestamp"], i * 2, {"type": "check_in", **ci}))
        for resp in self._responses:
            # Responses come after the check-ins they answer
            idx = resp["after_check_ins"]
            events.append((resp["timestamp"], idx * 2 - 1, {"type": "response", **resp}))
        events.sort(key=lambda e: (e[0], e[1]))
        return [e[2] for e in events]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "policy": self.policy.to_dict(),
            "check_ins": list(self._check_ins),
            "responses": list(self._responses),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscalationTracker:
        tracker = cls(
            task_id=data["task_id"],
            employee_id=data["employee_id"],
            employee_name=data["employee_name"],
            policy=CheckInPolicy.from_dict(data.get("policy", {})),
        )
        tracker._check_ins = list(data.get("check_ins", []))
        tracker._responses = list(data.get("responses", []))
        return tracker
