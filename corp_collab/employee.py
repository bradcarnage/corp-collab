"""Corp-Collab: employee identity module with YAML profile lifecycle management."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .nicknames import NicknameGenerator


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SKILLS: dict[str, list[str]] = {
    "researcher": ["web", "browser"],
    "engineer": ["terminal", "file", "code_exec"],
    "analyst": ["terminal", "file"],
    "reviewer": ["file"],
    "manager": ["terminal", "file", "web"],
}

PROMOTION_TRACK: list[str] = ["intern", "role", "senior", "lead", "director"]

DEFAULT_BASE_PATH = Path.home() / ".claude-code" / "collab" / "employees"


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_id(prefix: str = "emp") -> str:
    """Generate an ID like 'emp-a7f3'."""
    return f"{prefix}-{secrets.token_hex(2)}"


# ── Employee ─────────────────────────────────────────────────────────────────


class Employee:
    """Represents a corp-collab employee with YAML-backed profile."""

    def __init__(
        self,
        id: str,
        nickname: str,
        role: str,
        hired_by: str,
        title: str = "Intern",
        skills: list[str] | None = None,
        granted_skills: list[str] | None = None,
        can_delegate: bool = False,
        max_subordinates: int = 0,
        hired_at: str | None = None,
        last_active: str | None = None,
        status: str = "onboarding",
        current_task: str | None = None,
        custom_manager_title: str | None = None,
        tasks_completed_under_manager: int = 0,
        promotion_level: str = "intern",
    ) -> None:
        self.id = id
        self.nickname = nickname
        self.role = role
        self.hired_by = hired_by
        self.title = title
        self.skills = list(skills) if skills else list(DEFAULT_SKILLS.get(role, []))
        self.granted_skills = list(granted_skills) if granted_skills else []
        self.can_delegate = can_delegate
        self.max_subordinates = max_subordinates
        self.hired_at = hired_at or _utcnow_iso()
        self.last_active = last_active or self.hired_at
        self.status = status
        self.current_task = current_task
        self.custom_manager_title = custom_manager_title
        self.tasks_completed_under_manager = tasks_completed_under_manager
        self.promotion_level = promotion_level

    # ── Factory methods ──────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        role: str,
        hired_by: str,
        nicknames: NicknameGenerator,
        existing_names: set[str] | None = None,
    ) -> Employee:
        """Factory: create a new employee with generated ID and nickname."""
        role = role.lower()
        if role not in DEFAULT_SKILLS:
            raise ValueError(f"Unknown role: {role}. Choose from {list(DEFAULT_SKILLS)}")

        prefix = "mgr" if role == "manager" else "emp"
        emp_id = _generate_id(prefix)
        nickname = nicknames.generate(role, existing_names)
        title = "Intern"
        now = _utcnow_iso()

        return cls(
            id=emp_id,
            nickname=nickname,
            role=role,
            hired_by=hired_by,
            title=title,
            skills=list(DEFAULT_SKILLS[role]),
            hired_at=now,
            last_active=now,
            status="onboarding",
            promotion_level="intern",
        )

    @classmethod
    def load(cls, employee_id: str, base_path: Path | None = None) -> Employee:
        """Load an employee profile from YAML."""
        base = base_path or DEFAULT_BASE_PATH
        profile_path = base / employee_id / "profile.yaml"
        if not profile_path.exists():
            raise FileNotFoundError(f"No profile found at {profile_path}")

        with open(profile_path, "r") as f:
            data = yaml.safe_load(f)

        return cls(
            id=data["id"],
            nickname=data["nickname"],
            role=data["role"],
            hired_by=data["hired_by"],
            title=data.get("title", "Intern"),
            skills=data.get("skills", []),
            granted_skills=data.get("granted_skills", []),
            can_delegate=data.get("can_delegate", False),
            max_subordinates=data.get("max_subordinates", 0),
            hired_at=data.get("hired_at"),
            last_active=data.get("last_active"),
            status=data.get("status", "idle"),
            current_task=data.get("current_task"),
            custom_manager_title=data.get("custom_manager_title"),
            tasks_completed_under_manager=data.get("tasks_completed_under_manager", 0),
            promotion_level=data.get("promotion_level", "intern"),
        )

    # ── Persistence ──────────────────────────────────────────────────────

    def save(self, base_path: Path | None = None) -> Path:
        """Write profile to YAML, creating directories as needed."""
        base = base_path or DEFAULT_BASE_PATH
        profile_dir = base / self.id
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_path = profile_dir / "profile.yaml"

        with open(profile_path, "w") as f:
            yaml.dump(
                self.to_dict(),
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        return profile_path

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize employee to a dictionary matching the profile schema."""
        return {
            "id": self.id,
            "nickname": self.nickname,
            "title": self.title,
            "full_name": self.full_name,
            "role": self.role,
            "skills": self.skills,
            "granted_skills": self.granted_skills,
            "can_delegate": self.can_delegate,
            "max_subordinates": self.max_subordinates,
            "hired_by": self.hired_by,
            "hired_at": self.hired_at,
            "last_active": self.last_active,
            "status": self.status,
            "current_task": self.current_task,
            "custom_manager_title": self.custom_manager_title,
            "tasks_completed_under_manager": self.tasks_completed_under_manager,
            "promotion_level": self.promotion_level,
        }

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def full_name(self) -> str:
        """Display name combining title and nickname."""
        if self.custom_manager_title:
            return f"{self.custom_manager_title} {self.nickname}"
        return f"{self.title} {self.nickname}"

    @property
    def has_renaming_rights(self) -> bool:
        """True if the employee completed >= 10 tasks under a manager."""
        return self.tasks_completed_under_manager >= 10

    @property
    def all_skills(self) -> list[str]:
        """Combined base skills and granted skills (deduplicated, ordered)."""
        seen: set[str] = set()
        result: list[str] = []
        for s in self.skills + self.granted_skills:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result

    # ── Lifecycle ────────────────────────────────────────────────────────

    def activate(self, task_id: str | None = None) -> None:
        """Transition to active status, optionally assigning a task."""
        if self.status == "terminated":
            raise RuntimeError(f"Cannot activate terminated employee {self.id}")
        self.status = "active"
        self.current_task = task_id
        self.last_active = _utcnow_iso()

    def deactivate(self) -> None:
        """Set employee to idle."""
        if self.status == "terminated":
            raise RuntimeError(f"Cannot deactivate terminated employee {self.id}")
        self.status = "idle"
        self.current_task = None
        self.last_active = _utcnow_iso()

    def terminate(self) -> None:
        """Permanently terminate the employee."""
        self.status = "terminated"
        self.current_task = None
        self.last_active = _utcnow_iso()

    # ── Promotion ────────────────────────────────────────────────────────

    def promote(self) -> str:
        """Advance to the next title in the promotion track. Returns new full_name."""
        idx = PROMOTION_TRACK.index(self.promotion_level)
        if idx >= len(PROMOTION_TRACK) - 1:
            raise ValueError(f"{self.id} is already at the highest level (director)")

        next_level = PROMOTION_TRACK[idx + 1]
        self.promotion_level = next_level

        if next_level == "role":
            self.title = self.role.capitalize()
        elif next_level == "senior":
            self.title = f"Senior {self.role.capitalize()}"
        elif next_level == "lead":
            self.title = f"Lead {self.role.capitalize()}"
            self.can_delegate = True
            self.max_subordinates = 3
        elif next_level == "director":
            self.title = "Director"
            self.can_delegate = True
            self.max_subordinates = 10

        self.last_active = _utcnow_iso()
        return self.full_name

    # ── Task tracking ────────────────────────────────────────────────────

    def complete_task(self) -> None:
        """Increment task counter; check renaming rights threshold."""
        self.tasks_completed_under_manager += 1
        self.current_task = None
        self.status = "idle"
        self.last_active = _utcnow_iso()

    # ── Skills ───────────────────────────────────────────────────────────

    def grant_skill(self, skill: str) -> None:
        """Add a skill to granted_skills if not already present."""
        if skill not in self.granted_skills and skill not in self.skills:
            self.granted_skills.append(skill)

    def revoke_skill(self, skill: str) -> None:
        """Remove a skill from granted_skills."""
        if skill in self.granted_skills:
            self.granted_skills.remove(skill)
        else:
            raise ValueError(f"Cannot revoke base skill '{skill}' — only granted skills can be revoked")

    # ── Repr ─────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<Employee {self.id} '{self.full_name}' [{self.status}]>"
