"""Tests for job_title feature and ensure_manager_employee."""

from __future__ import annotations

import pytest
from pathlib import Path

from corp_collab.employee import Employee
from corp_collab.roster import Roster


class TestJobTitle:
    """Employee job_title field."""

    def test_default_none(self, tmp_path):
        emp = Employee(id="e1", nickname="Test", role="engineer", hired_by="mgr")
        assert emp.job_title is None

    def test_set_job_title(self, tmp_path):
        emp = Employee(id="e1", nickname="Test", role="engineer", hired_by="mgr")
        emp.set_job_title("Senior Backend Engineer")
        assert emp.job_title == "Senior Backend Engineer"

    def test_full_name_with_job_title(self):
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr",
                       title="Intern", job_title="API Specialist")
        assert "[API Specialist]" in emp.full_name
        assert "Intern Alice" in emp.full_name

    def test_full_name_without_job_title(self):
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr",
                       title="Intern")
        assert emp.full_name == "Intern Alice"
        assert "[" not in emp.full_name

    def test_clear_job_title(self):
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr",
                       job_title="Old Title")
        emp.set_job_title(None)
        assert emp.job_title is None
        assert "[" not in emp.full_name

    def test_job_title_roundtrip(self, tmp_path):
        """job_title persists through save/load."""
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr",
                       job_title="Lead Researcher")
        emp.save(tmp_path)
        loaded = Employee.load("e1", tmp_path)
        assert loaded.job_title == "Lead Researcher"

    def test_to_dict_includes_job_title(self):
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr",
                       job_title="DevOps Lead")
        d = emp.to_dict()
        assert d["job_title"] == "DevOps Lead"


class TestEnsureManagerEmployee:
    """Roster.ensure_manager_employee auto-registration."""

    def test_creates_manager_employee(self, tmp_path):
        roster = Roster(base_path=tmp_path)
        emp = roster.ensure_manager_employee("flowchat-mgr")
        assert emp.id == "flowchat-mgr"
        assert emp.role == "manager"
        assert emp.can_delegate is True
        assert emp.status == "active"

    def test_idempotent(self, tmp_path):
        roster = Roster(base_path=tmp_path)
        emp1 = roster.ensure_manager_employee("mgr-1")
        emp2 = roster.ensure_manager_employee("mgr-1")
        assert emp1.id == emp2.id

    def test_preserves_existing(self, tmp_path):
        """If manager already registered, returns existing — doesn't overwrite."""
        roster = Roster(base_path=tmp_path)
        # Manually create an engineer with that ID
        eng = Employee(id="special-mgr", nickname="SpecialNick", role="engineer",
                       hired_by="__ceo__", title="Intern")
        roster.register(eng)

        result = roster.ensure_manager_employee("special-mgr")
        assert result.role == "engineer"  # preserved, not overwritten to manager
        assert result.nickname == "SpecialNick"

    def test_hired_by_ceo(self, tmp_path):
        roster = Roster(base_path=tmp_path)
        emp = roster.ensure_manager_employee("top-mgr")
        assert emp.hired_by == "__ceo__"


class TestSetJobTitleDispatch:
    """MCP tool corp_set_job_title via dispatch."""

    def test_set_title(self, tmp_path):
        from corp_collab.mcp_tools import dispatch

        roster = Roster(base_path=tmp_path)
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr-1")
        roster.register(emp)

        result = dispatch("corp_set_job_title", {
            "employee_id": "e1",
            "manager_id": "mgr-1",
            "job_title": "Frontend Lead",
        }, base_path=str(tmp_path))

        assert result["success"] is True
        assert result["job_title"] == "Frontend Lead"
        assert "[Frontend Lead]" in result["full_name"]

    def test_wrong_manager_rejected(self, tmp_path):
        from corp_collab.mcp_tools import dispatch

        roster = Roster(base_path=tmp_path)
        emp = Employee(id="e1", nickname="Alice", role="engineer", hired_by="mgr-1")
        roster.register(emp)

        result = dispatch("corp_set_job_title", {
            "employee_id": "e1",
            "manager_id": "wrong-mgr",
            "job_title": "Hacker",
        }, base_path=str(tmp_path))

        assert "error" in result

    def test_nonexistent_employee(self, tmp_path):
        from corp_collab.mcp_tools import dispatch

        result = dispatch("corp_set_job_title", {
            "employee_id": "nope",
            "manager_id": "mgr",
            "job_title": "Ghost",
        }, base_path=str(tmp_path))

        assert "error" in result
