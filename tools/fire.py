"""Corp-Collab tool: fire — terminate an employee and generate a resume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_BASE = Path.home() / ".claude-code" / "collab"


def fire(
    employee_id: str,
    reason: str = "project_complete",
    manager_id: str | None = None,
    specialties: list[str] | None = None,
    strategies: list[str] | None = None,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Terminate an employee: generate resume, terminate, unregister.

    Args:
        employee_id: ID of the employee to fire.
        reason: Termination reason (default: project_complete).
        manager_id: ID of the firing manager (informational).
        specialties: Domain specialties demonstrated.
        strategies: General strategies the employee used well.
        base_path: Override collab base directory.

    Returns:
        Dict with employee_id, nickname, reason, resume_path.
    """
    try:
        from corp_collab.employee import Employee
        from corp_collab.roster import Roster
        from corp_collab.handoff import ResumeGenerator

        base = Path(base_path) if base_path else DEFAULT_BASE
        roster = Roster(base_path=base)

        # Load employee
        emp = roster.get(employee_id)

        # Calculate warmth for resume
        warmth = roster.calculate_warmth(emp)

        # Generate resume
        resume_gen = ResumeGenerator()
        resume = resume_gen.generate_resume(
            employee=emp,
            reason=reason,
            warmth=warmth,
            specialties=specialties,
            strategies=strategies,
        )

        # Save resume
        resume_path = resume_gen.save_resume(resume, base_path=base)

        # Terminate employee
        emp.terminate()
        emp.save(base / "employees")

        # Unregister from roster
        roster.unregister(employee_id)

        return {
            "employee_id": employee_id,
            "nickname": emp.nickname,
            "reason": reason,
            "resume_path": str(resume_path),
        }

    except Exception as exc:
        return {"error": str(exc)}
