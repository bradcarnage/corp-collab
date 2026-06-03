"""Tests for tools/hire.py and tools/fire.py."""

import tempfile
from pathlib import Path

import pytest

from corp_collab.nicknames import NicknameGenerator
from corp_collab.employee import Employee
from corp_collab.roster import Roster
from tools.hire import hire
from tools.fire import fire


@pytest.fixture
def base(tmp_path):
    """Provide a clean temporary collab base directory."""
    return tmp_path / "collab"


# ── hire tests ────────────────────────────────────────────────────────────────


class TestHire:
    def test_hire_creates_employee(self, base):
        result = hire(role="engineer", manager_id="mgr-001", base_path=base)
        assert "error" not in result
        assert result["role"] == "engineer"
        assert result["employee_id"].startswith("emp-")
        assert result["nickname"]
        assert result["full_name"].startswith("Intern ")
        assert "terminal" in result["skills"]

    def test_hire_registers_in_roster(self, base):
        result = hire(role="researcher", manager_id="mgr-001", base_path=base)
        assert "error" not in result
        roster = Roster(base_path=base)
        emp = roster.get(result["employee_id"])
        assert emp.role == "researcher"
        assert emp.hired_by == "mgr-001"

    def test_hire_grants_extra_skills(self, base):
        result = hire(
            role="analyst",
            manager_id="mgr-001",
            skills=["web", "code_exec"],
            base_path=base,
        )
        assert "error" not in result
        assert "web" in result["skills"]
        assert "code_exec" in result["skills"]
        # base analyst skills should also be present
        assert "terminal" in result["skills"]

    def test_hire_sends_welcome_im(self, base):
        from corp_collab.mailbox import Mailbox

        result = hire(role="engineer", manager_id="mgr-001", base_path=base)
        assert "error" not in result
        eid = result["employee_id"]
        db_path = base / "employees" / eid / "mailbox.db"
        mbox = Mailbox(employee_id=eid, db_path=db_path)
        unread = mbox.get_unread(channel="im")
        assert len(unread) >= 1
        assert "Welcome aboard" in unread[0]["body"]
        mbox.close()

    def test_hire_with_project_access(self, base):
        from corp_collab.file_share import FileShare

        fs = FileShare(base_path=base)
        fs.create_project("proj-1", created_by="mgr-001")

        result = hire(
            role="engineer",
            manager_id="mgr-001",
            project_id="proj-1",
            base_path=base,
        )
        assert "error" not in result
        # Employee should now have access
        manifest = fs._load_manifest("proj-1")
        assert result["employee_id"] in manifest["access"]

    def test_hire_invalid_role(self, base):
        result = hire(role="wizard", manager_id="mgr-001", base_path=base)
        assert "error" in result
        assert "Unknown role" in result["error"]


# ── fire tests ────────────────────────────────────────────────────────────────


class TestFire:
    def _hire_employee(self, base, role="engineer"):
        """Helper to hire an employee for fire tests."""
        result = hire(role=role, manager_id="mgr-001", base_path=base)
        assert "error" not in result
        return result

    def test_fire_terminates_employee(self, base):
        hired = self._hire_employee(base)
        result = fire(employee_id=hired["employee_id"], base_path=base)
        assert "error" not in result
        assert result["employee_id"] == hired["employee_id"]
        assert result["nickname"] == hired["nickname"]
        assert result["reason"] == "project_complete"

    def test_fire_unregisters_from_roster(self, base):
        hired = self._hire_employee(base)
        fire(employee_id=hired["employee_id"], base_path=base)
        roster = Roster(base_path=base)
        # Employee should no longer be in registry
        with pytest.raises(KeyError):
            roster.unregister(hired["employee_id"])

    def test_fire_generates_resume(self, base):
        hired = self._hire_employee(base)
        result = fire(
            employee_id=hired["employee_id"],
            reason="downsizing",
            specialties=["API design"],
            strategies=["divide and conquer"],
            base_path=base,
        )
        assert "error" not in result
        resume_path = Path(result["resume_path"])
        assert resume_path.exists()
        assert result["reason"] == "downsizing"

    def test_fire_employee_status_terminated(self, base):
        hired = self._hire_employee(base)
        fire(employee_id=hired["employee_id"], base_path=base)
        # Load directly from disk to verify status
        emp = Employee.load(hired["employee_id"], base / "employees")
        assert emp.status == "terminated"

    def test_fire_nonexistent_employee(self, base):
        # Ensure roster dir exists
        Roster(base_path=base)
        result = fire(employee_id="emp-0000", base_path=base)
        assert "error" in result
