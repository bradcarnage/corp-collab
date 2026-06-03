"""Corp-Collab tool: request_permission.

Send a formal permission request email to a manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"

VALID_REQUEST_TYPES = {"delegate", "resource", "tool", "other"}


def request_permission(
    employee_id: str,
    employee_name: str,
    manager_id: str,
    request_type: str,
    details: str,
    base_path: Optional[str | Path] = None,
) -> dict:
    """Send a formal permission request email to the manager.

    Args:
        employee_id: Requesting employee's ID.
        employee_name: Requesting employee's display name.
        manager_id: Manager's employee ID.
        request_type: One of 'delegate', 'resource', 'tool', 'other'.
        details: Description of what is being requested and why.
        base_path: Base path for mailbox storage.

    Returns:
        {sent: True, request_type: str, to: manager_id} or {error: str}.
    """
    try:
        from corp_collab.mailbox import Mailbox

        if request_type not in VALID_REQUEST_TYPES:
            return {
                "error": f"Invalid request_type '{request_type}'. "
                         f"Must be one of: {sorted(VALID_REQUEST_TYPES)}"
            }

        bp = Path(base_path) if base_path else DEFAULT_BASE

        subject = f"Permission Request: {request_type}"

        body = "\n".join([
            f"Permission Request — {request_type.upper()}",
            f"From: {employee_name} ({employee_id})",
            "",
            f"Type: {request_type}",
            f"Details: {details}",
            "",
            "Awaiting approval.",
        ])

        # Send to manager's mailbox
        db_path = bp / "employees" / manager_id / "mailbox.db"
        mbox = Mailbox(manager_id, db_path=db_path)
        try:
            mbox.send(
                channel="email",
                to_id=manager_id,
                to_name=manager_id,
                from_id=employee_id,
                from_name=employee_name,
                subject=subject,
                body=body,
            )
        finally:
            mbox.close()

        return {"sent": True, "request_type": request_type, "to": manager_id}

    except Exception as e:
        return {"error": str(e)}
