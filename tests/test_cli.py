"""Tests for corp_collab.cli — dashboard/monitoring CLI."""

import pytest

from corp_collab.cli import build_parser, main, COMMANDS


# ── Parser ───────────────────────────────────────────────────────────────────


class TestParser:
    def test_build_parser(self):
        parser = build_parser()
        assert parser is not None

    def test_no_command_shows_help(self, capsys):
        ret = main([])
        assert ret == 0

    def test_all_commands_registered(self):
        expected = {"roster", "status", "inbox", "skills", "org", "locks", "stats"}
        assert set(COMMANDS.keys()) == expected


# ── Roster Command ───────────────────────────────────────────────────────────


class TestRosterCmd:
    def test_roster_empty(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "roster"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "No employees" in out

    def test_roster_with_employees(self, tmp_path, capsys):
        # Hire one first
        from tools.hire import hire
        hire(role="engineer", manager_id="mgr", base_path=str(tmp_path))

        ret = main(["--base", str(tmp_path), "roster"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "engineer" in out
        assert "Total:" in out

    def test_roster_idle_filter(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "roster", "--idle"])
        assert ret == 0

    def test_roster_role_filter(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "roster", "--role", "engineer"])
        assert ret == 0


# ── Status Command ───────────────────────────────────────────────────────────


class TestStatusCmd:
    def test_status_not_found(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "status", "emp-nonexistent"])
        assert ret == 1
        assert "not found" in capsys.readouterr().out

    def test_status_found(self, tmp_path, capsys):
        from tools.hire import hire
        result = hire(role="engineer", manager_id="mgr", base_path=str(tmp_path))
        emp_id = result["employee_id"]

        ret = main(["--base", str(tmp_path), "status", emp_id])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Employee:" in out
        assert "Role:" in out


# ── Inbox Command ────────────────────────────────────────────────────────────


class TestInboxCmd:
    def test_inbox_no_mailbox(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "inbox", "emp-nonexistent"])
        assert ret == 1
        assert "No mailbox" in capsys.readouterr().out

    def test_inbox_with_employee(self, tmp_path, capsys):
        from tools.hire import hire
        result = hire(role="engineer", manager_id="mgr", base_path=str(tmp_path))
        emp_id = result["employee_id"]

        ret = main(["--base", str(tmp_path), "inbox", emp_id])
        # Welcome IM should be there
        assert ret == 0


# ── Skills Command ───────────────────────────────────────────────────────────


class TestSkillsCmd:
    def test_skills_not_found(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "skills", "emp-nonexistent"])
        assert ret == 1

    def test_skills_found(self, tmp_path, capsys):
        from tools.hire import hire
        result = hire(role="engineer", manager_id="mgr", base_path=str(tmp_path))
        emp_id = result["employee_id"]

        ret = main(["--base", str(tmp_path), "skills", emp_id])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Skills for" in out


# ── Org Command ──────────────────────────────────────────────────────────────


class TestOrgCmd:
    def test_org_empty(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "org"])
        assert ret == 0
        assert "No employees" in capsys.readouterr().out

    def test_org_with_employees(self, tmp_path, capsys):
        from tools.hire import hire
        hire(role="engineer", manager_id="boss", base_path=str(tmp_path))
        hire(role="reviewer", manager_id="boss", base_path=str(tmp_path))

        ret = main(["--base", str(tmp_path), "org"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "boss" in out
        assert "Organization" in out


# ── Locks Command ────────────────────────────────────────────────────────────


class TestLocksCmd:
    def test_locks_empty(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "locks"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "No active locks" in out


# ── Stats Command ────────────────────────────────────────────────────────────


class TestStatsCmd:
    def test_stats_empty(self, tmp_path, capsys):
        ret = main(["--base", str(tmp_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Total employees: 0" in out

    def test_stats_with_employees(self, tmp_path, capsys):
        from tools.hire import hire
        hire(role="engineer", manager_id="mgr", base_path=str(tmp_path))

        ret = main(["--base", str(tmp_path), "stats"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Total employees: 1" in out
