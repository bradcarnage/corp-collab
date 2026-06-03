"""Corp-Collab: delegation module — formal permission protocol for employees."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Enums ─────────────────────────────────────────────────────────────────────


class RequestType(str, Enum):
    DELEGATE = "delegate"  # hire sub-employees
    TOOL = "tool"  # request additional tool/skill
    RESOURCE = "resource"  # request resource access
    PROMOTION = "promotion"  # request promotion


class ResponseType(str, Enum):
    APPROVED = "approved"
    PARTIAL = "partial"  # partially approved (reduced scope)
    DENIED = "denied"
    REDIRECT = "redirect"  # manager assigns existing employee instead


# ── DelegationRequest ────────────────────────────────────────────────────────


@dataclass
class DelegationRequest:
    """A formal permission request between employee and manager."""

    id: str  # req-{uuid4[:8]}
    request_type: RequestType
    from_id: str  # requesting employee
    from_name: str
    to_id: str  # manager
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    # For delegate requests:
    #   requested_headcount: int, proposed_roles: list[dict], estimated_complexity: str
    # For tool requests:
    #   tools: list[str], justification: str
    created_at: str = field(default_factory=_utcnow_iso)
    status: str = "pending"  # pending | approved | partial | denied | redirect
    response: Optional[dict] = None
    response_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_type": self.request_type.value,
            "from_id": self.from_id,
            "from_name": self.from_name,
            "to_id": self.to_id,
            "reason": self.reason,
            "details": self.details,
            "created_at": self.created_at,
            "status": self.status,
            "response": self.response,
            "response_at": self.response_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DelegationRequest:
        data = dict(data)
        data["request_type"] = RequestType(data["request_type"])
        return cls(**data)


# ── DelegationManager ────────────────────────────────────────────────────────


class DelegationManager:
    """Manages delegation requests between employees and managers."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.home() / ".claude-code" / "collab"
        self._requests_dir = self.base_path / "delegation_requests"
        self._requests_dir.mkdir(parents=True, exist_ok=True)

    def _request_path(self, request_id: str) -> Path:
        return self._requests_dir / f"{request_id}.yaml"

    def create_request(
        self,
        request_type: str | RequestType,
        from_id: str,
        from_name: str,
        to_id: str,
        reason: str,
        details: dict | None = None,
        notify: bool = True,
    ) -> DelegationRequest:
        """Create a delegation request and optionally notify manager via email."""
        req_id = f"req-{uuid.uuid4().hex[:8]}"
        if isinstance(request_type, str):
            request_type = RequestType(request_type)

        req = DelegationRequest(
            id=req_id,
            request_type=request_type,
            from_id=from_id,
            from_name=from_name,
            to_id=to_id,
            reason=reason,
            details=details or {},
        )

        # Save to disk
        with open(self._request_path(req_id), "w") as f:
            yaml.dump(req.to_dict(), f, default_flow_style=False)

        # Notify manager via email
        if notify:
            from corp_collab.mailbox import Mailbox

            db_path = self.base_path / "employees" / to_id / "mailbox.db"
            mailbox = Mailbox(to_id, db_path=db_path)
            try:
                subject = f"Permission Request: {request_type.value} from {from_name}"
                body = self._format_request_email(req)
                mailbox.send(
                    to_id=to_id,
                    to_name=to_id,
                    channel="email",
                    body=body,
                    subject=subject,
                    priority="normal",
                    from_id=from_id,
                    from_name=from_name,
                )
            finally:
                mailbox.close()

        return req

    def respond(
        self,
        request_id: str,
        response_type: str | ResponseType,
        response_details: dict | None = None,
        notify: bool = True,
    ) -> DelegationRequest:
        """Respond to a delegation request."""
        if isinstance(response_type, str):
            response_type = ResponseType(response_type)

        req = self.get_request(request_id)
        if req.status != "pending":
            raise ValueError(f"Request {request_id} already resolved: {req.status}")

        req.status = response_type.value
        req.response = response_details or {}
        req.response_at = _utcnow_iso()

        # Save updated request
        with open(self._request_path(request_id), "w") as f:
            yaml.dump(req.to_dict(), f, default_flow_style=False)

        # Notify requester
        if notify:
            from corp_collab.mailbox import Mailbox

            db_path = self.base_path / "employees" / req.from_id / "mailbox.db"
            mailbox = Mailbox(req.from_id, db_path=db_path)
            try:
                channel = (
                    "im"
                    if response_type
                    in (ResponseType.APPROVED, ResponseType.REDIRECT)
                    else "email"
                )
                body = self._format_response_notification(req)
                subject = f"RE: Permission Request: {req.request_type.value}"
                mailbox.send(
                    to_id=req.from_id,
                    to_name=req.from_name,
                    channel=channel,
                    body=body,
                    subject=subject,
                    from_id=req.to_id,
                    from_name="Manager",
                )
            finally:
                mailbox.close()

        return req

    def get_request(self, request_id: str) -> DelegationRequest:
        """Load a delegation request by ID."""
        path = self._request_path(request_id)
        if not path.exists():
            raise FileNotFoundError(f"Request {request_id} not found")
        with open(path) as f:
            data = yaml.safe_load(f)
        return DelegationRequest.from_dict(data)

    def list_requests(
        self,
        manager_id: str | None = None,
        employee_id: str | None = None,
        status: str | None = None,
    ) -> list[DelegationRequest]:
        """List requests, optionally filtered."""
        results = []
        for path in self._requests_dir.glob("req-*.yaml"):
            with open(path) as f:
                data = yaml.safe_load(f)
            req = DelegationRequest.from_dict(data)
            if manager_id and req.to_id != manager_id:
                continue
            if employee_id and req.from_id != employee_id:
                continue
            if status and req.status != status:
                continue
            results.append(req)
        return sorted(results, key=lambda r: r.created_at, reverse=True)

    def list_pending(self, manager_id: str) -> list[DelegationRequest]:
        """Convenience: pending requests for a manager."""
        return self.list_requests(manager_id=manager_id, status="pending")

    # ── Formatting helpers ────────────────────────────────────────────────

    def _format_request_email(self, req: DelegationRequest) -> str:
        lines = [
            f"Permission Request from {req.from_name}",
            f"Type: {req.request_type.value}",
            f"Reason: {req.reason}",
        ]
        if req.request_type == RequestType.DELEGATE:
            hc = req.details.get("requested_headcount", "?")
            lines.append(f"Requested headcount: {hc}")
            roles = req.details.get("proposed_roles", [])
            for r in roles:
                lines.append(
                    f'  - {r.get("role", "unknown")}: {r.get("tasks", "")}'
                )
        elif req.request_type == RequestType.TOOL:
            tools = req.details.get("tools", [])
            lines.append(f'Tools requested: {", ".join(tools)}')
        lines.append(f"\nRequest ID: {req.id}")
        return "\n".join(lines)

    def _format_response_notification(self, req: DelegationRequest) -> str:
        lines = [f"Your {req.request_type.value} request has been {req.status}."]
        if req.response:
            for k, v in req.response.items():
                lines.append(f"  {k}: {v}")
        if req.status == "redirect":
            redirect_to = req.response.get("redirect_to", "unknown") if req.response else "unknown"
            lines.append(
                f"An existing employee ({redirect_to}) will assist instead."
            )
        return "\n".join(lines)


# ── Hierarchy validation ─────────────────────────────────────────────────────


def validate_hierarchy_depth(
    employee_id: str,
    max_depth: int = 3,
    base_path: Path | None = None,
) -> bool:
    """Check if employee can delegate without exceeding max hierarchy depth.

    Walks up the chain counting levels. Returns True if depth < max_depth.
    """
    bp = base_path or Path.home() / ".claude-code" / "collab"
    employees_path = bp / "employees"
    from corp_collab.employee import Employee

    depth = 0
    current_id = employee_id
    seen: set[str] = set()

    while current_id and current_id not in seen:
        seen.add(current_id)
        try:
            emp = Employee.load(current_id, base_path=employees_path)
        except (FileNotFoundError, Exception):
            break
        depth += 1
        current_id = emp.hired_by

    # depth = number of levels from this employee to root
    # If depth >= max_depth, can't add more levels below
    return depth < max_depth


def can_delegate(
    employee_id: str, base_path: Path | None = None
) -> dict[str, Any]:
    """Check if an employee has delegation permissions and budget."""
    bp = base_path or Path.home() / ".claude-code" / "collab"
    employees_path = bp / "employees"
    from corp_collab.employee import Employee

    try:
        emp = Employee.load(employee_id, base_path=employees_path)
    except FileNotFoundError:
        return {"can_delegate": False, "reason": "employee not found"}

    if not emp.can_delegate:
        return {"can_delegate": False, "reason": "delegation not granted"}

    if not validate_hierarchy_depth(employee_id, base_path=bp):
        return {"can_delegate": False, "reason": "max hierarchy depth reached"}

    # Count current subordinates
    from corp_collab.roster import Roster

    roster = Roster(base_path=bp)
    subs = roster.list_all(manager_id=employee_id)
    active_subs = [s for s in subs if s.status in ("active", "idle")]

    remaining_budget = emp.max_subordinates - len(active_subs)

    return {
        "can_delegate": remaining_budget > 0,
        "remaining_budget": remaining_budget,
        "current_subordinates": len(active_subs),
        "max_subordinates": emp.max_subordinates,
        "reason": None if remaining_budget > 0 else "hiring budget exhausted",
    }
