"""Tests for corp_collab.skill_grants — grantable skills system."""

from unittest.mock import MagicMock

import pytest

from corp_collab.skill_grants import (
    DEFAULT_CATALOG,
    LEVEL_ORDER,
    SkillDefinition,
    SkillGrant,
    SkillGrantManager,
)


def _mock_emp(emp_id="emp-001", role="engineer", level="intern"):
    emp = MagicMock()
    emp.id = emp_id
    emp.role = role
    emp.promotion_level = level
    return emp


@pytest.fixture
def mgr():
    return SkillGrantManager()


# ── Catalog ──────────────────────────────────────────────────────────────────


class TestCatalog:
    def test_default_catalog_has_entries(self):
        assert len(DEFAULT_CATALOG) >= 10

    def test_all_skills_have_required_fields(self):
        for name, skill in DEFAULT_CATALOG.items():
            assert skill.name == name
            assert skill.description
            assert skill.min_level in LEVEL_ORDER
            assert len(skill.roles) > 0

    def test_skill_to_dict(self):
        skill = DEFAULT_CATALOG["tdd"]
        d = skill.to_dict()
        assert d["name"] == "tdd"
        assert isinstance(d["roles"], list)

    def test_add_custom_skill(self, mgr):
        custom = SkillDefinition(
            name="custom-tool",
            description="A custom tool",
            min_level="intern",
            roles=("engineer",),
        )
        mgr.add_to_catalog(custom)
        assert "custom-tool" in mgr.catalog

    def test_remove_from_catalog(self, mgr):
        assert mgr.remove_from_catalog("tdd") is True
        assert "tdd" not in mgr.catalog

    def test_remove_nonexistent(self, mgr):
        assert mgr.remove_from_catalog("nonexistent") is False


# ── Eligibility ──────────────────────────────────────────────────────────────


class TestEligibility:
    def test_eligible_basic(self, mgr):
        ok, _ = mgr.check_eligibility("tdd", "engineer", "intern")
        assert ok is True

    def test_wrong_role(self, mgr):
        ok, reason = mgr.check_eligibility("tdd", "reviewer", "intern")
        assert ok is False
        assert "role" in reason.lower()

    def test_level_too_low(self, mgr):
        ok, reason = mgr.check_eligibility("teach", "engineer", "intern")
        assert ok is False
        assert "level" in reason.lower()

    def test_level_sufficient(self, mgr):
        ok, _ = mgr.check_eligibility("teach", "engineer", "senior")
        assert ok is True

    def test_higher_level_ok(self, mgr):
        ok, _ = mgr.check_eligibility("teach", "engineer", "director")
        assert ok is True

    def test_unknown_skill(self, mgr):
        ok, reason = mgr.check_eligibility("nonexistent", "engineer", "intern")
        assert ok is False
        assert "not in catalog" in reason.lower()


# ── Granting ─────────────────────────────────────────────────────────────────


class TestGrant:
    def test_grant_eligible(self, mgr):
        emp = _mock_emp()
        ok, msg = mgr.grant("tdd", emp, "mgr-1")
        assert ok is True
        assert "tdd" in mgr.get_employee_skills(emp.id)

    def test_grant_ineligible_blocked(self, mgr):
        emp = _mock_emp(role="reviewer")
        ok, _ = mgr.grant("tdd", emp, "mgr-1")
        assert ok is False
        assert "tdd" not in mgr.get_employee_skills(emp.id)

    def test_grant_force_bypasses_eligibility(self, mgr):
        emp = _mock_emp(role="reviewer")
        ok, _ = mgr.grant("tdd", emp, "mgr-1", force=True)
        assert ok is True

    def test_duplicate_grant_blocked(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        ok, msg = mgr.grant("tdd", emp, "mgr-1")
        assert ok is False
        assert "already" in msg.lower()

    def test_grant_after_revoke_ok(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        mgr.revoke("tdd", emp.id)
        ok, _ = mgr.grant("tdd", emp, "mgr-1")
        assert ok is True


# ── Revocation ───────────────────────────────────────────────────────────────


class TestRevoke:
    def test_revoke_active(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        ok, _ = mgr.revoke("tdd", emp.id, reason="Misused")
        assert ok is True
        assert "tdd" not in mgr.get_employee_skills(emp.id)

    def test_revoke_nonexistent(self, mgr):
        ok, _ = mgr.revoke("tdd", "emp-999")
        assert ok is False

    def test_revoke_preserves_history(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        mgr.revoke("tdd", emp.id, reason="Test")
        grants = mgr.get_employee_grants(emp.id)
        assert len(grants) == 1
        assert grants[0].revoked is True
        assert grants[0].revoke_reason == "Test"

    def test_grant_record_to_dict(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        grants = mgr.get_employee_grants(emp.id)
        d = grants[0].to_dict()
        assert d["skill_name"] == "tdd"
        assert d["revoked"] is False


# ── Auto-Grant ───────────────────────────────────────────────────────────────


class TestAutoGrant:
    def test_auto_grant_engineer_intern(self, mgr):
        emp = _mock_emp(role="engineer", level="intern")
        granted = mgr.auto_grant_for_role(emp, "mgr-1")
        assert "tdd" in granted
        assert "diagnose" in granted
        assert "handoff" in granted
        # teach requires senior
        assert "teach" not in granted

    def test_auto_grant_engineer_senior(self, mgr):
        emp = _mock_emp(role="engineer", level="senior")
        granted = mgr.auto_grant_for_role(emp, "mgr-1")
        assert "teach" in granted

    def test_auto_grant_reviewer(self, mgr):
        emp = _mock_emp(role="reviewer", level="intern")
        granted = mgr.auto_grant_for_role(emp, "mgr-1")
        assert "grill-me" in granted
        assert "review" in granted
        assert "tdd" not in granted  # engineer only

    def test_auto_grant_no_duplicates(self, mgr):
        emp = _mock_emp()
        mgr.auto_grant_for_role(emp, "mgr-1")
        # Second call should not duplicate
        granted2 = mgr.auto_grant_for_role(emp, "mgr-1")
        assert len(granted2) == 0


# ── Tool Request ─────────────────────────────────────────────────────────────


class TestToolRequest:
    def test_request_eligible(self, mgr):
        emp = _mock_emp()
        ok, _ = mgr.process_tool_request("diagnose", emp)
        assert ok is True

    def test_request_ineligible_no_approval(self, mgr):
        emp = _mock_emp(role="reviewer")
        ok, msg = mgr.process_tool_request("tdd", emp)
        assert ok is False
        assert "manager approval" in msg.lower()

    def test_request_ineligible_with_approval(self, mgr):
        emp = _mock_emp(role="reviewer")
        ok, _ = mgr.process_tool_request("tdd", emp, manager_approved=True)
        assert ok is True


# ── Filtering ────────────────────────────────────────────────────────────────


class TestListAvailable:
    def test_no_filter(self, mgr):
        result = mgr.list_available()
        assert len(result) == len(mgr.catalog)

    def test_filter_by_role(self, mgr):
        result = mgr.list_available(role="reviewer")
        names = {s.name for s in result}
        assert "grill-me" in names
        assert "tdd" not in names

    def test_filter_by_level(self, mgr):
        result = mgr.list_available(level="intern")
        names = {s.name for s in result}
        assert "teach" not in names  # requires senior

    def test_filter_by_category(self, mgr):
        result = mgr.list_available(category="debugging")
        names = {s.name for s in result}
        assert "diagnose" in names
        assert "tdd" not in names

    def test_combined_filter(self, mgr):
        result = mgr.list_available(role="engineer", level="senior", category="mentoring")
        names = {s.name for s in result}
        assert "teach" in names


# ── Context Block ────────────────────────────────────────────────────────────


class TestContextBlock:
    def test_empty_for_no_skills(self, mgr):
        assert mgr.build_context_block("emp-none") == ""

    def test_includes_granted_skills(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        mgr.grant("diagnose", emp, "mgr-1")
        block = mgr.build_context_block(emp.id)
        assert "tdd" in block
        assert "diagnose" in block
        assert "Granted Skills" in block
        assert "skill_view" in block

    def test_excludes_revoked(self, mgr):
        emp = _mock_emp()
        mgr.grant("tdd", emp, "mgr-1")
        mgr.revoke("tdd", emp.id)
        assert mgr.build_context_block(emp.id) == ""
