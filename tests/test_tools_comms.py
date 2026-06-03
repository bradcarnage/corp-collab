"""Tests for tools/im_send.py and tools/email_send.py."""

import tempfile
from pathlib import Path

import pytest

from corp_collab.mailbox import Mailbox
from tools.im_send import im_send
from tools.email_send import email_send


@pytest.fixture
def base(tmp_path):
    """Provide a clean temporary collab base directory."""
    return tmp_path / "collab"


def _ensure_employee_dir(base, employee_id):
    """Ensure the employee directory exists for mailbox creation."""
    emp_dir = base / "employees" / employee_id
    emp_dir.mkdir(parents=True, exist_ok=True)
    return emp_dir


# ── im_send tests ─────────────────────────────────────────────────────────────


class TestImSend:
    def test_im_send_basic(self, base):
        _ensure_employee_dir(base, "emp-0001")
        result = im_send(
            from_id="mgr-001",
            from_name="Manager Chen",
            to_id="emp-0001",
            body="Hello, how's the task going?",
            base_path=base,
        )
        assert "error" not in result
        assert result["channel"] == "im"
        assert result["delivered_to"] == "emp-0001"
        assert isinstance(result["message_id"], int)

    def test_im_send_message_appears_in_mailbox(self, base):
        _ensure_employee_dir(base, "emp-0002")
        im_send(
            from_id="mgr-001",
            from_name="Manager Chen",
            to_id="emp-0002",
            body="Check in please",
            base_path=base,
        )
        db_path = base / "employees" / "emp-0002" / "mailbox.db"
        mbox = Mailbox(employee_id="emp-0002", db_path=db_path)
        unread = mbox.get_unread(channel="im")
        assert len(unread) == 1
        assert unread[0]["body"] == "Check in please"
        assert unread[0]["from_id"] == "mgr-001"
        mbox.close()

    def test_im_send_multiple_messages(self, base):
        _ensure_employee_dir(base, "emp-0003")
        for i in range(3):
            result = im_send(
                from_id="mgr-001",
                from_name="Manager",
                to_id="emp-0003",
                body=f"Message {i}",
                base_path=base,
            )
            assert "error" not in result

        db_path = base / "employees" / "emp-0003" / "mailbox.db"
        mbox = Mailbox(employee_id="emp-0003", db_path=db_path)
        unread = mbox.get_unread(channel="im")
        assert len(unread) == 3
        mbox.close()

    def test_im_send_returns_correct_format(self, base):
        _ensure_employee_dir(base, "emp-0004")
        result = im_send(
            from_id="mgr-001",
            from_name="Boss",
            to_id="emp-0004",
            body="Quick update?",
            base_path=base,
        )
        assert set(result.keys()) == {"message_id", "delivered_to", "channel"}


# ── email_send tests ──────────────────────────────────────────────────────────


class TestEmailSend:
    def test_email_send_basic(self, base):
        _ensure_employee_dir(base, "emp-0010")
        result = email_send(
            from_id="mgr-001",
            from_name="Manager Chen",
            to_id="emp-0010",
            subject="Weekly Review",
            body="Please submit your status report.",
            base_path=base,
        )
        assert "error" not in result
        assert result["channel"] == "email"
        assert result["delivered_to"] == "emp-0010"
        assert result["priority"] == "normal"
        assert isinstance(result["message_id"], int)

    def test_email_send_with_priority(self, base):
        _ensure_employee_dir(base, "emp-0011")
        result = email_send(
            from_id="mgr-001",
            from_name="Manager Chen",
            to_id="emp-0011",
            subject="URGENT: Deadline",
            body="Need this by EOD.",
            priority="urgent",
            base_path=base,
        )
        assert "error" not in result
        assert result["priority"] == "urgent"

    def test_email_send_message_appears_in_mailbox(self, base):
        _ensure_employee_dir(base, "emp-0012")
        email_send(
            from_id="mgr-001",
            from_name="Manager Chen",
            to_id="emp-0012",
            subject="FYI: New Policy",
            body="Please read the attached.",
            priority="fyi",
            base_path=base,
        )
        db_path = base / "employees" / "emp-0012" / "mailbox.db"
        mbox = Mailbox(employee_id="emp-0012", db_path=db_path)
        unread = mbox.get_unread(channel="email")
        assert len(unread) == 1
        assert unread[0]["subject"] == "FYI: New Policy"
        assert unread[0]["priority"] == "fyi"
        mbox.close()

    def test_email_send_returns_correct_format(self, base):
        _ensure_employee_dir(base, "emp-0013")
        result = email_send(
            from_id="mgr-001",
            from_name="Boss",
            to_id="emp-0013",
            subject="Test",
            body="Test body",
            base_path=base,
        )
        assert set(result.keys()) == {"message_id", "delivered_to", "channel", "priority"}

    def test_email_send_invalid_priority(self, base):
        _ensure_employee_dir(base, "emp-0014")
        result = email_send(
            from_id="mgr-001",
            from_name="Boss",
            to_id="emp-0014",
            subject="Test",
            body="Body",
            priority="critical",
            base_path=base,
        )
        assert "error" in result
