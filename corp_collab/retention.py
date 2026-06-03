"""Corp-Collab: retention engine — warmth-based retention enforcement with manager approval.

Evaluates the workforce for retention risk, proposes terminations for cold employees,
enforces grace periods, and requires manager approval before firing. Integrates with
the handoff system for proper offboarding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RetentionAction(str, Enum):
    """Possible retention actions for an employee."""
    RETAIN = "retain"
    WARN = "warn"
    GRACE_PERIOD = "grace_period"
    PROPOSE_TERMINATION = "propose_termination"
    TERMINATE = "terminate"


@dataclass
class RetentionPolicy:
    """Configurable retention thresholds."""
    max_idle: int = 5
    warmth_warn_threshold: float = 0.5
    warmth_terminate_threshold: float = 0.0
    grace_period_seconds: float = 3600.0  # 1 hour default
    min_tasks_before_review: int = 1  # at least 1 task before eligible for termination
    protected_levels: tuple[str, ...] = ("lead", "director")  # these need extra approval

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_idle": self.max_idle,
            "warmth_warn_threshold": self.warmth_warn_threshold,
            "warmth_terminate_threshold": self.warmth_terminate_threshold,
            "grace_period_seconds": self.grace_period_seconds,
            "min_tasks_before_review": self.min_tasks_before_review,
            "protected_levels": list(self.protected_levels),
        }


@dataclass
class RetentionReview:
    """Result of evaluating one employee for retention."""
    employee_id: str
    employee_name: str
    warmth: float
    action: RetentionAction
    reason: str
    grace_deadline: float | None = None  # unix timestamp when grace expires
    requires_approval: bool = False
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "warmth": self.warmth,
            "action": self.action.value,
            "reason": self.reason,
            "grace_deadline": self.grace_deadline,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
        }


@dataclass
class RetentionReport:
    """Batch retention review results."""
    reviews: list[RetentionReview] = field(default_factory=list)
    proposed_terminations: list[RetentionReview] = field(default_factory=list)
    warnings: list[RetentionReview] = field(default_factory=list)
    retained: list[RetentionReview] = field(default_factory=list)
    over_capacity: bool = False

    @property
    def total_reviewed(self) -> int:
        return len(self.reviews)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_reviewed": self.total_reviewed,
            "over_capacity": self.over_capacity,
            "proposed_terminations": [r.to_dict() for r in self.proposed_terminations],
            "warnings": [r.to_dict() for r in self.warnings],
            "retained_count": len(self.retained),
        }


class RetentionEngine:
    """Evaluate workforce retention and propose/execute terminations.

    Flow:
    1. review_workforce() → RetentionReport with proposed actions
    2. Manager approves/rejects proposed terminations
    3. execute_termination() → offboards via handoff system
    """

    def __init__(self, policy: RetentionPolicy | None = None):
        self.policy = policy or RetentionPolicy()
        self._grace_periods: dict[str, float] = {}  # employee_id → deadline timestamp

    def review_employee(self, employee: Any, warmth: float) -> RetentionReview:
        """Evaluate a single employee for retention risk."""
        emp_id = employee.id
        emp_name = getattr(employee, "full_name", getattr(employee, "nickname", emp_id))
        level = getattr(employee, "promotion_level", "intern")
        tasks = getattr(employee, "tasks_completed_under_manager", 0)
        status = getattr(employee, "status", "idle")

        # Active employees always retained
        if status == "active":
            return RetentionReview(
                employee_id=emp_id,
                employee_name=emp_name,
                warmth=warmth,
                action=RetentionAction.RETAIN,
                reason="Currently active",
            )

        # Too few tasks — not enough data for review
        if tasks < self.policy.min_tasks_before_review:
            return RetentionReview(
                employee_id=emp_id,
                employee_name=emp_name,
                warmth=warmth,
                action=RetentionAction.RETAIN,
                reason=f"Only {tasks} tasks completed, below review threshold",
            )

        # Check warmth against thresholds
        if warmth <= self.policy.warmth_terminate_threshold:
            # Check if already in grace period
            if emp_id in self._grace_periods:
                deadline = self._grace_periods[emp_id]
                if time.time() >= deadline:
                    # Grace period expired
                    is_protected = level in self.policy.protected_levels
                    return RetentionReview(
                        employee_id=emp_id,
                        employee_name=emp_name,
                        warmth=warmth,
                        action=RetentionAction.PROPOSE_TERMINATION,
                        reason=f"Warmth {warmth:.2f} at/below termination threshold, grace period expired",
                        requires_approval=is_protected,
                    )
                else:
                    return RetentionReview(
                        employee_id=emp_id,
                        employee_name=emp_name,
                        warmth=warmth,
                        action=RetentionAction.GRACE_PERIOD,
                        reason=f"In grace period until {deadline:.0f}",
                        grace_deadline=deadline,
                    )
            else:
                # Start grace period
                deadline = time.time() + self.policy.grace_period_seconds
                self._grace_periods[emp_id] = deadline
                return RetentionReview(
                    employee_id=emp_id,
                    employee_name=emp_name,
                    warmth=warmth,
                    action=RetentionAction.GRACE_PERIOD,
                    reason=f"Warmth {warmth:.2f} at/below threshold, grace period started",
                    grace_deadline=deadline,
                )

        elif warmth < self.policy.warmth_warn_threshold:
            return RetentionReview(
                employee_id=emp_id,
                employee_name=emp_name,
                warmth=warmth,
                action=RetentionAction.WARN,
                reason=f"Warmth {warmth:.2f} below warning threshold {self.policy.warmth_warn_threshold:.2f}",
            )

        # Clear grace period if warmth recovered
        self._grace_periods.pop(emp_id, None)

        return RetentionReview(
            employee_id=emp_id,
            employee_name=emp_name,
            warmth=warmth,
            action=RetentionAction.RETAIN,
            reason=f"Warmth {warmth:.2f} above thresholds",
        )

    def review_workforce(
        self,
        employees_with_warmth: list[tuple[Any, float]],
    ) -> RetentionReport:
        """Review all employees and generate retention report.

        Args:
            employees_with_warmth: list of (employee, warmth_score) tuples
        """
        report = RetentionReport()

        idle_count = sum(
            1 for emp, _ in employees_with_warmth
            if getattr(emp, "status", "idle") == "idle"
        )
        report.over_capacity = idle_count > self.policy.max_idle

        for emp, warmth in employees_with_warmth:
            review = self.review_employee(emp, warmth)
            report.reviews.append(review)

            if review.action == RetentionAction.PROPOSE_TERMINATION:
                report.proposed_terminations.append(review)
            elif review.action in (RetentionAction.WARN, RetentionAction.GRACE_PERIOD):
                report.warnings.append(review)
            else:
                report.retained.append(review)

        return report

    def approve_termination(self, review: RetentionReview) -> RetentionReview:
        """Manager approves a proposed termination."""
        if review.action != RetentionAction.PROPOSE_TERMINATION:
            raise ValueError(f"Cannot approve non-termination review (action={review.action})")
        review.approved = True
        review.action = RetentionAction.TERMINATE
        return review

    def reject_termination(self, review: RetentionReview) -> RetentionReview:
        """Manager rejects a proposed termination — employee gets a fresh grace period."""
        if review.action != RetentionAction.PROPOSE_TERMINATION:
            raise ValueError(f"Cannot reject non-termination review (action={review.action})")
        # Reset grace period
        deadline = time.time() + self.policy.grace_period_seconds
        self._grace_periods[review.employee_id] = deadline
        review.action = RetentionAction.GRACE_PERIOD
        review.grace_deadline = deadline
        review.reason = "Termination rejected by manager, grace period reset"
        return review

    def execute_termination(
        self,
        review: RetentionReview,
        roster: Any,
        reason: str = "Low warmth retention policy",
    ) -> dict[str, Any]:
        """Execute an approved termination via the roster's terminate flow.

        Returns the handoff/termination result from roster.
        """
        if review.action != RetentionAction.TERMINATE:
            raise ValueError("Can only execute approved terminations")

        # Clean up grace period tracking
        self._grace_periods.pop(review.employee_id, None)

        # Delegate to roster.terminate() which handles handoff generation
        result = roster.terminate(review.employee_id, reason=reason)
        return result

    def force_retain(self, employee_id: str) -> None:
        """Manager force-retains an employee — clears any grace period or pending review."""
        self._grace_periods.pop(employee_id, None)

    def get_grace_status(self, employee_id: str) -> dict[str, Any] | None:
        """Check if an employee is in a grace period."""
        if employee_id not in self._grace_periods:
            return None
        deadline = self._grace_periods[employee_id]
        remaining = max(0.0, deadline - time.time())
        return {
            "employee_id": employee_id,
            "deadline": deadline,
            "remaining_seconds": remaining,
            "expired": remaining == 0.0,
        }

    def clear_grace_period(self, employee_id: str) -> bool:
        """Clear grace period for an employee (e.g., they completed new work)."""
        if employee_id in self._grace_periods:
            del self._grace_periods[employee_id]
            return True
        return False

    @property
    def active_grace_periods(self) -> dict[str, float]:
        """Return all active grace periods (employee_id → deadline)."""
        return dict(self._grace_periods)
