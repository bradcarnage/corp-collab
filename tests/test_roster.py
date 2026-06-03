"""Tests for corp_collab.roster — registry, warmth, retention, and resume search."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from corp_collab.employee import Employee
from corp_collab.roster import Roster


@pytest.fixture
def tmp_base(tmp_path):
    """Provide a temporary base path for roster tests."""
    return tmp_path / "collab"


@pytest.fixture
def roster(tmp_base):
    return Roster(base_path=tmp_base)


def _make_employee(
    emp_id: str = "emp-0001",
    nickname: str = "TestBot",
    role: str = "engineer",
    hired_by: str = "mgr-0001",
    status: str = "idle",
    tasks: int = 0,
    last_active: str | None = None,
) -> Employee:
    emp = Employee(
        id=emp_id,
        nickname=nickname,
        role=role,
        hired_by=hired_by,
        status=status,
        tasks_completed_under_manager=tasks,
    )
    if last_active:
        emp.last_active = last_active
    return emp


# ── Register / Unregister ────────────────────────────────────────────────────


class TestRegisterUnregister:
    def test_register_adds_to_registry(self, roster):
        emp = _make_employee()
        roster.register(emp)

        registry = roster._load_registry()
        assert "emp-0001" in registry
        assert registry["emp-0001"]["role"] == "engineer"
        assert registry["emp-0001"]["status"] == "idle"
        assert registry["emp-0001"]["manager_id"] == "mgr-0001"

    def test_register_saves_profile(self, roster):
        emp = _make_employee()
        roster.register(emp)

        loaded = roster.get("emp-0001")
        assert loaded.id == "emp-0001"
        assert loaded.nickname == "TestBot"

    def test_unregister_removes_from_registry(self, roster):
        emp = _make_employee()
        roster.register(emp)
        roster.unregister("emp-0001")

        registry = roster._load_registry()
        assert "emp-0001" not in registry

    def test_unregister_missing_raises(self, roster):
        with pytest.raises(KeyError):
            roster.unregister("nonexistent")

    def test_register_multiple(self, roster):
        e1 = _make_employee(emp_id="emp-0001", nickname="Alpha")
        e2 = _make_employee(emp_id="emp-0002", nickname="Beta", role="researcher")
        roster.register(e1)
        roster.register(e2)

        registry = roster._load_registry()
        assert len(registry) == 2


# ── List filtering ───────────────────────────────────────────────────────────


class TestListFiltering:
    def test_list_all_no_filter(self, roster):
        roster.register(_make_employee(emp_id="emp-0001"))
        roster.register(_make_employee(emp_id="emp-0002", role="researcher"))
        assert len(roster.list_all()) == 2

    def test_list_all_filter_by_status(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", status="idle"))
        roster.register(_make_employee(emp_id="emp-0002", status="active"))
        result = roster.list_all(status="idle")
        assert len(result) == 1
        assert result[0].id == "emp-0001"

    def test_list_all_filter_by_role(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", role="engineer"))
        roster.register(_make_employee(emp_id="emp-0002", role="researcher"))
        result = roster.list_all(role="engineer")
        assert len(result) == 1
        assert result[0].role == "engineer"

    def test_list_all_filter_by_manager(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", hired_by="mgr-A"))
        roster.register(_make_employee(emp_id="emp-0002", hired_by="mgr-B"))
        result = roster.list_all(manager_id="mgr-A")
        assert len(result) == 1

    def test_list_idle(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", status="idle"))
        roster.register(_make_employee(emp_id="emp-0002", status="active"))
        idle = roster.list_idle()
        assert len(idle) == 1
        assert idle[0].status == "idle"

    def test_list_idle_with_manager(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", status="idle", hired_by="mgr-A"))
        roster.register(_make_employee(emp_id="emp-0002", status="idle", hired_by="mgr-B"))
        result = roster.list_idle(manager_id="mgr-A")
        assert len(result) == 1


# ── Warmth calculation ───────────────────────────────────────────────────────


class TestWarmth:
    def test_warmth_zero_tasks_recent(self, roster):
        emp = _make_employee(tasks=0)
        emp.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        w = roster.calculate_warmth(emp)
        # 0 * 0.3 + 0 * -0.1 + 0.5 = 0.5
        assert w == pytest.approx(0.5, abs=0.05)

    def test_warmth_with_tasks(self, roster):
        emp = _make_employee(tasks=10)
        emp.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        w = roster.calculate_warmth(emp)
        # 10 * 0.3 + 0 * -0.1 + 0.5 = 3.5
        assert w == pytest.approx(3.5, abs=0.05)

    def test_warmth_decays_with_time(self, roster):
        emp = _make_employee(tasks=5)
        old = datetime.now(timezone.utc) - timedelta(days=10)
        emp.last_active = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        w = roster.calculate_warmth(emp)
        # 5 * 0.3 + 10 * -0.1 + 0.5 = 1.5 - 1.0 + 0.5 = 1.0
        assert w == pytest.approx(1.0, abs=0.05)

    def test_find_by_warmth(self, roster):
        # High warmth employee
        e1 = _make_employee(emp_id="emp-hot", tasks=10)
        e1.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Low warmth employee
        e2 = _make_employee(emp_id="emp-cold", tasks=0)
        old = datetime.now(timezone.utc) - timedelta(days=30)
        e2.last_active = old.strftime("%Y-%m-%dT%H:%M:%SZ")

        roster.register(e1)
        roster.register(e2)

        result = roster.find_by_warmth(min_warmth=1.0)
        assert len(result) == 1
        assert result[0].id == "emp-hot"

    def test_find_by_warmth_sorted_desc(self, roster):
        e1 = _make_employee(emp_id="emp-med", tasks=3)
        e1.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        e2 = _make_employee(emp_id="emp-hot", tasks=10)
        e2.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        roster.register(e1)
        roster.register(e2)

        result = roster.find_by_warmth(min_warmth=0.0)
        assert len(result) == 2
        assert result[0].id == "emp-hot"  # higher warmth first


# ── Retention candidates ─────────────────────────────────────────────────────


class TestRetention:
    def test_no_candidates_under_limit(self, roster):
        roster.register(_make_employee(emp_id="emp-0001", status="idle"))
        roster.register(_make_employee(emp_id="emp-0002", status="idle"))
        assert roster.get_retention_candidates(max_idle=5) == []

    def test_candidates_over_limit(self, roster):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Create 3 idle employees with different warmth
        e1 = _make_employee(emp_id="emp-cold", status="idle", tasks=0)
        old = datetime.now(timezone.utc) - timedelta(days=20)
        e1.last_active = old.strftime("%Y-%m-%dT%H:%M:%SZ")

        e2 = _make_employee(emp_id="emp-warm", status="idle", tasks=5)
        e2.last_active = now

        e3 = _make_employee(emp_id="emp-hot", status="idle", tasks=10)
        e3.last_active = now

        roster.register(e1)
        roster.register(e2)
        roster.register(e3)

        candidates = roster.get_retention_candidates(max_idle=2)
        assert len(candidates) == 1
        assert candidates[0].id == "emp-cold"  # lowest warmth

    def test_candidates_sorted_by_warmth_asc(self, roster):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        e1 = _make_employee(emp_id="emp-a", status="idle", tasks=0)
        e1.last_active = old

        e2 = _make_employee(emp_id="emp-b", status="idle", tasks=1)
        e2.last_active = old

        e3 = _make_employee(emp_id="emp-c", status="idle", tasks=10)
        e3.last_active = now

        roster.register(e1)
        roster.register(e2)
        roster.register(e3)

        candidates = roster.get_retention_candidates(max_idle=1)
        assert len(candidates) == 2
        # Should be sorted ascending by warmth
        w0 = roster.calculate_warmth(candidates[0])
        w1 = roster.calculate_warmth(candidates[1])
        assert w0 <= w1


# ── Resume search ────────────────────────────────────────────────────────────


class TestResumeSearch:
    def test_save_and_search_resume(self, roster):
        emp = _make_employee(emp_id="emp-term", role="engineer", tasks=5)
        roster.save_resume(emp, reason="downsizing", strategies=["code_review"])

        results = roster.search_resumes(role="engineer")
        assert len(results) == 1
        assert results[0]["id"] == "emp-term"
        assert results[0]["reason"] == "downsizing"

    def test_search_by_skills(self, roster):
        emp = _make_employee(emp_id="emp-term", role="engineer")
        roster.save_resume(emp)

        # engineer has ["terminal", "file", "code_exec"] by default
        results = roster.search_resumes(skills=["terminal"])
        assert len(results) == 1

        results = roster.search_resumes(skills=["nonexistent_skill"])
        assert len(results) == 0

    def test_search_by_min_tasks(self, roster):
        emp1 = _make_employee(emp_id="emp-low", tasks=1)
        emp2 = _make_employee(emp_id="emp-high", tasks=10)
        roster.save_resume(emp1)
        roster.save_resume(emp2)

        results = roster.search_resumes(min_tasks=5)
        assert len(results) == 1
        assert results[0]["id"] == "emp-high"

    def test_search_combined_filters(self, roster):
        e1 = _make_employee(emp_id="emp-a", role="engineer", tasks=10)
        e2 = _make_employee(emp_id="emp-b", role="researcher", tasks=10)
        roster.save_resume(e1)
        roster.save_resume(e2)

        results = roster.search_resumes(role="engineer", min_tasks=5)
        assert len(results) == 1
        assert results[0]["role"] == "engineer"

    def test_search_empty_resumes(self, roster):
        results = roster.search_resumes()
        assert results == []
