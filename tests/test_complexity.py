"""Tests for corp_collab.complexity — C1-C4 tiers and time estimation."""

import pytest

from corp_collab.complexity import (
    TaskComplexity,
    TimeEstimate,
    assess_complexity,
    TIER_DEFINITIONS,
)


# ── TaskComplexity ───────────────────────────────────────────────────────────


class TestTaskComplexity:
    def test_for_tier_c1(self):
        c = TaskComplexity.for_tier("C1")
        assert c.tier == "C1"
        assert c.default_estimate_minutes == 5
        assert c.can_delegate is False
        assert c.min_level == "intern"

    def test_for_tier_c2(self):
        c = TaskComplexity.for_tier("C2")
        assert c.tier == "C2"
        assert c.default_estimate_minutes == 30
        assert c.can_delegate is False
        assert c.min_level == "role"

    def test_for_tier_c3(self):
        c = TaskComplexity.for_tier("C3")
        assert c.tier == "C3"
        assert c.default_estimate_minutes == 60
        assert c.can_delegate is True
        assert c.min_level == "senior"

    def test_for_tier_c4(self):
        c = TaskComplexity.for_tier("C4")
        assert c.tier == "C4"
        assert c.default_estimate_minutes == 120
        assert c.can_delegate is True
        assert c.min_level == "lead"

    def test_for_tier_case_insensitive(self):
        c = TaskComplexity.for_tier("c2")
        assert c.tier == "C2"

    def test_for_tier_invalid(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            TaskComplexity.for_tier("C5")

    def test_roundtrip_dict(self):
        c = TaskComplexity.for_tier("C3")
        d = c.to_dict()
        c2 = TaskComplexity.from_dict(d)
        assert c == c2

    def test_frozen(self):
        c = TaskComplexity.for_tier("C1")
        with pytest.raises(AttributeError):
            c.tier = "C2"  # type: ignore


# ── TimeEstimate ─────────────────────────────────────────────────────────────


class TestTimeEstimate:
    def make_estimate(self, minutes: float = 30.0, tier: str = "C2") -> TimeEstimate:
        return TimeEstimate(
            manager_estimate=minutes,
            complexity=TaskComplexity.for_tier(tier),
        )

    def test_defaults(self):
        te = self.make_estimate()
        assert te.manager_estimate == 30.0
        assert te.escalation_multiplier == 1.4

    def test_accepted_uses_manager_when_no_counter(self):
        te = self.make_estimate(30)
        assert te.accepted_estimate() == 30.0

    def test_employee_counter_estimate(self):
        te = self.make_estimate(30)
        te.employee_counter_estimate(45)
        assert te.employee_counter_estimate() == 45
        # accepted should be max of manager and counter
        assert te.accepted_estimate() == 45

    def test_accepted_takes_max(self):
        te = self.make_estimate(50)
        te.employee_counter_estimate(30)
        assert te.accepted_estimate() == 50  # manager > counter

    def test_set_accepted_override(self):
        te = self.make_estimate(30)
        te.set_accepted(20)
        assert te.accepted_estimate() == 20

    def test_is_overdue(self):
        te = self.make_estimate(30)
        assert te.is_overdue(29) is False
        assert te.is_overdue(30) is False
        assert te.is_overdue(31) is True

    def test_escalation_threshold(self):
        te = self.make_estimate(100)
        assert te.escalation_threshold_minutes() == 140.0

    def test_roundtrip_dict(self):
        te = self.make_estimate(30)
        te.employee_counter_estimate(40)
        d = te.to_dict()
        te2 = TimeEstimate.from_dict(d)
        assert te2.manager_estimate == 30
        assert te2.employee_counter_estimate() == 40
        assert te2.complexity.tier == "C2"


# ── assess_complexity ────────────────────────────────────────────────────────


class TestAssessComplexity:
    def test_single_step_returns_c1(self):
        c = assess_complexity("simple task")
        assert c.tier == "C1"

    def test_two_subtasks_returns_c2(self):
        c = assess_complexity("multi-step task", subtask_count=2)
        assert c.tier == "C2"

    def test_three_subtasks_returns_c3(self):
        c = assess_complexity("complex task", subtask_count=3)
        assert c.tier == "C3"

    def test_ambiguous_returns_c3(self):
        c = assess_complexity("unclear task", ambiguous=True)
        assert c.tier == "C3"

    def test_four_subtasks_returns_c4(self):
        c = assess_complexity("big task", subtask_count=4)
        assert c.tier == "C4"

    def test_delegation_returns_c4(self):
        c = assess_complexity("delegated task", requires_delegation=True)
        assert c.tier == "C4"

    def test_delegation_overrides_low_subtask(self):
        c = assess_complexity("delegated", subtask_count=1, requires_delegation=True)
        assert c.tier == "C4"
