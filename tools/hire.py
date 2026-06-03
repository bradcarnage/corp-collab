"""Corp-Collab tool: hire — create and onboard a new employee."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def hire(
    role: str,
    manager_id: str,
    skills: list[str] | None = None,
    project_id: str | None = None,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Hire a new employee: create profile, register, optionally grant project access, send welcome IM.

    Args:
        role: Employee role (researcher, engineer, analyst, reviewer, manager).
        manager_id: ID of the hiring manager.
        skills: Extra skills to grant beyond role defaults.
        project_id: Optional project to grant access to.
        base_path: Override collab base directory.

    Returns:
        Dict with employee_id, nickname, full_name, role, skills.
    """
    try:
        from corp_collab.employee import Employee
        from corp_collab.nicknames import NicknameGenerator
        from corp_collab.roster import Roster
        from corp_collab.mailbox import Mailbox
        from corp_collab.file_share import FileShare

        base = Path(base_path) if base_path else DEFAULT_BASE

        # Create employee
        nickgen = NicknameGenerator()
        roster = Roster(base_path=base)

        # Auto-register manager as employee if needed
        from corp_collab.config import get_config
        cfg = get_config(base_path=base)
        if cfg.auto_register_managers:
            roster.ensure_manager_employee(manager_id)

        # Gather existing nicknames to avoid collisions
        existing = {emp.nickname for emp in roster.list_all()}
        emp = Employee.create(role=role, hired_by=manager_id, nicknames=nickgen, existing_names=existing)

        # Grant extra skills
        if skills:
            for skill in skills:
                emp.grant_skill(skill)

        # Register (saves profile + adds to registry)
        roster.register(emp)

        # Grant project access if requested
        if project_id:
            fs = FileShare(base_path=base)
            try:
                fs.add_access(project_id, emp.id)
            except FileNotFoundError:
                pass  # project doesn't exist yet — caller can create it

        # Send welcome IM
        try:
            db_path = base / "employees" / emp.id / "mailbox.db"
            mbox = Mailbox(employee_id=emp.id, db_path=db_path)
            mbox.send(
                channel="im",
                to_id=emp.id,
                to_name=emp.full_name,
                from_id=manager_id,
                from_name=manager_id,
                body=f"Welcome aboard, {emp.nickname}! You've been hired as {role}.",
            )
            mbox.close()
        except Exception:
            pass  # messaging failure shouldn't block hiring

        return {
            "employee_id": emp.id,
            "nickname": emp.nickname,
            "full_name": emp.full_name,
            "role": emp.role,
            "skills": emp.all_skills,
        }

    except Exception as exc:
        return {"error": str(exc)}
