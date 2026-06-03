"""Tests for corp_collab.delegation — permission protocol with hierarchy validation."""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from corp_collab.delegation import (
    DelegationManager,
    DelegationRequest,
    RequestType,
    ResponseType,
    _utcnow_iso,
    can_delegate,
    validate_hierarchy_depth,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_employee_profile(
    base_path: Path,
    emp_id: str,
    role: str = "engineer",
    hired_by: str = "root",
    can_deleg: bool = False,
    max_subs: int = 0,
    status: str = "active",
) -> Path:
    """Create a minimal employee profile.yaml on disk for testing."""
    emp_dir = base_path / "employees" / emp_id
    emp_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "id": emp_id,
        "nickname": f"Nick-{emp_id}",
        "title": "Engineer",
        "full_name": f"Engineer Nick-{emp_id}",
        "role": role,
        "skills": ["terminal", "file"],
        "granted_skills": [],
        "can_delegate": can_deleg,
        "max_subordinates": max_subs,
        "hired_by": hired_by,
        "hired_at": "2025-01-01T00:00:00Z",
        "last_active": "2025-01-01T00:00:00Z",
        "status": status,
        "current_task": None,
        "custom_manager_title": None,
        "tasks_completed_under_manager": 0,
        "promotion_level": "role",
    }
    profile_path = emp_dir / "profile.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(profile, f, default_flow_style=False)
    return profile_path


def _make_registry(base_path: Path, entries: dict[str, dict]) -> None:
    """Write a registry.yaml for the roster."""
    registry_path = base_path / "registry.yaml"
    with open(registry_path, "w") as f:
        yaml.dump(entries, f, default_flow_style=False)


# ── DelegationRequest tests ─────────────────────────────────────────────────


class TestDelegationRequest:
    def test_create(self):
        req = DelegationRequest(
            id="req-abc12345",
            request_type=RequestType.DELEGATE,
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need help with subtasks",
        )
        assert req.id == "req-abc12345"
        assert req.request_type == RequestType.DELEGATE
        assert req.status == "pending"
        assert req.response is None

    def test_to_dict(self):
        req = DelegationRequest(
            id="req-abc12345",
            request_type=RequestType.TOOL,
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need web access",
            details={"tools": ["web", "browser"]},
            created_at="2025-01-01T00:00:00Z",
        )
        d = req.to_dict()
        assert d["id"] == "req-abc12345"
        assert d["request_type"] == "tool"
        assert d["details"]["tools"] == ["web", "browser"]
        assert d["status"] == "pending"

    def test_from_dict_roundtrip(self):
        req = DelegationRequest(
            id="req-abc12345",
            request_type=RequestType.RESOURCE,
            from_id="emp-002",
            from_name="Bob",
            to_id="mgr-001",
            reason="Need DB access",
            details={"resource": "database"},
            created_at="2025-06-01T12:00:00Z",
        )
        d = req.to_dict()
        restored = DelegationRequest.from_dict(d)
        assert restored.id == req.id
        assert restored.request_type == req.request_type
        assert restored.from_id == req.from_id
        assert restored.details == req.details
        assert restored.status == "pending"

    def test_request_type_enum_values(self):
        assert RequestType.DELEGATE.value == "delegate"
        assert RequestType.TOOL.value == "tool"
        assert RequestType.RESOURCE.value == "resource"
        assert RequestType.PROMOTION.value == "promotion"

    def test_response_type_enum_values(self):
        assert ResponseType.APPROVED.value == "approved"
        assert ResponseType.PARTIAL.value == "partial"
        assert ResponseType.DENIED.value == "denied"
        assert ResponseType.REDIRECT.value == "redirect"


# ── DelegationManager tests ─────────────────────────────────────────────────


class TestDelegationManager:
    def test_create_request_saves_to_disk(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need sub-employees",
            details={"requested_headcount": 2},
            notify=False,
        )
        assert req.id.startswith("req-")
        assert req.request_type == RequestType.DELEGATE
        # Check file exists
        path = tmp_path / "delegation_requests" / f"{req.id}.yaml"
        assert path.exists()
        # Check content
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["from_id"] == "emp-001"
        assert data["status"] == "pending"

    def test_create_request_with_string_type(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="tool",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need web access",
            notify=False,
        )
        assert req.request_type == RequestType.TOOL

    def test_create_request_notifies_manager(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        # Create with notify=True (the default)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need help",
            notify=True,
        )
        # Verify mailbox DB was created for manager
        db_path = tmp_path / "employees" / "mgr-001" / "mailbox.db"
        assert db_path.exists()

    def test_respond_approved(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need help",
            notify=False,
        )
        updated = dm.respond(
            req.id,
            response_type="approved",
            response_details={"approved_headcount": 2},
            notify=False,
        )
        assert updated.status == "approved"
        assert updated.response == {"approved_headcount": 2}
        assert updated.response_at is not None

    def test_respond_denied(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="tool",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need web",
            notify=False,
        )
        updated = dm.respond(
            req.id,
            response_type=ResponseType.DENIED,
            response_details={"reason": "Not authorized"},
            notify=False,
        )
        assert updated.status == "denied"
        # Verify persisted
        reloaded = dm.get_request(req.id)
        assert reloaded.status == "denied"

    def test_respond_partial(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need 5 people",
            details={"requested_headcount": 5},
            notify=False,
        )
        updated = dm.respond(
            req.id,
            response_type="partial",
            response_details={"approved_headcount": 2, "note": "Budget limited"},
            notify=False,
        )
        assert updated.status == "partial"
        assert updated.response["approved_headcount"] == 2

    def test_respond_redirect_includes_redirect_to(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need researcher",
            notify=False,
        )
        updated = dm.respond(
            req.id,
            response_type="redirect",
            response_details={"redirect_to": "emp-099"},
            notify=False,
        )
        assert updated.status == "redirect"
        assert updated.response["redirect_to"] == "emp-099"

    def test_respond_to_resolved_raises_value_error(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="tool",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need tool",
            notify=False,
        )
        dm.respond(req.id, response_type="approved", notify=False)
        with pytest.raises(ValueError, match="already resolved"):
            dm.respond(req.id, response_type="denied", notify=False)

    def test_respond_notifies_requester(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = dm.create_request(
            request_type="delegate",
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need help",
            notify=False,
        )
        dm.respond(
            req.id,
            response_type="denied",
            response_details={"reason": "No budget"},
            notify=True,
        )
        # Requester mailbox should exist
        db_path = tmp_path / "employees" / "emp-001" / "mailbox.db"
        assert db_path.exists()

    def test_list_requests_filters_by_manager_id(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        dm.create_request("delegate", "emp-001", "Alice", "mgr-001", "r1", notify=False)
        dm.create_request("tool", "emp-002", "Bob", "mgr-002", "r2", notify=False)
        dm.create_request("resource", "emp-003", "Carol", "mgr-001", "r3", notify=False)

        results = dm.list_requests(manager_id="mgr-001")
        assert len(results) == 2
        assert all(r.to_id == "mgr-001" for r in results)

    def test_list_requests_filters_by_employee_id(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        dm.create_request("delegate", "emp-001", "Alice", "mgr-001", "r1", notify=False)
        dm.create_request("tool", "emp-001", "Alice", "mgr-002", "r2", notify=False)
        dm.create_request("resource", "emp-002", "Bob", "mgr-001", "r3", notify=False)

        results = dm.list_requests(employee_id="emp-001")
        assert len(results) == 2
        assert all(r.from_id == "emp-001" for r in results)

    def test_list_requests_filters_by_status(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req1 = dm.create_request("delegate", "emp-001", "Alice", "mgr-001", "r1", notify=False)
        dm.create_request("tool", "emp-002", "Bob", "mgr-001", "r2", notify=False)

        dm.respond(req1.id, "approved", notify=False)

        pending = dm.list_requests(status="pending")
        assert len(pending) == 1
        approved = dm.list_requests(status="approved")
        assert len(approved) == 1

    def test_list_pending_convenience(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        dm.create_request("delegate", "emp-001", "Alice", "mgr-001", "r1", notify=False)
        req2 = dm.create_request("tool", "emp-002", "Bob", "mgr-001", "r2", notify=False)
        dm.create_request("resource", "emp-003", "Carol", "mgr-002", "r3", notify=False)

        dm.respond(req2.id, "denied", notify=False)

        pending = dm.list_pending("mgr-001")
        assert len(pending) == 1
        assert pending[0].from_id == "emp-001"

    def test_get_request_not_found_raises(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        with pytest.raises(FileNotFoundError, match="not found"):
            dm.get_request("req-nonexistent")

    def test_format_request_email_delegate(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = DelegationRequest(
            id="req-test",
            request_type=RequestType.DELEGATE,
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need workers",
            details={
                "requested_headcount": 3,
                "proposed_roles": [{"role": "researcher", "tasks": "web search"}],
            },
        )
        body = dm._format_request_email(req)
        assert "Alice" in body
        assert "delegate" in body
        assert "Requested headcount: 3" in body
        assert "researcher" in body

    def test_format_request_email_tool(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = DelegationRequest(
            id="req-test",
            request_type=RequestType.TOOL,
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need tools",
            details={"tools": ["web", "browser"]},
        )
        body = dm._format_request_email(req)
        assert "web, browser" in body

    def test_format_response_notification_redirect(self, tmp_path: Path):
        dm = DelegationManager(base_path=tmp_path)
        req = DelegationRequest(
            id="req-test",
            request_type=RequestType.DELEGATE,
            from_id="emp-001",
            from_name="Alice",
            to_id="mgr-001",
            reason="Need help",
            status="redirect",
            response={"redirect_to": "emp-099"},
        )
        body = dm._format_response_notification(req)
        assert "redirect" in body
        assert "emp-099" in body


# ── Hierarchy validation tests ───────────────────────────────────────────────


class TestHierarchyValidation:
    def test_under_limit_returns_true(self, tmp_path: Path):
        # Create a 2-level chain: root -> emp-001
        _make_employee_profile(tmp_path, "root", hired_by="", can_deleg=True)
        _make_employee_profile(tmp_path, "emp-001", hired_by="root", can_deleg=True)

        assert validate_hierarchy_depth("emp-001", max_depth=3, base_path=tmp_path) is True

    def test_at_limit_returns_false(self, tmp_path: Path):
        # Create a 3-level chain: root -> mgr-001 -> emp-001
        _make_employee_profile(tmp_path, "root", hired_by="")
        _make_employee_profile(tmp_path, "mgr-001", hired_by="root")
        _make_employee_profile(tmp_path, "emp-001", hired_by="mgr-001")

        assert validate_hierarchy_depth("emp-001", max_depth=3, base_path=tmp_path) is False

    def test_single_employee_under_limit(self, tmp_path: Path):
        # Just one employee with no manager found
        _make_employee_profile(tmp_path, "emp-solo", hired_by="nonexistent")

        assert validate_hierarchy_depth("emp-solo", max_depth=3, base_path=tmp_path) is True

    def test_nonexistent_employee(self, tmp_path: Path):
        # Employee doesn't exist — depth is 0, always under limit
        assert validate_hierarchy_depth("emp-ghost", max_depth=3, base_path=tmp_path) is True

    def test_cycle_detection(self, tmp_path: Path):
        # Create a cycle: a -> b -> a
        _make_employee_profile(tmp_path, "emp-a", hired_by="emp-b")
        _make_employee_profile(tmp_path, "emp-b", hired_by="emp-a")

        # Should terminate without infinite loop
        result = validate_hierarchy_depth("emp-a", max_depth=10, base_path=tmp_path)
        assert isinstance(result, bool)


# ── can_delegate tests ───────────────────────────────────────────────────────


class TestCanDelegate:
    def test_employee_not_found(self, tmp_path: Path):
        result = can_delegate("emp-ghost", base_path=tmp_path)
        assert result["can_delegate"] is False
        assert result["reason"] == "employee not found"

    def test_employee_without_permission(self, tmp_path: Path):
        _make_employee_profile(
            tmp_path, "emp-001", can_deleg=False, max_subs=0
        )
        result = can_delegate("emp-001", base_path=tmp_path)
        assert result["can_delegate"] is False
        assert result["reason"] == "delegation not granted"

    def test_employee_with_budget_exhausted(self, tmp_path: Path):
        _make_employee_profile(
            tmp_path, "mgr-001", hired_by="", can_deleg=True, max_subs=1
        )
        # Create one active subordinate
        _make_employee_profile(
            tmp_path, "emp-sub1", hired_by="mgr-001", status="active"
        )
        # Set up registry so roster can find sub
        _make_registry(
            tmp_path,
            {
                "mgr-001": {
                    "role": "engineer",
                    "status": "active",
                    "manager_id": "",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
                "emp-sub1": {
                    "role": "engineer",
                    "status": "active",
                    "manager_id": "mgr-001",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
            },
        )
        # Also create resumes dir (roster expects it)
        (tmp_path / "resumes").mkdir(exist_ok=True)

        result = can_delegate("mgr-001", base_path=tmp_path)
        assert result["can_delegate"] is False
        assert result["reason"] == "hiring budget exhausted"
        assert result["remaining_budget"] == 0

    def test_employee_with_remaining_budget(self, tmp_path: Path):
        _make_employee_profile(
            tmp_path, "mgr-002", hired_by="", can_deleg=True, max_subs=3
        )
        # Create one active subordinate
        _make_employee_profile(
            tmp_path, "emp-sub2", hired_by="mgr-002", status="idle"
        )
        _make_registry(
            tmp_path,
            {
                "mgr-002": {
                    "role": "engineer",
                    "status": "active",
                    "manager_id": "",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
                "emp-sub2": {
                    "role": "engineer",
                    "status": "idle",
                    "manager_id": "mgr-002",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
            },
        )
        (tmp_path / "resumes").mkdir(exist_ok=True)

        result = can_delegate("mgr-002", base_path=tmp_path)
        assert result["can_delegate"] is True
        assert result["remaining_budget"] == 2
        assert result["current_subordinates"] == 1
        assert result["max_subordinates"] == 3
        assert result["reason"] is None

    def test_terminated_subs_not_counted(self, tmp_path: Path):
        _make_employee_profile(
            tmp_path, "mgr-003", hired_by="", can_deleg=True, max_subs=1
        )
        _make_employee_profile(
            tmp_path, "emp-term", hired_by="mgr-003", status="terminated"
        )
        _make_registry(
            tmp_path,
            {
                "mgr-003": {
                    "role": "engineer",
                    "status": "active",
                    "manager_id": "",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
                "emp-term": {
                    "role": "engineer",
                    "status": "terminated",
                    "manager_id": "mgr-003",
                    "hired_at": "2025-01-01T00:00:00Z",
                },
            },
        )
        (tmp_path / "resumes").mkdir(exist_ok=True)

        result = can_delegate("mgr-003", base_path=tmp_path)
        # Terminated employees should not count against budget
        assert result["can_delegate"] is True
        assert result["remaining_budget"] == 1
