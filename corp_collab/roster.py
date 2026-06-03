"""Corp-Collab: roster module — employee registry with warmth scoring, retention, and resume search."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .employee import Employee, DEFAULT_BASE_PATH


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_ROSTER_BASE = Path.home() / ".claude-code" / "collab"

WARMTH_TASK_WEIGHT = 0.3
WARMTH_RECENCY_WEIGHT = -0.1
WARMTH_DOMAIN_OVERLAP = 0.5  # hardcoded for now


# ── Roster ───────────────────────────────────────────────────────────────────


class Roster:
    """Employee registry with warmth scoring, retention policy, and resume search."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or DEFAULT_ROSTER_BASE
        self.registry_path = self.base_path / "registry.yaml"
        self.employees_path = self.base_path / "employees"
        self.resumes_path = self.base_path / "resumes"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.employees_path.mkdir(parents=True, exist_ok=True)
        self.resumes_path.mkdir(parents=True, exist_ok=True)

    # ── Registry I/O ─────────────────────────────────────────────────────

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if self.registry_path.exists():
            with open(self.registry_path, "r") as f:
                data = yaml.safe_load(f)
            return data if data else {}
        return {}

    def _save_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        with open(self.registry_path, "w") as f:
            yaml.dump(registry, f, default_flow_style=False, sort_keys=False)

    # ── Core operations ──────────────────────────────────────────────────

    def register(self, employee: Employee) -> None:
        """Add an employee to the registry and save their profile."""
        registry = self._load_registry()
        registry[employee.id] = {
            "role": employee.role,
            "status": employee.status,
            "manager_id": employee.hired_by,
            "hired_at": employee.hired_at,
        }
        self._save_registry(registry)
        employee.save(self.employees_path)

    def unregister(self, employee_id: str) -> None:
        """Remove an employee from the registry."""
        registry = self._load_registry()
        if employee_id not in registry:
            raise KeyError(f"Employee {employee_id} not in registry")
        del registry[employee_id]
        self._save_registry(registry)

    def get(self, employee_id: str) -> Employee:
        """Load an employee from disk."""
        return Employee.load(employee_id, self.employees_path)

    def exists(self, employee_id: str) -> bool:
        """Check if an employee profile exists on disk."""
        return (self.employees_path / employee_id / "profile.yaml").exists()

    def ensure_manager_employee(
        self,
        manager_id: str,
        nickname: str | None = None,
        hired_by: str = "__ceo__",
    ) -> Employee:
        """Ensure a manager exists as a registered employee.

        If *manager_id* already has a profile, returns the existing employee.
        Otherwise creates a new manager-role employee with the given ID
        (preserving the caller-chosen ID instead of generating one).

        This enables managers to appear in the org chart as real nodes
        rather than virtual placeholders.
        """
        if self.exists(manager_id):
            return self.get(manager_id)

        from .nicknames import NicknameGenerator

        gen = NicknameGenerator()
        display_name = nickname or manager_id.replace("-", " ").replace("_", " ").title()

        emp = Employee(
            id=manager_id,
            nickname=display_name,
            role="manager",
            hired_by=hired_by,
            title="Manager",
            skills=list(Employee._default_skills_for("manager")),
            can_delegate=True,
            max_subordinates=10,
            status="active",
            promotion_level="lead",
        )
        self.register(emp)
        return emp

    # ── Listing ──────────────────────────────────────────────────────────

    def list_all(
        self,
        status: str | None = None,
        role: str | None = None,
        manager_id: str | None = None,
    ) -> list[Employee]:
        """List employees with optional filters on status, role, and manager_id."""
        registry = self._load_registry()
        results: list[Employee] = []

        for emp_id, meta in registry.items():
            if status and meta.get("status") != status:
                continue
            if role and meta.get("role") != role:
                continue
            if manager_id and meta.get("manager_id") != manager_id:
                continue
            try:
                emp = self.get(emp_id)
                results.append(emp)
            except FileNotFoundError:
                continue

        return results

    def list_idle(self, manager_id: str | None = None) -> list[Employee]:
        """List idle employees, optionally filtered by manager_id."""
        return self.list_all(status="idle", manager_id=manager_id)

    # ── Warmth ───────────────────────────────────────────────────────────

    def calculate_warmth(self, employee: Employee) -> float:
        """
        Calculate warmth score for an employee.

        warmth = (tasks_completed * 0.3) + (recency_days * -0.1) + (domain_overlap * 0.5)
        """
        tasks = employee.tasks_completed_under_manager
        # Calculate recency in days
        try:
            last = datetime.fromisoformat(employee.last_active.replace("Z", "+00:00"))
            recency_days = (datetime.now(timezone.utc) - last).days
        except (ValueError, AttributeError):
            recency_days = 0

        warmth = (tasks * WARMTH_TASK_WEIGHT) + (recency_days * WARMTH_RECENCY_WEIGHT) + WARMTH_DOMAIN_OVERLAP
        return round(warmth, 4)

    def find_by_warmth(
        self,
        min_warmth: float = 0.0,
        role: str | None = None,
    ) -> list[Employee]:
        """Find employees at or above a warmth threshold, sorted by warmth descending."""
        candidates = self.list_all(role=role)
        scored: list[tuple[float, Employee]] = []

        for emp in candidates:
            w = self.calculate_warmth(emp)
            if w >= min_warmth:
                scored.append((w, emp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [emp for _, emp in scored]

    # ── Retention ────────────────────────────────────────────────────────

    def get_retention_candidates(self, max_idle: int = 5) -> list[Employee]:
        """
        Return idle employees exceeding max headcount, sorted by warmth ascending.

        If there are more idle employees than max_idle, the lowest-warmth ones
        are returned as candidates for termination.
        """
        idle = self.list_idle()
        if len(idle) <= max_idle:
            return []

        scored = [(self.calculate_warmth(emp), emp) for emp in idle]
        scored.sort(key=lambda x: x[0])  # ascending warmth (coldest first)

        excess = len(idle) - max_idle
        return [emp for _, emp in scored[:excess]]

    # ── Resume search ────────────────────────────────────────────────────

    def save_resume(
        self,
        employee: Employee,
        reason: str = "unknown",
        strategies: list[str] | None = None,
    ) -> Path:
        """Save a termination resume for an employee."""
        resume = {
            "id": employee.id,
            "nickname": employee.nickname,
            "role": employee.role,
            "skills": employee.skills + employee.granted_skills,
            "tasks_completed": employee.tasks_completed_under_manager,
            "specialties_demonstrated": employee.granted_skills,
            "warmth_at_termination": self.calculate_warmth(employee),
            "reason": reason,
            "strategies": strategies or [],
        }
        resume_path = self.resumes_path / f"{employee.id}.yaml"
        with open(resume_path, "w") as f:
            yaml.dump(resume, f, default_flow_style=False, sort_keys=False)
        return resume_path

    def search_resumes(
        self,
        role: str | None = None,
        skills: list[str] | None = None,
        min_tasks: int = 0,
    ) -> list[dict]:
        """Search terminated employee resumes by role, skills, and minimum tasks."""
        results: list[dict] = []

        if not self.resumes_path.exists():
            return results

        for resume_file in self.resumes_path.glob("*.yaml"):
            with open(resume_file, "r") as f:
                resume = yaml.safe_load(f)
            if not resume:
                continue

            if role and resume.get("role") != role:
                continue
            if min_tasks and resume.get("tasks_completed", 0) < min_tasks:
                continue
            if skills:
                resume_skills = set(resume.get("skills", []))
                if not set(skills).intersection(resume_skills):
                    continue

            results.append(resume)

        return results
