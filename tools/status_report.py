"""Corp-Collab tool: status_report.

Send a structured status report email to a manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def status_report(
    employee_id: str,
    employee_name: str,
    manager_id: str,
    task_id: str,
    summary: str,
    progress_pct: Optional[float] = None,
    blockers: Optional[str] = None,
    base_path: Optional[str | Path] = None,
) -> dict:
    """Send a structured status report email to the manager's mailbox.

    Returns:
        {sent: True, to: manager_id} or {error: str}.
    """
    try:
        from corp_collab.mailbox import Mailbox

        bp = Path(base_path) if base_path else DEFAULT_BASE

        subject = f"Status: {task_id}"

        # Build formatted body
        lines = [
            f"Status Report — {task_id}",
            f"From: {employee_name} ({employee_id})",
            "",
            f"Summary: {summary}",
        ]
        if progress_pct is not None:
            lines.append(f"Progress: {progress_pct}%")
        if blockers:
            lines.append(f"Blockers: {blockers}")

        body = "\n".join(lines)

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

        return {"sent": True, "to": manager_id}

    except Exception as e:
        return {"error": str(e)}
