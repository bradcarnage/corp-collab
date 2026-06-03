"""Tests for corp_collab.retention — warmth-based retention with manager approval."""

import time
from unittest.mock import MagicMock, patch

import pytest

from corp_collab.retention import (
    RetentionAction,
    RetentionEngine,
    RetentionPolicy,
    RetentionReport,
    RetentionReview,
)


def _mock_employee(
    emp_id="emp-001",
    nickname="Turing",
    status="idle",
    level="intern",
    tasks=5,
):
    emp = MagicMock()
    emp.id = emp_id
    emp.full_name = f"{level.capitalize()} {nickname}"
    emp.nickname = nickname
    emp.promotion_level = level
    emp.tasks_completed_under_manager = tasks
    emp.status = status
    return emp


@pytest.fixture
def engine():
    return RetentionEngine()


@pytest.fixture
def strict_engine():
    policy = RetentionPolicy(
        warmth_warn_threshold=1.0,
        warmth_terminate_threshold=0.2,
        grace_period_seconds=0.01,  # near-instant for testing
    )
    return RetentionEngine(policy=policy)


# ── Single Employee Review ───────────────────────────────────────────────────


class TestReviewEmployee:
    def test_active_always_retained(self, engine):
        emp = _mock_employee(status="active")
        result = engine.review_employee(emp, warmth=-5.0)
        assert result.action == RetentionAction.RETAIN
        assert "active" in result.reason.lower()

    def test_too_few_tasks(self, engine):
        emp = _mock_employee(tasks=0)
        result = engine.review_employee(emp, warmth=-1.0)
        assert result.action == RetentionAction.RETAIN
        assert "threshold" in result.reason.lower()

    def test_warm_employee_retained(self, engine):
        emp = _mock_employee()
        result = engine.review_employee(emp, warmth=2.0)
        assert result.action == RetentionAction.RETAIN

    def test_below_warn_threshold(self, engine):
        emp = _mock_employee()
        result = engine.review_employee(emp, warmth=0.3)
        assert result.action == RetentionAction.WARN

    def test_at_terminate_threshold_starts_grace(self, engine):
        emp = _mock_employee()
        result = engine.review_employee(emp, warmth=0.0)
        assert result.action == RetentionAction.GRACE_PERIOD
        assert result.grace_deadline is not None

    def test_grace_period_not_expired(self, engine):
        emp = _mock_employee()
        # First call starts grace
        engine.review_employee(emp, warmth=0.0)
        # Second call — still in grace
        result = engine.review_employee(emp, warmth=0.0)
        assert result.action == RetentionAction.GRACE_PERIOD

    def test_grace_period_expired_proposes_termination(self, strict_engine):
        emp = _mock_employee()
        # Start grace
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)  # wait for grace to expire
        result = strict_engine.review_employee(emp, warmth=0.0)
        assert result.action == RetentionAction.PROPOSE_TERMINATION

    def test_protected_level_requires_approval(self, strict_engine):
        emp = _mock_employee(level="lead")
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        result = strict_engine.review_employee(emp, warmth=0.0)
        assert result.action == RetentionAction.PROPOSE_TERMINATION
        assert result.requires_approval is True

    def test_non_protected_no_extra_approval(self, strict_engine):
        emp = _mock_employee(level="intern")
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        result = strict_engine.review_employee(emp, warmth=0.0)
        assert result.requires_approval is False

    def test_warmth_recovery_clears_grace(self, engine):
        emp = _mock_employee()
        engine.review_employee(emp, warmth=0.0)
        assert emp.id in engine.active_grace_periods
        # Warmth recovers
        engine.review_employee(emp, warmth=2.0)
        assert emp.id not in engine.active_grace_periods


# ── Workforce Review ─────────────────────────────────────────────────────────


class TestReviewWorkforce:
    def test_basic_report(self, engine):
        emps = [
            (_mock_employee(emp_id="e1"), 5.0),
            (_mock_employee(emp_id="e2"), 0.3),
        ]
        report = engine.review_workforce(emps)
        assert report.total_reviewed == 2
        assert len(report.retained) == 1
        assert len(report.warnings) == 1

    def test_over_capacity_detected(self, engine):
        # Default max_idle=5, create 6 idle
        emps = [(_mock_employee(emp_id=f"e{i}"), 5.0) for i in range(6)]
        report = engine.review_workforce(emps)
        assert report.over_capacity is True

    def test_under_capacity(self, engine):
        emps = [(_mock_employee(emp_id=f"e{i}"), 5.0) for i in range(3)]
        report = engine.review_workforce(emps)
        assert report.over_capacity is False

    def test_mixed_actions(self, strict_engine):
        emp_warm = _mock_employee(emp_id="warm")
        emp_cold = _mock_employee(emp_id="cold")
        # Pre-seed grace period for cold employee
        strict_engine.review_employee(emp_cold, warmth=0.0)
        time.sleep(0.02)

        report = strict_engine.review_workforce([
            (emp_warm, 5.0),
            (emp_cold, 0.0),
        ])
        assert len(report.proposed_terminations) == 1
        assert len(report.retained) == 1

    def test_report_to_dict(self, engine):
        report = engine.review_workforce([(_mock_employee(), 5.0)])
        d = report.to_dict()
        assert "total_reviewed" in d
        assert "over_capacity" in d
        assert d["retained_count"] == 1


# ── Manager Approval Flow ───────────────────────────────────────────────────


class TestApprovalFlow:
    def test_approve_termination(self, strict_engine):
        emp = _mock_employee()
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        review = strict_engine.review_employee(emp, warmth=0.0)
        assert review.action == RetentionAction.PROPOSE_TERMINATION

        approved = strict_engine.approve_termination(review)
        assert approved.action == RetentionAction.TERMINATE
        assert approved.approved is True

    def test_reject_termination_resets_grace(self, strict_engine):
        emp = _mock_employee()
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        review = strict_engine.review_employee(emp, warmth=0.0)

        rejected = strict_engine.reject_termination(review)
        assert rejected.action == RetentionAction.GRACE_PERIOD
        assert rejected.grace_deadline is not None
        assert emp.id in strict_engine.active_grace_periods

    def test_approve_non_termination_raises(self, engine):
        review = RetentionReview(
            employee_id="e1", employee_name="Test", warmth=5.0,
            action=RetentionAction.RETAIN, reason="test",
        )
        with pytest.raises(ValueError, match="non-termination"):
            engine.approve_termination(review)

    def test_reject_non_termination_raises(self, engine):
        review = RetentionReview(
            employee_id="e1", employee_name="Test", warmth=5.0,
            action=RetentionAction.RETAIN, reason="test",
        )
        with pytest.raises(ValueError, match="non-termination"):
            engine.reject_termination(review)


# ── Execute Termination ──────────────────────────────────────────────────────


class TestExecuteTermination:
    def test_execute_calls_roster_terminate(self, strict_engine):
        emp = _mock_employee()
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        review = strict_engine.review_employee(emp, warmth=0.0)
        approved = strict_engine.approve_termination(review)

        mock_roster = MagicMock()
        mock_roster.terminate.return_value = {"status": "terminated", "handoff": "doc123"}
        result = strict_engine.execute_termination(approved, mock_roster)

        mock_roster.terminate.assert_called_once_with(emp.id, reason="Low warmth retention policy")
        assert result["status"] == "terminated"
        assert emp.id not in strict_engine.active_grace_periods

    def test_execute_unapproved_raises(self, engine):
        review = RetentionReview(
            employee_id="e1", employee_name="Test", warmth=0.0,
            action=RetentionAction.PROPOSE_TERMINATION, reason="test",
        )
        with pytest.raises(ValueError, match="approved"):
            engine.execute_termination(review, MagicMock())

    def test_custom_reason(self, strict_engine):
        emp = _mock_employee()
        strict_engine.review_employee(emp, warmth=0.0)
        time.sleep(0.02)
        review = strict_engine.review_employee(emp, warmth=0.0)
        approved = strict_engine.approve_termination(review)

        mock_roster = MagicMock()
        mock_roster.terminate.return_value = {}
        strict_engine.execute_termination(approved, mock_roster, reason="Budget cuts")
        mock_roster.terminate.assert_called_once_with(emp.id, reason="Budget cuts")


# ── Grace Period Management ──────────────────────────────────────────────────


class TestGracePeriod:
    def test_get_status(self, engine):
        emp = _mock_employee()
        engine.review_employee(emp, warmth=0.0)
        status = engine.get_grace_status(emp.id)
        assert status is not None
        assert status["remaining_seconds"] > 0
        assert status["expired"] is False

    def test_get_status_none(self, engine):
        assert engine.get_grace_status("nonexistent") is None

    def test_clear_grace(self, engine):
        emp = _mock_employee()
        engine.review_employee(emp, warmth=0.0)
        assert engine.clear_grace_period(emp.id) is True
        assert engine.get_grace_status(emp.id) is None

    def test_clear_nonexistent(self, engine):
        assert engine.clear_grace_period("nope") is False

    def test_force_retain(self, engine):
        emp = _mock_employee()
        engine.review_employee(emp, warmth=0.0)
        engine.force_retain(emp.id)
        assert emp.id not in engine.active_grace_periods


# ── Policy Config ────────────────────────────────────────────────────────────


class TestPolicy:
    def test_default_policy(self):
        p = RetentionPolicy()
        assert p.max_idle == 5
        assert p.warmth_warn_threshold == 0.5

    def test_custom_policy(self):
        p = RetentionPolicy(max_idle=10, warmth_warn_threshold=2.0)
        assert p.max_idle == 10

    def test_policy_to_dict(self):
        p = RetentionPolicy()
        d = p.to_dict()
        assert "max_idle" in d
        assert "protected_levels" in d
        assert isinstance(d["protected_levels"], list)

    def test_review_to_dict(self):
        r = RetentionReview(
            employee_id="e1", employee_name="Test", warmth=1.5,
            action=RetentionAction.WARN, reason="low warmth",
        )
        d = r.to_dict()
        assert d["action"] == "warn"
        assert d["warmth"] == 1.5
