"""Tests for corp_collab.promotion — auto-promotion, ceremony, renaming rights."""

from pathlib import Path

import pytest

from corp_collab.employee import Employee, PROMOTION_TRACK
from corp_collab.nicknames import NicknameGenerator
from corp_collab.performance import PerformanceTracker
from corp_collab.promotion import PromotionEngine, RENAMING_THRESHOLD, DEFAULT_THRESHOLDS


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path / "employees"


@pytest.fixture
def nicknames():
    return NicknameGenerator(seed=42)


@pytest.fixture
def engine():
    return PromotionEngine()


def _make_employee(tmp_base, nicknames, role="engineer", tasks_completed=0, level="intern"):
    emp = Employee.create(role=role, hired_by="mgr-boss", nicknames=nicknames)
    emp.promotion_level = level
    emp.tasks_completed_under_manager = tasks_completed
    if level == "role":
        emp.title = role.capitalize()
    elif level == "senior":
        emp.title = f"Senior {role.capitalize()}"
    elif level == "lead":
        emp.title = f"Lead {role.capitalize()}"
        emp.can_delegate = True
        emp.max_subordinates = 3
    return emp


def _make_tracker(tmp_base, emp_id, n_tasks=0, ratio=1.0, success=True):
    tracker = PerformanceTracker(emp_id, base_path=tmp_base)
    for i in range(n_tasks):
        tracker.record_task(
            f"t{i}", "C2", 30.0, 30.0 * ratio,
            completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            success=success,
        )
    return tracker


# ── Evaluation ───────────────────────────────────────────────────────────────


class TestEvaluation:
    def test_eligible_for_role(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=5)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=5, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=0.5)
        assert result.eligible is True
        assert result.next_level == "role"

    def test_not_enough_tasks(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=1)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=1, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=0.5)
        assert result.eligible is False
        assert "tasks" in result.reason.lower()

    def test_overrun_rate_too_high(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=10, level="role")
        tracker = PerformanceTracker(emp.id, base_path=tmp_base)
        # 8 overruns out of 10 = 80% overrun rate (need 8+ tasks for senior threshold)
        for i in range(10):
            tracker.record_task(
                f"t{i}", "C2", 30.0, 60.0 if i < 8 else 25.0,
                completed_at=f"2026-01-{i + 1:02d}T00:00:00Z",
            )
        result = engine.evaluate(emp, tracker, warmth=2.0)
        assert result.eligible is False
        assert "overrun" in result.reason.lower()

    def test_warmth_too_low(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=10, level="role")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=10, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=0.5)
        assert result.eligible is False
        assert "warmth" in result.reason.lower()

    def test_already_max_level(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=50, level="director")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=50, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=10.0)
        assert result.eligible is False
        assert "maximum" in result.reason.lower()

    def test_eligible_for_senior(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=10, level="role")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=10, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=2.0)
        assert result.eligible is True
        assert result.next_level == "senior"

    def test_eligible_for_lead(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=20, level="senior")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=20, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=3.0)
        assert result.eligible is True
        assert result.next_level == "lead"

    def test_eligible_for_director(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=35, level="lead")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=35, ratio=1.0)
        result = engine.evaluate(emp, tracker, warmth=5.0)
        assert result.eligible is True
        assert result.next_level == "director"


# ── Promotion Ceremony ───────────────────────────────────────────────────────


class TestCeremony:
    def test_promote_eligible(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=5)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=5, ratio=1.0)
        result = engine.promote(emp, tracker, warmth=0.5)
        assert result.promoted is True
        assert emp.promotion_level == "role"
        assert result.new_title is not None

    def test_promote_not_eligible(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=0)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=0)
        result = engine.promote(emp, tracker, warmth=0.0)
        assert result.promoted is False
        assert emp.promotion_level == "intern"

    def test_force_promote(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=0)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=0)
        result = engine.promote(emp, tracker, warmth=0.0, force=True)
        assert result.promoted is True
        assert result.reason == "Force-promoted by manager"

    def test_force_promote_at_max(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, level="director")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=0)
        result = engine.promote(emp, tracker, warmth=10.0, force=True)
        assert result.promoted is False

    def test_promote_unlocks_delegation_at_lead(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=20, level="senior")
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=20, ratio=1.0)
        engine.promote(emp, tracker, warmth=3.0)
        assert emp.can_delegate is True
        assert emp.max_subordinates == 3

    def test_renaming_unlocked_flag(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=RENAMING_THRESHOLD)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=5, ratio=1.0)
        result = engine.promote(emp, tracker, warmth=0.5)
        assert result.renaming_unlocked is True

    def test_renaming_not_unlocked(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=3)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=3, ratio=1.0)
        result = engine.promote(emp, tracker, warmth=0.5)
        assert result.renaming_unlocked is False


# ── Renaming Rights ──────────────────────────────────────────────────────────


class TestRenamingRights:
    def test_has_rights(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        has, reason = engine.check_renaming_rights(emp)
        assert has is True
        assert "unlocked" in reason.lower()

    def test_no_rights(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=5,
        )
        has, reason = engine.check_renaming_rights(emp)
        assert has is False
        assert "more tasks" in reason.lower()

    def test_rename_success(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        ok, msg = engine.rename_employee(emp, "Chief Architect")
        assert ok is True
        assert emp.custom_manager_title == "Chief Architect"
        assert "Chief Architect Turing" in msg

    def test_rename_blocked_word(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        ok, msg = engine.rename_employee(emp, "stupid engineer")
        assert ok is False
        assert "blocked" in msg.lower()

    def test_rename_no_rights(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=5,
        )
        ok, msg = engine.rename_employee(emp, "Chief")
        assert ok is False

    def test_rename_duplicate_title(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        ok, msg = engine.rename_employee(emp, "Chief", taken_titles={"Chief"})
        assert ok is False
        assert "already in use" in msg.lower()

    def test_rename_empty_title(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        ok, msg = engine.rename_employee(emp, "   ")
        assert ok is False

    def test_rename_too_long(self, engine):
        emp = Employee(
            id="emp-1234", nickname="Turing", role="engineer",
            hired_by="mgr-boss", tasks_completed_under_manager=12,
        )
        ok, msg = engine.rename_employee(emp, "A" * 50)
        assert ok is False
        assert "exceeds" in msg.lower()


# ── Batch Operations ─────────────────────────────────────────────────────────


class TestBatch:
    def test_batch_evaluate(self, tmp_base, nicknames, engine):
        emp1 = _make_employee(tmp_base, nicknames, tasks_completed=5)
        t1 = _make_tracker(tmp_base, emp1.id, n_tasks=5, ratio=1.0)
        emp2 = _make_employee(tmp_base, nicknames, tasks_completed=0)
        t2 = _make_tracker(tmp_base, emp2.id, n_tasks=0)

        results = engine.batch_evaluate([(emp1, t1, 0.5), (emp2, t2, 0.0)])
        assert len(results) == 2
        assert results[0].eligible is True
        assert results[1].eligible is False

    def test_auto_promote_eligible(self, tmp_base, nicknames, engine):
        emp1 = _make_employee(tmp_base, nicknames, tasks_completed=5)
        t1 = _make_tracker(tmp_base, emp1.id, n_tasks=5, ratio=1.0)
        emp2 = _make_employee(tmp_base, nicknames, tasks_completed=0)
        t2 = _make_tracker(tmp_base, emp2.id, n_tasks=0)

        promoted = engine.auto_promote_eligible([(emp1, t1, 0.5), (emp2, t2, 0.0)])
        assert len(promoted) == 1
        assert promoted[0].employee_id == emp1.id

    def test_custom_thresholds(self, tmp_base, nicknames):
        custom = {"role": {"min_tasks": 1, "max_overrun_rate": 1.0, "min_warmth": 0.0}}
        engine = PromotionEngine(thresholds=custom)
        emp = _make_employee(tmp_base, nicknames, tasks_completed=1)
        t = _make_tracker(tmp_base, emp.id, n_tasks=1, ratio=1.0)
        result = engine.evaluate(emp, t, warmth=0.0)
        assert result.eligible is True


# ── Result Serialization ─────────────────────────────────────────────────────


class TestSerialization:
    def test_result_to_dict(self, tmp_base, nicknames, engine):
        emp = _make_employee(tmp_base, nicknames, tasks_completed=5)
        tracker = _make_tracker(tmp_base, emp.id, n_tasks=5, ratio=1.0)
        result = engine.promote(emp, tracker, warmth=0.5)
        d = result.to_dict()
        assert d["promoted"] is True
        assert d["employee_id"] == emp.id
        assert "next_level" in d
