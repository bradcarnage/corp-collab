"""Tests for corp_collab.checkin — escalation ladder and check-in policy."""

import pytest

from corp_collab.checkin import (
    CheckInPolicy,
    EscalationTracker,
    ESCALATION_LEVELS,
    MAX_LEVEL,
)


# ── CheckInPolicy ───────────────────────────────────────────────────────────


class TestCheckInPolicy:
    def test_defaults(self):
        p = CheckInPolicy()
        assert p.im_wait == 120
        assert p.email_wait == 300
        assert p.escalation_multiplier == 1.4

    def test_should_check_in_early(self):
        p = CheckInPolicy()
        # Early in task, recent report → no check-in
        assert p.should_check_in(estimate=60, elapsed=10, last_report_ago=5) is False

    def test_should_check_in_half_estimate(self):
        p = CheckInPolicy()
        # Past half estimate, no recent report
        assert p.should_check_in(estimate=60, elapsed=35, last_report_ago=35) is True

    def test_should_check_in_overdue(self):
        p = CheckInPolicy()
        # Overdue and no recent report
        assert p.should_check_in(estimate=30, elapsed=35, last_report_ago=5) is True

    def test_escalation_level_from_attempts(self):
        p = CheckInPolicy()
        assert p.get_escalation_level(0) == 1
        assert p.get_escalation_level(1) == 1
        assert p.get_escalation_level(2) == 2
        assert p.get_escalation_level(3) == 3
        assert p.get_escalation_level(4) == 4
        assert p.get_escalation_level(5) == 5
        assert p.get_escalation_level(99) == 5

    def test_generate_message_l1(self):
        p = CheckInPolicy()
        msg = p.generate_check_in_message(1, "Sparky", "fix the bug")
        assert "Sparky" in msg
        assert "fix the bug" in msg
        assert "check-in" in msg.lower()

    def test_generate_message_l2(self):
        p = CheckInPolicy()
        msg = p.generate_check_in_message(2, "Sparky", "fix the bug")
        assert "URGENT" in msg

    def test_generate_message_l3(self):
        p = CheckInPolicy()
        msg = p.generate_check_in_message(3, "Sparky", "fix the bug")
        assert "INVESTIGATING" in msg

    def test_generate_message_l4(self):
        p = CheckInPolicy()
        msg = p.generate_check_in_message(4, "Sparky", "fix the bug")
        assert "INTERVENTION" in msg

    def test_generate_message_l5(self):
        p = CheckInPolicy()
        msg = p.generate_check_in_message(5, "Sparky", "fix the bug")
        assert "TERMINATION" in msg

    def test_roundtrip_dict(self):
        p = CheckInPolicy(im_wait=60, email_wait=180, escalation_multiplier=2.0)
        d = p.to_dict()
        p2 = CheckInPolicy.from_dict(d)
        assert p2.im_wait == 60
        assert p2.email_wait == 180
        assert p2.escalation_multiplier == 2.0


# ── EscalationTracker ────────────────────────────────────────────────────────


class TestEscalationTracker:
    def make_tracker(self) -> EscalationTracker:
        return EscalationTracker(
            task_id="task-001",
            employee_id="emp-abc1",
            employee_name="Sparky",
        )

    def test_initial_level_zero(self):
        t = self.make_tracker()
        assert t.current_level() == 0

    def test_record_check_in_increments_level(self):
        t = self.make_tracker()
        t.record_check_in(1)
        assert t.current_level() == 1
        t.record_check_in(2)
        assert t.current_level() == 2

    def test_response_resets_level(self):
        t = self.make_tracker()
        t.record_check_in(1)
        t.record_check_in(2)
        assert t.current_level() == 2
        t.record_response()
        assert t.current_level() == 0

    def test_level_caps_at_max(self):
        t = self.make_tracker()
        for i in range(10):
            t.record_check_in(i + 1)
        assert t.current_level() == MAX_LEVEL

    def test_next_action_wait_when_fine(self):
        t = self.make_tracker()
        action = t.next_action(elapsed=5, estimate=60, last_status_ago=5)
        assert action["should_act"] is False
        assert action["action"] == "wait"

    def test_next_action_escalates(self):
        t = self.make_tracker()
        # Overdue and no recent report
        action = t.next_action(elapsed=65, estimate=60, last_status_ago=10)
        assert action["should_act"] is True
        assert action["level"] == 1

    def test_next_action_after_check_ins(self):
        t = self.make_tracker()
        t.record_check_in(1)
        t.record_check_in(2)
        action = t.next_action(elapsed=65, estimate=60, last_status_ago=10)
        assert action["level"] == 3  # 2 unanswered → next is 3

    def test_history_ordered(self):
        t = self.make_tracker()
        t.record_check_in(1)
        t.record_response()
        t.record_check_in(2)
        history = t.history()
        assert len(history) == 3
        assert history[0]["type"] == "check_in"
        assert history[1]["type"] == "response"
        assert history[2]["type"] == "check_in"

    def test_roundtrip_dict(self):
        t = self.make_tracker()
        t.record_check_in(1)
        t.record_response()
        d = t.to_dict()
        t2 = EscalationTracker.from_dict(d)
        assert t2.task_id == "task-001"
        assert t2.employee_id == "emp-abc1"
        assert t2.current_level() == 0
        assert len(t2.history()) == 2
