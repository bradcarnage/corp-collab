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


# ── Auto-Classification ─────────────────────────────────────────────────────


class TestAutoClassify:
    def test_empty_string(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("").tier == "C1"

    def test_c1_simple_task(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("rename the config file").tier == "C1"

    def test_c1_status_check(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("show server status").tier == "C1"

    def test_c2_implement(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("implement the login endpoint").tier == "C2"

    def test_c2_fix_bug(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("fix the authentication bug").tier == "C2"

    def test_c3_investigate(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("investigate why the service is slow").tier == "C3"

    def test_c3_design(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("design the new API spec").tier == "C3"

    def test_c3_refactor(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("refactor the database layer").tier == "C3"

    def test_c4_cross_domain(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("cross-domain migration of all services").tier == "C4"

    def test_c4_hire(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("hire a new researcher to investigate").tier == "C4"

    def test_c4_orchestrate(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("orchestrate deployment across teams").tier == "C4"

    def test_c4_security_audit(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("perform a security audit of all endpoints").tier == "C4"

    def test_highest_tier_wins(self):
        from corp_collab.complexity import auto_classify
        # Has both C2 (implement) and C4 (cross-domain) keywords
        result = auto_classify("implement a cross-domain service migration")
        assert result.tier == "C4"

    def test_no_match_defaults_c1(self):
        from corp_collab.complexity import auto_classify
        assert auto_classify("do the thing").tier == "C1"


# ── Classify with Context ───────────────────────────────────────────────────


class TestClassifyWithContext:
    def test_keyword_higher_than_rules(self):
        from corp_collab.complexity import classify_with_context
        # Keywords say C3 (investigate), rules say C1 (1 subtask, not ambiguous)
        result = classify_with_context("investigate the memory leak")
        assert result.tier == "C3"

    def test_rules_higher_than_keywords(self):
        from corp_collab.complexity import classify_with_context
        # Keywords say C1 (rename), rules say C4 (requires_delegation)
        result = classify_with_context("rename files", requires_delegation=True)
        assert result.tier == "C4"

    def test_both_agree(self):
        from corp_collab.complexity import classify_with_context
        result = classify_with_context("implement the feature", subtask_count=2)
        assert result.tier == "C2"

    def test_subtask_count_boosts(self):
        from corp_collab.complexity import classify_with_context
        result = classify_with_context("rename the file", subtask_count=4)
        assert result.tier == "C4"


# ── Calibrated Time Estimate ────────────────────────────────────────────────


class TestCalibratedTimeEstimate:
    def test_default_no_employee(self):
        from corp_collab.complexity import calibrated_time_estimate
        c = TaskComplexity.for_tier("C2")
        assert calibrated_time_estimate(c) == 30.0

    def test_with_employee_no_history(self, tmp_path):
        from corp_collab.complexity import calibrated_time_estimate
        c = TaskComplexity.for_tier("C2")
        result = calibrated_time_estimate(c, employee_id="emp-none", base_path=tmp_path)
        assert result == 30.0  # no history → factor=1.0

    def test_with_employee_history(self, tmp_path):
        from corp_collab.complexity import calibrated_time_estimate
        from corp_collab.performance import PerformanceTracker
        tracker = PerformanceTracker("emp-cal", base_path=tmp_path)
        # ratio 1.5 across 3 tasks
        for i in range(3):
            tracker.record_task(f"t{i}", "C2", 30.0, 45.0)
        c = TaskComplexity.for_tier("C2")
        result = calibrated_time_estimate(c, employee_id="emp-cal", base_path=tmp_path)
        assert result == 45.0  # 30 * 1.5
