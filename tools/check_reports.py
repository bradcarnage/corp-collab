"""Corp-Collab tool: check_reports.

Check unread messages from direct reports to a manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def check_reports(
    manager_id: str,
    employee_id: Optional[str] = None,
    base_path: Optional[str | Path] = None,
) -> dict:
    """Check unread messages from managed employees.

    If employee_id is given, returns unread counts for that employee only.
    Otherwise, iterates all employees under this manager.

    Returns:
        {reports: [{employee_id, nickname, unread_im, unread_email}]}
    """
    try:
        from corp_collab.roster import Roster
        from corp_collab.mailbox import Mailbox

        bp = Path(base_path) if base_path else DEFAULT_BASE

        roster = Roster(base_path=bp)

        if employee_id:
            # Single employee
            try:
                emp = roster.get(employee_id)
            except FileNotFoundError:
                return {"error": f"Employee {employee_id} not found"}
            employees = [emp]
        else:
            employees = roster.list_all(manager_id=manager_id)

        # Open manager's mailbox to check messages FROM employees
        db_path = bp / "employees" / manager_id / "mailbox.db"
        mbox = Mailbox(manager_id, db_path=db_path)

        reports = []
        try:
            unread_all = mbox.get_unread()

            for emp in employees:
                # Filter unread messages from this employee
                im_count = sum(
                    1 for m in unread_all
                    if m["from_id"] == emp.id and m["channel"] == "im"
                )
                email_count = sum(
                    1 for m in unread_all
                    if m["from_id"] == emp.id and m["channel"] == "email"
                )
                reports.append({
                    "employee_id": emp.id,
                    "nickname": emp.nickname,
                    "unread_im": im_count,
                    "unread_email": email_count,
                })
        finally:
            mbox.close()

        return {"reports": reports}

    except Exception as e:
        return {"error": str(e)}
