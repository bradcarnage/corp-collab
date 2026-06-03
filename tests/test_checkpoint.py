"""Tests for corp_collab.checkpoint and corp_collab.im modules."""

from __future__ import annotations

import pytest
from pathlib import Path

from corp_collab.mailbox import Mailbox
from corp_collab.checkpoint import (
    CheckpointConfig,
    CheckpointMonitor,
    CheckpointResult,
    InjectedMessage,
)
from corp_collab import im as im_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mailbox(employee_id: str, base_path: Path) -> Mailbox:
    db = base_path / "employees" / employee_id / "mailbox.db"
    return Mailbox(employee_id, db_path=db)


def _send_im(base_path: Path, from_id: str, to_id: str, body: str) -> int:
    mb = _mailbox(to_id, base_path)
    try:
        return mb.send(
            channel="im", to_id=to_id, to_name=to_id,
            from_id=from_id, from_name=from_id, body=body,
        )
    finally:
        mb.close()


def _send_email(
    base_path: Path, from_id: str, to_id: str, body: str,
    subject: str = "Test", priority: str = "normal",
) -> int:
    mb = _mailbox(to_id, base_path)
    try:
        return mb.send(
            channel="email", to_id=to_id, to_name=to_id,
            from_id=from_id, from_name=from_id, body=body,
            subject=subject, priority=priority,
        )
    finally:
        mb.close()


# ---------------------------------------------------------------------------
# CheckpointMonitor tests
# ---------------------------------------------------------------------------

class TestCheckpointMonitorEmpty:
    def test_check_returns_empty_on_no_messages(self, tmp_path: Path):
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        result = mon.check()
        assert result.tool_call_count == 1
        assert result.messages_injected == []
        assert result.has_messages is False
        assert result.has_steers is False

    def test_tool_call_count_increments(self, tmp_path: Path):
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        mon.check()
        mon.check()
        mon.check()
        assert mon.tool_call_count == 3

    def test_reset_count(self, tmp_path: Path):
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        mon.check()
        mon.check()
        assert mon.tool_call_count == 2
        mon.reset_count()
        assert mon.tool_call_count == 0


class TestCheckpointMonitorIM:
    def test_injects_ims_every_call_default(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "hello")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        r = mon.check()
        assert r.has_messages
        assert len(r.messages_injected) == 1
        assert r.messages_injected[0].channel == "im"
        assert r.messages_injected[0].body == "hello"

    def test_respects_im_check_interval(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "hi")
        cfg = CheckpointConfig(im_check_every=3, urgent_email_always=False)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        # calls 1 and 2 should NOT check IMs
        r1 = mon.check()
        assert not r1.has_messages
        r2 = mon.check()
        assert not r2.has_messages
        # call 3 should
        r3 = mon.check()
        assert r3.has_messages

    def test_respects_max_im_inject(self, tmp_path: Path):
        for i in range(10):
            _send_im(tmp_path, "bob", "alice", f"msg {i}")
        cfg = CheckpointConfig(max_im_inject=3)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        r = mon.check()
        assert len(r.messages_injected) == 3

    def test_marks_messages_as_read(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "read me")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        mon.check()
        # Second check should find nothing
        r2 = mon.check()
        assert not r2.has_messages

    def test_auto_mark_read_disabled(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "still here")
        cfg = CheckpointConfig(auto_mark_read=False)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        mon.check()
        # Message should still be unread
        r2 = mon.check()
        assert r2.has_messages


class TestCheckpointMonitorSteer:
    def test_steer_detection_in_body(self, tmp_path: Path):
        _send_im(tmp_path, "boss", "alice", "please stop what you are doing")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        r = mon.check()
        assert r.has_steers

    def test_steer_callback_fires(self, tmp_path: Path):
        _send_im(tmp_path, "boss", "alice", "abort immediately")
        captured = []
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        mon.on_steer(lambda msg: captured.append(msg))
        mon.check()
        assert len(captured) == 1
        assert captured[0].from_name == "boss"

    def test_no_steer_for_normal_message(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "great work on the report")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        r = mon.check()
        assert not r.has_steers


class TestCheckpointMonitorEmail:
    def test_injects_email_every_10_calls(self, tmp_path: Path):
        _send_email(tmp_path, "hr", "alice", "policy update", subject="Policy")
        cfg = CheckpointConfig(urgent_email_always=False)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        # calls 1-9: no email
        for _ in range(9):
            r = mon.check()
            assert all(m.channel == "im" for m in r.messages_injected)
        # call 10: email appears
        r10 = mon.check()
        emails = [m for m in r10.messages_injected if m.channel == "email"]
        assert len(emails) == 1

    def test_urgent_email_always_injected(self, tmp_path: Path):
        _send_email(tmp_path, "ceo", "alice", "urgent matter", subject="URGENT", priority="urgent")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        r = mon.check()  # call 1, not call 10
        emails = [m for m in r.messages_injected if m.channel == "email"]
        assert len(emails) == 1
        assert emails[0].priority == "urgent"

    def test_non_urgent_email_skipped_outside_interval(self, tmp_path: Path):
        _send_email(tmp_path, "hr", "alice", "fyi", subject="FYI", priority="normal")
        mon = CheckpointMonitor("alice", base_path=tmp_path)
        r = mon.check()  # call 1
        emails = [m for m in r.messages_injected if m.channel == "email"]
        assert len(emails) == 0

    def test_respects_max_email_inject(self, tmp_path: Path):
        for i in range(10):
            _send_email(tmp_path, "hr", "alice", f"email {i}", subject=f"E{i}", priority="urgent")
        cfg = CheckpointConfig(max_email_inject=2)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        r = mon.check()
        emails = [m for m in r.messages_injected if m.channel == "email"]
        assert len(emails) == 2


class TestCheckpointResultFormat:
    def test_format_injection_empty(self):
        r = CheckpointResult(tool_call_count=1)
        assert r.format_injection() == ""

    def test_format_injection_im(self):
        r = CheckpointResult(
            tool_call_count=1,
            messages_injected=[
                InjectedMessage(id=1, channel="im", from_name="Bob", body="hey there", priority="urgent"),
            ],
        )
        text = r.format_injection()
        assert "INCOMING MESSAGES" in text
        assert "Bob" in text
        assert "hey there" in text
        assert "🔴" in text  # urgent prefix

    def test_format_injection_email_with_subject(self):
        r = CheckpointResult(
            tool_call_count=1,
            messages_injected=[
                InjectedMessage(id=2, channel="email", from_name="HR", body="update", subject="Policy", priority="normal"),
            ],
        )
        text = r.format_injection()
        assert "Subject: Policy" in text
        assert "📨" in text

    def test_total_injected_accumulates(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "m1")
        cfg = CheckpointConfig(auto_mark_read=False)
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        mon.check()
        mon.check()
        assert mon.total_injected == 2


class TestCheckpointConfig:
    def test_defaults(self):
        cfg = CheckpointConfig()
        assert cfg.im_check_every == 1
        assert cfg.email_check_every == 10
        assert cfg.urgent_email_always is True
        assert cfg.max_im_inject == 5
        assert cfg.max_email_inject == 3
        assert cfg.auto_mark_read is True

    def test_custom_intervals(self, tmp_path: Path):
        cfg = CheckpointConfig(im_check_every=2, email_check_every=5)
        _send_im(tmp_path, "bob", "alice", "test")
        mon = CheckpointMonitor("alice", config=cfg, base_path=tmp_path)
        r1 = mon.check()  # call 1 — not a multiple of 2
        assert not r1.has_messages
        r2 = mon.check()  # call 2 — check IMs
        assert r2.has_messages


# ---------------------------------------------------------------------------
# im.py module tests
# ---------------------------------------------------------------------------

class TestSendSteer:
    def test_adds_steer_prefix(self, tmp_path: Path):
        result = im_mod.send_steer(
            from_id="boss", from_name="Boss",
            to_id="alice", to_name="Alice",
            instruction="focus on bug #42",
            base_path=tmp_path,
        )
        assert result["type"] == "steer"
        assert result["delivered_to"] == "alice"
        # Verify the actual message in mailbox
        mb = _mailbox("alice", tmp_path)
        try:
            msgs = mb.get_unread(channel="im")
            assert len(msgs) == 1
            assert msgs[0]["body"].startswith("[STEER]")
            assert "focus on bug #42" in msgs[0]["body"]
        finally:
            mb.close()


class TestSendBroadcast:
    def test_sends_to_multiple_recipients(self, tmp_path: Path):
        result = im_mod.send_broadcast(
            from_id="boss", from_name="Boss",
            to_ids=["alice", "bob", "carol"],
            body="team standup in 5 min",
            base_path=tmp_path,
        )
        assert result["broadcast"] is True
        assert result["recipients"] == 3
        assert all(r["status"] == "sent" for r in result["results"])
        # Each recipient should have 1 unread IM
        for eid in ("alice", "bob", "carol"):
            mb = _mailbox(eid, tmp_path)
            try:
                assert mb.count_unread(channel="im") == 1
            finally:
                mb.close()

    def test_broadcast_with_custom_names(self, tmp_path: Path):
        result = im_mod.send_broadcast(
            from_id="boss", from_name="Boss",
            to_ids=["alice", "bob"],
            to_names=["Alice A.", "Bob B."],
            body="hi team",
            base_path=tmp_path,
        )
        assert len(result["results"]) == 2


class TestGetPendingSteers:
    def test_filters_steer_messages(self, tmp_path: Path):
        im_mod.send_steer("boss", "Boss", "alice", "Alice", "stop coding", base_path=tmp_path)
        _send_im(tmp_path, "bob", "alice", "lunch?")
        steers = im_mod.get_pending_steers("alice", base_path=tmp_path)
        assert len(steers) == 1
        assert "[STEER]" in steers[0]["body"]

    def test_empty_when_no_steers(self, tmp_path: Path):
        _send_im(tmp_path, "bob", "alice", "regular message")
        steers = im_mod.get_pending_steers("alice", base_path=tmp_path)
        assert steers == []


class TestCountPending:
    def test_correct_counts(self, tmp_path: Path):
        im_mod.send_steer("boss", "Boss", "alice", "Alice", "redirect now", base_path=tmp_path)
        im_mod.send_steer("cto", "CTO", "alice", "Alice", "pause deploy", base_path=tmp_path)
        _send_im(tmp_path, "bob", "alice", "hey")
        _send_im(tmp_path, "carol", "alice", "hi there")
        counts = im_mod.count_pending("alice", base_path=tmp_path)
        assert counts["total_im"] == 4
        assert counts["steers"] == 2
        assert counts["regular"] == 2

    def test_zero_when_empty(self, tmp_path: Path):
        # Create the mailbox dir so it exists
        (tmp_path / "employees" / "alice").mkdir(parents=True, exist_ok=True)
        counts = im_mod.count_pending("alice", base_path=tmp_path)
        assert counts == {"total_im": 0, "steers": 0, "regular": 0}
