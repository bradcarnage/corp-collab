"""Corp-Collab: complexity assessment with C1-C4 tiers and time estimation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Complexity Tiers ─────────────────────────────────────────────────────────

TIER_DEFINITIONS: dict[str, dict[str, Any]] = {
    "C1": {
        "description": "Single-step task, any employee, no delegation",
        "default_estimate_minutes": 5,
        "can_delegate": False,
        "min_level": "intern",
    },
    "C2": {
        "description": "Multi-step with clear spec, employee-level, no delegation",
        "default_estimate_minutes": 30,
        "can_delegate": False,
        "min_level": "role",
    },
    "C3": {
        "description": "Ambiguous task requiring senior+ with permission",
        "default_estimate_minutes": 60,
        "can_delegate": True,
        "min_level": "senior",
    },
    "C4": {
        "description": "Cross-domain task requiring manager with delegation",
        "default_estimate_minutes": 120,
        "can_delegate": True,
        "min_level": "lead",
    },
}


@dataclass(frozen=True)
class TaskComplexity:
    """Immutable description of a task's complexity tier."""

    tier: str
    description: str
    default_estimate_minutes: int
    can_delegate: bool
    min_level: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "description": self.description,
            "default_estimate_minutes": self.default_estimate_minutes,
            "can_delegate": self.can_delegate,
            "min_level": self.min_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskComplexity:
        return cls(
            tier=data["tier"],
            description=data["description"],
            default_estimate_minutes=data["default_estimate_minutes"],
            can_delegate=data["can_delegate"],
            min_level=data["min_level"],
        )

    @classmethod
    def for_tier(cls, tier: str) -> TaskComplexity:
        """Build a TaskComplexity from a known tier name (C1-C4)."""
        tier = tier.upper()
        if tier not in TIER_DEFINITIONS:
            raise ValueError(f"Unknown tier: {tier}. Choose from {list(TIER_DEFINITIONS)}")
        defn = TIER_DEFINITIONS[tier]
        return cls(tier=tier, **defn)


# ── Time Estimation ──────────────────────────────────────────────────────────


@dataclass
class TimeEstimate:
    """Manager's time estimate enriched with complexity-aware helpers."""

    manager_estimate: float  # minutes
    complexity: TaskComplexity
    escalation_multiplier: float = 1.4
    _employee_counter: float | None = field(default=None, repr=False)
    _accepted: float | None = field(default=None, repr=False)

    def employee_counter_estimate(self, minutes: float | None = None) -> float:
        """Record or retrieve the employee's counter-estimate."""
        if minutes is not None:
            self._employee_counter = minutes
        if self._employee_counter is None:
            return self.manager_estimate
        return self._employee_counter

    def accepted_estimate(self) -> float:
        """The working estimate: max of manager and employee estimates."""
        counter = self._employee_counter if self._employee_counter is not None else self.manager_estimate
        if self._accepted is not None:
            return self._accepted
        return max(self.manager_estimate, counter)

    def set_accepted(self, minutes: float) -> None:
        """Explicitly override the accepted estimate."""
        self._accepted = minutes

    def is_overdue(self, elapsed: float) -> bool:
        """True if elapsed minutes exceed the accepted estimate."""
        return elapsed > self.accepted_estimate()

    def escalation_threshold_minutes(self) -> float:
        """Minutes after which escalation should trigger (accepted * multiplier)."""
        return self.accepted_estimate() * self.escalation_multiplier

    def to_dict(self) -> dict[str, Any]:
        return {
            "manager_estimate": self.manager_estimate,
            "complexity": self.complexity.to_dict(),
            "escalation_multiplier": self.escalation_multiplier,
            "employee_counter": self._employee_counter,
            "accepted": self._accepted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeEstimate:
        te = cls(
            manager_estimate=data["manager_estimate"],
            complexity=TaskComplexity.from_dict(data["complexity"]),
            escalation_multiplier=data.get("escalation_multiplier", 1.4),
        )
        te._employee_counter = data.get("employee_counter")
        te._accepted = data.get("accepted")
        return te


# ── Assessment ───────────────────────────────────────────────────────────────


def assess_complexity(
    description: str,
    subtask_count: int = 1,
    requires_delegation: bool = False,
    ambiguous: bool = False,
) -> TaskComplexity:
    """Heuristic complexity assessment returning a TaskComplexity.

    Rules (applied in order of descending severity):
    - requires_delegation or subtask_count >= 4 → C4
    - ambiguous or subtask_count >= 2 → C3
    - subtask_count > 1 → C2
    - otherwise → C1
    """
    if requires_delegation or subtask_count >= 4:
        return TaskComplexity.for_tier("C4")
    if ambiguous or subtask_count >= 3:
        return TaskComplexity.for_tier("C3")
    if subtask_count >= 2:
        return TaskComplexity.for_tier("C2")
    return TaskComplexity.for_tier("C1")
