"""Corp-Collab tool: escalate.

Check-in escalation for overdue or unresponsive employees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def escalate(
    manager_id: str,
    employee_id: str,
    task_id: str,
    estimate_dict: dict[str, Any],
    elapsed_minutes: float,
    last_status_ago: Optional[float] = None,
    tracker_dict: Optional[dict[str, Any]] = None,
    base_path: Optional[str | Path] = None,
) -> dict:
    """Run the escalation ladder for an employee/task.

    Args:
        manager_id: The manager performing escalation.
        employee_id: The employee being escalated.
        task_id: The task ID.
        estimate_dict: {manager_estimate, complexity, multiplier} for TimeEstimate.
        elapsed_minutes: Minutes since task started.
        last_status_ago: Minutes since last status report (defaults to elapsed).
        tracker_dict: Serialized EscalationTracker state (or None for new).
        base_path: Base path for mailbox storage.

    Returns:
        {action_taken: bool, level: int, action: str|None, tracker: dict}
        or {error: str}.
    """
    try:
        from corp_collab.checkin import EscalationTracker, CheckInPolicy
        from corp_collab.complexity import TimeEstimate, TaskComplexity
        from corp_collab.mailbox import Mailbox

        bp = Path(base_path) if base_path else DEFAULT_BASE

        if last_status_ago is None:
            last_status_ago = elapsed_minutes

        # Build or restore tracker
        if tracker_dict:
            tracker = EscalationTracker.from_dict(tracker_dict)
        else:
            tracker = EscalationTracker(
                task_id=task_id,
                employee_id=employee_id,
                employee_name=employee_id,  # fallback name
            )

        # Build TimeEstimate
        manager_est = estimate_dict.get("manager_estimate", 30)
        complexity_tier = estimate_dict.get("complexity", "C1")
        multiplier = estimate_dict.get("multiplier", 1.4)

        if isinstance(complexity_tier, dict):
            complexity = TaskComplexity.from_dict(complexity_tier)
        else:
            complexity = TaskComplexity.for_tier(str(complexity_tier))

        estimate = TimeEstimate(
            manager_estimate=manager_est,
            complexity=complexity,
            escalation_multiplier=multiplier,
        )

        # Determine next action
        accepted = estimate.accepted_estimate()
        result = tracker.next_action(
            elapsed=elapsed_minutes,
            estimate=accepted,
            last_status_ago=last_status_ago,
        )

        action_taken = False
        action_str = result.get("action")

        if result.get("should_act"):
            level = result["level"]
            message = result["message"]

            # Send message to employee's mailbox
            db_path = bp / "employees" / employee_id / "mailbox.db"
            mbox = Mailbox(employee_id, db_path=db_path)
            try:
                if action_str == "send_im":
                    mbox.send(
                        channel="im",
                        to_id=employee_id,
                        to_name=employee_id,
                        from_id=manager_id,
                        from_name=manager_id,
                        body=message,
                    )
                elif action_str in ("send_urgent_email", "investigate", "intervene", "fire_and_rehire"):
                    mbox.send(
                        channel="email",
                        to_id=employee_id,
                        to_name=employee_id,
                        from_id=manager_id,
                        from_name=manager_id,
                        subject=f"Escalation L{level}: {task_id}",
                        body=message,
                        priority="urgent",
                    )
            finally:
                mbox.close()

            tracker.record_check_in(level)
            action_taken = True

        return {
            "action_taken": action_taken,
            "level": result.get("level", 0),
            "action": action_str,
            "tracker": tracker.to_dict(),
        }

    except Exception as e:
        return {"error": str(e)}
