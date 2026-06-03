"""Tests for tools/ management wrappers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_base(tmp_path: Path) -> Path:
    """Create a collab base directory structure."""
    bp = tmp_path / "collab"
    (bp / "employees").mkdir(parents=True)
    (bp / "resumes").mkdir(parents=True)
    return bp


def _register_employee(bp: Path, emp_id: str, nickname: str, role: str, manager_id: str, status: str = "active"):
    """Write minimal employee profile + registry entry."""
    emp_dir = bp / "employees" / emp_id
    emp_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "id": emp_id,
        "nickname": nickname,
        "title": "Intern",
        "full_name": f"Intern {nickname}",
        "role": role,
        "skills": ["terminal"],
        "granted_skills": [],
        "can_delegate": False,
        "max_subordinates": 0,
        "hired_by": manager_id,
        "hired_at": "2025-01-01T00:00:00Z",
        "last_active": "2025-01-01T00:00:00Z",
        "status": status,
        "current_task": None,
        "custom_manager_title": None,
        "tasks_completed_under_manager": 0,
        "promotion_level": "intern",
    }
    with open(emp_dir / "profile.yaml", "w") as f:
        yaml.dump(profile, f)

    # Update registry
    reg_path = bp / "registry.yaml"
    if reg_path.exists():
        with open(reg_path) as f:
            registry = yaml.safe_load(f) or {}
    else:
        registry = {}
    registry[emp_id] = {
        "role": role,
        "status": status,
        "manager_id": manager_id,
        "hired_at": "2025-01-01T00:00:00Z",
    }
    with open(reg_path, "w") as f:
        yaml.dump(registry, f)


# ══════════════════════════════════════════════════════════════════════════════
# check_reports
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckReports:
    def test_no_employees(self, tmp_path):
        """Manager with no reports returns empty list."""
        from tools.check_reports import check_reports

        bp = _make_base(tmp_path)
        # Create registry file (empty)
        (bp / "registry.yaml").write_text("{}")
        # Ensure manager mailbox dir exists
        (bp / "employees" / "mgr-001").mkdir(parents=True)

        result = check_reports("mgr-001", base_path=bp)
        assert "reports" in result
        assert result["reports"] == []

    def test_with_unread_messages(self, tmp_path):
        """Messages from employee show up in unread counts."""
        from tools.check_reports import check_reports
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        _register_employee(bp, "emp-001", "Alice", "engineer", "mgr-001")

        # Send messages to manager's mailbox
        mgr_db = bp / "employees" / "mgr-001" / "mailbox.db"
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)
        mbox = Mailbox("mgr-001", db_path=mgr_db)
        mbox.send("im", to_id="mgr-001", to_name="Manager", from_id="emp-001", from_name="Alice", body="hi")
        mbox.send("email", to_id="mgr-001", to_name="Manager", from_id="emp-001", from_name="Alice", body="report", subject="test")
        mbox.send("email", to_id="mgr-001", to_name="Manager", from_id="emp-001", from_name="Alice", body="report2", subject="test2")
        mbox.close()

        result = check_reports("mgr-001", base_path=bp)
        assert len(result["reports"]) == 1
        r = result["reports"][0]
        assert r["employee_id"] == "emp-001"
        assert r["nickname"] == "Alice"
        assert r["unread_im"] == 1
        assert r["unread_email"] == 2

    def test_specific_employee(self, tmp_path):
        """Filtering by employee_id returns only that employee."""
        from tools.check_reports import check_reports
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        _register_employee(bp, "emp-001", "Alice", "engineer", "mgr-001")
        _register_employee(bp, "emp-002", "Bob", "engineer", "mgr-001")

        mgr_db = bp / "employees" / "mgr-001" / "mailbox.db"
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)
        mbox = Mailbox("mgr-001", db_path=mgr_db)
        mbox.send("im", to_id="mgr-001", to_name="Mgr", from_id="emp-001", from_name="Alice", body="hi")
        mbox.send("im", to_id="mgr-001", to_name="Mgr", from_id="emp-002", from_name="Bob", body="hey")
        mbox.close()

        result = check_reports("mgr-001", employee_id="emp-001", base_path=bp)
        assert len(result["reports"]) == 1
        assert result["reports"][0]["employee_id"] == "emp-001"
        assert result["reports"][0]["unread_im"] == 1

    def test_error_handling(self, tmp_path):
        """Non-existent employee_id returns error."""
        from tools.check_reports import check_reports

        bp = _make_base(tmp_path)
        (bp / "registry.yaml").write_text("{}")

        result = check_reports("mgr-001", employee_id="emp-nonexistent", base_path=bp)
        assert "error" in result


# ══════════════════════════════════════════════════════════════════════════════
# share_file
# ══════════════════════════════════════════════════════════════════════════════


class TestShareFile:
    def test_publish_file(self, tmp_path):
        """Publishing a file returns notification dict."""
        from tools.share_file import share_file
        from corp_collab.file_share import FileShare

        bp = _make_base(tmp_path)
        fs = FileShare(base_path=bp)
        fs.create_project("proj-1", created_by="emp-001")

        result = share_file(
            project_id="proj-1",
            file_name="readme.md",
            content="# Hello",
            author_id="emp-001",
            author_name="Alice",
            message="initial commit",
            base_path=bp,
        )

        assert result["type"] == "file_published"
        assert result["file_name"] == "readme.md"
        assert result["author_id"] == "emp-001"
        assert result["message"] == "initial commit"

    def test_publish_to_nonexistent_project(self, tmp_path):
        """Publishing to a missing project returns error."""
        from tools.share_file import share_file

        bp = _make_base(tmp_path)
        result = share_file(
            project_id="no-such-project",
            file_name="test.txt",
            content="hello",
            author_id="emp-001",
            author_name="Alice",
            base_path=bp,
        )
        assert "error" in result

    def test_file_content_written(self, tmp_path):
        """File content is actually written to disk."""
        from tools.share_file import share_file
        from corp_collab.file_share import FileShare

        bp = _make_base(tmp_path)
        fs = FileShare(base_path=bp)
        fs.create_project("proj-2", created_by="emp-001")

        share_file(
            project_id="proj-2",
            file_name="data.txt",
            content="hello world",
            author_id="emp-001",
            author_name="Alice",
            base_path=bp,
        )

        content = fs.read("proj-2", "data.txt", "emp-001")
        assert content == "hello world"


# ══════════════════════════════════════════════════════════════════════════════
# status_report
# ══════════════════════════════════════════════════════════════════════════════


class TestStatusReport:
    def test_send_basic_report(self, tmp_path):
        """Sending a status report returns sent=True."""
        from tools.status_report import status_report

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        result = status_report(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            task_id="task-42",
            summary="50% done, working on tests",
            base_path=bp,
        )
        assert result["sent"] is True
        assert result["to"] == "mgr-001"

    def test_report_with_progress_and_blockers(self, tmp_path):
        """Report with progress and blockers is stored in mailbox."""
        from tools.status_report import status_report
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        status_report(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            task_id="task-42",
            summary="Making progress",
            progress_pct=75.0,
            blockers="Waiting on API access",
            base_path=bp,
        )

        mbox = Mailbox("mgr-001", db_path=bp / "employees" / "mgr-001" / "mailbox.db")
        msgs = mbox.get_unread("email")
        mbox.close()

        assert len(msgs) == 1
        msg = msgs[0]
        assert msg["subject"] == "Status: task-42"
        assert "Progress: 75.0%" in msg["body"]
        assert "Blockers: Waiting on API access" in msg["body"]

    def test_report_body_format(self, tmp_path):
        """Report body contains summary line."""
        from tools.status_report import status_report
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        status_report(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            task_id="task-99",
            summary="All done",
            base_path=bp,
        )

        mbox = Mailbox("mgr-001", db_path=bp / "employees" / "mgr-001" / "mailbox.db")
        msgs = mbox.get_unread("email")
        mbox.close()

        assert "Summary: All done" in msgs[0]["body"]


# ══════════════════════════════════════════════════════════════════════════════
# escalate
# ══════════════════════════════════════════════════════════════════════════════


class TestEscalate:
    def test_no_action_needed(self, tmp_path):
        """When not overdue, no action is taken."""
        from tools.escalate import escalate

        bp = _make_base(tmp_path)
        (bp / "employees" / "emp-001").mkdir(parents=True, exist_ok=True)

        result = escalate(
            manager_id="mgr-001",
            employee_id="emp-001",
            task_id="task-1",
            estimate_dict={"manager_estimate": 60, "complexity": "C2", "multiplier": 1.4},
            elapsed_minutes=5,
            last_status_ago=5,
            base_path=bp,
        )

        assert result["action_taken"] is False
        assert result["level"] == 0
        assert "tracker" in result

    def test_action_when_overdue(self, tmp_path):
        """When significantly overdue with no status, action is taken."""
        from tools.escalate import escalate

        bp = _make_base(tmp_path)
        (bp / "employees" / "emp-001").mkdir(parents=True, exist_ok=True)

        result = escalate(
            manager_id="mgr-001",
            employee_id="emp-001",
            task_id="task-1",
            estimate_dict={"manager_estimate": 10, "complexity": "C1", "multiplier": 1.4},
            elapsed_minutes=60,
            last_status_ago=60,
            base_path=bp,
        )

        assert result["action_taken"] is True
        assert result["level"] >= 1
        assert result["action"] is not None
        assert "tracker" in result

    def test_tracker_persistence(self, tmp_path):
        """Tracker dict can be passed back for continued escalation."""
        from tools.escalate import escalate

        bp = _make_base(tmp_path)
        (bp / "employees" / "emp-001").mkdir(parents=True, exist_ok=True)

        # First call
        r1 = escalate(
            manager_id="mgr-001",
            employee_id="emp-001",
            task_id="task-1",
            estimate_dict={"manager_estimate": 10, "complexity": "C1", "multiplier": 1.4},
            elapsed_minutes=60,
            last_status_ago=60,
            base_path=bp,
        )

        # Second call with tracker from first
        r2 = escalate(
            manager_id="mgr-001",
            employee_id="emp-001",
            task_id="task-1",
            estimate_dict={"manager_estimate": 10, "complexity": "C1", "multiplier": 1.4},
            elapsed_minutes=120,
            last_status_ago=120,
            tracker_dict=r1["tracker"],
            base_path=bp,
        )

        assert r2["action_taken"] is True
        # Level should have increased
        assert r2["level"] >= r1["level"]

    def test_escalate_sends_message(self, tmp_path):
        """Escalation sends a message to the employee's mailbox."""
        from tools.escalate import escalate
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        (bp / "employees" / "emp-001").mkdir(parents=True, exist_ok=True)

        escalate(
            manager_id="mgr-001",
            employee_id="emp-001",
            task_id="task-1",
            estimate_dict={"manager_estimate": 10, "complexity": "C1", "multiplier": 1.4},
            elapsed_minutes=60,
            last_status_ago=60,
            base_path=bp,
        )

        mbox = Mailbox("emp-001", db_path=bp / "employees" / "emp-001" / "mailbox.db")
        msgs = mbox.get_unread()
        mbox.close()

        assert len(msgs) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# request_permission
# ══════════════════════════════════════════════════════════════════════════════


class TestRequestPermission:
    def test_delegate_request(self, tmp_path):
        """Delegate permission request sends email and returns correctly."""
        from tools.request_permission import request_permission

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        result = request_permission(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            request_type="delegate",
            details="Need to hire sub-employee for research subtask",
            base_path=bp,
        )

        assert result["sent"] is True
        assert result["request_type"] == "delegate"
        assert result["to"] == "mgr-001"

    def test_invalid_request_type(self, tmp_path):
        """Invalid request_type returns error."""
        from tools.request_permission import request_permission

        bp = _make_base(tmp_path)
        result = request_permission(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            request_type="invalid_type",
            details="something",
            base_path=bp,
        )
        assert "error" in result

    def test_email_stored_in_mailbox(self, tmp_path):
        """Permission request email is stored in manager's mailbox."""
        from tools.request_permission import request_permission
        from corp_collab.mailbox import Mailbox

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        request_permission(
            employee_id="emp-001",
            employee_name="Alice",
            manager_id="mgr-001",
            request_type="resource",
            details="Need access to GPU cluster",
            base_path=bp,
        )

        mbox = Mailbox("mgr-001", db_path=bp / "employees" / "mgr-001" / "mailbox.db")
        msgs = mbox.get_unread("email")
        mbox.close()

        assert len(msgs) == 1
        assert msgs[0]["subject"] == "Permission Request: resource"
        assert "GPU cluster" in msgs[0]["body"]

    def test_all_valid_types(self, tmp_path):
        """All valid request types are accepted."""
        from tools.request_permission import request_permission

        bp = _make_base(tmp_path)
        (bp / "employees" / "mgr-001").mkdir(parents=True, exist_ok=True)

        for rtype in ("delegate", "resource", "tool", "other"):
            result = request_permission(
                employee_id="emp-001",
                employee_name="Alice",
                manager_id="mgr-001",
                request_type=rtype,
                details=f"Testing {rtype}",
                base_path=bp,
            )
            assert result["sent"] is True, f"Failed for request_type={rtype}"
