"""Corp-Collab: promotion engine with auto-promotion, ceremony, and renaming rights.

Evaluates employees for promotion based on task count, accuracy, and warmth.
Handles the full promotion ceremony including manager renaming rights at 10 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .employee import Employee, PROMOTION_TRACK
from .performance import PerformanceTracker
from .nicknames import NicknameGenerator


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Promotion Thresholds ─────────────────────────────────────────────────────

DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "role": {
        "min_tasks": 3,
        "max_overrun_rate": 0.7,
        "min_warmth": 0.0,
    },
    "senior": {
        "min_tasks": 8,
        "max_overrun_rate": 0.5,
        "min_warmth": 1.0,
    },
    "lead": {
        "min_tasks": 15,
        "max_overrun_rate": 0.4,
        "min_warmth": 2.0,
    },
    "director": {
        "min_tasks": 30,
        "max_overrun_rate": 0.3,
        "min_warmth": 4.0,
    },
}

RENAMING_THRESHOLD = 10  # tasks completed before manager can rename


# ── Promotion Result ─────────────────────────────────────────────────────────


@dataclass
class PromotionResult:
    """Outcome of a promotion evaluation or ceremony."""

    employee_id: str
    eligible: bool
    current_level: str
    next_level: Optional[str]
    reason: str
    promoted: bool = False
    new_title: Optional[str] = None
    renaming_unlocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "eligible": self.eligible,
            "current_level": self.current_level,
            "next_level": self.next_level,
            "reason": self.reason,
            "promoted": self.promoted,
            "new_title": self.new_title,
            "renaming_unlocked": self.renaming_unlocked,
        }


# ── Promotion Engine ─────────────────────────────────────────────────────────


class PromotionEngine:
    """Evaluate and execute employee promotions based on performance thresholds.

    Supports:
    - Auto-promotion evaluation based on tasks, accuracy, warmth
    - Promotion ceremony (actually promotes the employee)
    - Manager renaming rights after RENAMING_THRESHOLD tasks
    - Custom threshold overrides
    """

    def __init__(
        self,
        thresholds: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.thresholds = thresholds or dict(DEFAULT_THRESHOLDS)

    def _next_level(self, current: str) -> Optional[str]:
        """Get the next promotion level, or None if at max."""
        try:
            idx = PROMOTION_TRACK.index(current)
        except ValueError:
            return None
        if idx >= len(PROMOTION_TRACK) - 1:
            return None
        return PROMOTION_TRACK[idx + 1]

    def evaluate(
        self,
        employee: Employee,
        tracker: PerformanceTracker,
        warmth: float,
    ) -> PromotionResult:
        """Evaluate whether an employee is eligible for promotion.

        Checks:
        1. Not already at max level
        2. Meets minimum task count
        3. Overrun rate within threshold
        4. Warmth score sufficient
        """
        current = employee.promotion_level
        next_level = self._next_level(current)

        if next_level is None:
            return PromotionResult(
                employee_id=employee.id,
                eligible=False,
                current_level=current,
                next_level=None,
                reason="Already at maximum level (director)",
            )

        thresholds = self.thresholds.get(next_level)
        if thresholds is None:
            return PromotionResult(
                employee_id=employee.id,
                eligible=False,
                current_level=current,
                next_level=next_level,
                reason=f"No thresholds defined for level '{next_level}'",
            )

        # Check task count
        snap = tracker.snapshot()
        if snap.successful_tasks < thresholds["min_tasks"]:
            return PromotionResult(
                employee_id=employee.id,
                eligible=False,
                current_level=current,
                next_level=next_level,
                reason=(
                    f"Needs {thresholds['min_tasks']} successful tasks, "
                    f"has {snap.successful_tasks}"
                ),
            )

        # Check overrun rate
        if snap.overrun_rate > thresholds["max_overrun_rate"]:
            return PromotionResult(
                employee_id=employee.id,
                eligible=False,
                current_level=current,
                next_level=next_level,
                reason=(
                    f"Overrun rate {snap.overrun_rate:.0%} exceeds max "
                    f"{thresholds['max_overrun_rate']:.0%}"
                ),
            )

        # Check warmth
        if warmth < thresholds["min_warmth"]:
            return PromotionResult(
                employee_id=employee.id,
                eligible=False,
                current_level=current,
                next_level=next_level,
                reason=(
                    f"Warmth {warmth:.2f} below minimum {thresholds['min_warmth']:.2f}"
                ),
            )

        return PromotionResult(
            employee_id=employee.id,
            eligible=True,
            current_level=current,
            next_level=next_level,
            reason="Meets all promotion criteria",
        )

    def promote(
        self,
        employee: Employee,
        tracker: PerformanceTracker,
        warmth: float,
        force: bool = False,
    ) -> PromotionResult:
        """Execute a promotion ceremony — evaluate + promote if eligible.

        Set force=True to skip eligibility checks (manager override).
        """
        if not force:
            result = self.evaluate(employee, tracker, warmth)
            if not result.eligible:
                return result
        else:
            next_level = self._next_level(employee.promotion_level)
            if next_level is None:
                return PromotionResult(
                    employee_id=employee.id,
                    eligible=False,
                    current_level=employee.promotion_level,
                    next_level=None,
                    reason="Already at maximum level (director)",
                    promoted=False,
                )
            result = PromotionResult(
                employee_id=employee.id,
                eligible=True,
                current_level=employee.promotion_level,
                next_level=next_level,
                reason="Force-promoted by manager",
            )

        # Execute promotion
        new_name = employee.promote()
        result.promoted = True
        result.new_title = new_name

        # Check if renaming was just unlocked
        if employee.tasks_completed_under_manager >= RENAMING_THRESHOLD:
            result.renaming_unlocked = True

        return result

    def check_renaming_rights(self, employee: Employee) -> tuple[bool, str]:
        """Check if a manager has renaming rights for this employee.

        Rights unlock at RENAMING_THRESHOLD tasks completed.
        """
        tasks = employee.tasks_completed_under_manager
        if tasks >= RENAMING_THRESHOLD:
            return True, f"Renaming unlocked ({tasks}/{RENAMING_THRESHOLD} tasks)"
        return False, f"Needs {RENAMING_THRESHOLD - tasks} more tasks ({tasks}/{RENAMING_THRESHOLD})"

    def rename_employee(
        self,
        employee: Employee,
        new_title: str,
        taken_titles: set[str] | None = None,
    ) -> tuple[bool, str]:
        """Apply a custom manager title to an employee.

        Requires renaming rights (>= RENAMING_THRESHOLD tasks).
        Validates title via NicknameGenerator.validate_custom_title.
        """
        has_rights, reason = self.check_renaming_rights(employee)
        if not has_rights:
            return False, reason

        valid, msg = NicknameGenerator.validate_custom_title(new_title, taken_titles)
        if not valid:
            return False, msg

        employee.custom_manager_title = new_title
        return True, f"Renamed to '{new_title} {employee.nickname}'"

    def batch_evaluate(
        self,
        employees: list[tuple[Employee, PerformanceTracker, float]],
    ) -> list[PromotionResult]:
        """Evaluate multiple employees for promotion at once."""
        return [self.evaluate(emp, tracker, warmth) for emp, tracker, warmth in employees]

    def auto_promote_eligible(
        self,
        employees: list[tuple[Employee, PerformanceTracker, float]],
    ) -> list[PromotionResult]:
        """Auto-promote all eligible employees. Returns only those who were promoted."""
        results = []
        for emp, tracker, warmth in employees:
            result = self.promote(emp, tracker, warmth)
            if result.promoted:
                results.append(result)
        return results
