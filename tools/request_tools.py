"""Corp-Collab tool: request_tools."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from corp_collab.mailbox import Mailbox


_DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def request_tools(
    employee_id: str,
    employee_name: str,
    manager_id: str,
    tools_requested: list[str],
    justification: str,
    base_path: Optional[Path] = None,
) -> dict:
    """Request that a manager grant specific tools/skills to an employee.

    Sends an email via the Mailbox system to the manager.

    Parameters
    ----------
    employee_id : str
        Employee making the request.
    employee_name : str
        Display name of the employee.
    manager_id : str
        Manager who can approve the tools.
    tools_requested : list[str]
        List of tool/skill names being requested.
    justification : str
        Reason for the request.
    base_path : Path, optional
        Root collab directory. Defaults to ~/.claude-code/collab.

    Returns
    -------
    dict
        {sent: True, tools_requested: [...], to: manager_id}
    """
    base = Path(base_path) if base_path else _DEFAULT_BASE
    db_path = base / "employees" / manager_id / "mailbox.db"

    mbox = Mailbox(manager_id, db_path=db_path)
    try:
        tools_list = ", ".join(tools_requested)
        body = (
            f"Tool/Skill Access Request from {employee_name} ({employee_id}):\n\n"
            f"Tools requested: {tools_list}\n\n"
            f"Justification: {justification}"
        )
        mbox.send(
            channel="email",
            to_id=manager_id,
            to_name=manager_id,
            from_id=employee_id,
            from_name=employee_name,
            body=body,
            subject=f"Tool Access Request: {tools_list}",
            priority="normal",
        )
    finally:
        mbox.close()

    return {"sent": True, "tools_requested": tools_requested, "to": manager_id}
