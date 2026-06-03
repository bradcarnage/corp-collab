"""Corp-Collab: handoff and resume generation with cross-company info barrier."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Employee Protocol ────────────────────────────────────────────────────────

class EmployeeLike(Protocol):
    """Minimal interface for Employee objects used in resume generation."""

    id: str
    nickname: str
    role: str
    tasks_completed_under_manager: int

    @property
    def all_skills(self) -> list[str]: ...

    @property
    def full_name(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


# ── Info Barrier Whitelist ───────────────────────────────────────────────────

RESUME_WHITELIST = frozenset({
    "id",
    "nickname",
    "role",
    "skills",
    "tasks_completed",
    "specialties_demonstrated",
    "warmth_at_termination",
    "reason",
    "strategies",
    "terminated_at",
    "previous_managers",
})

# Fields that must NEVER appear in a resume (cross-company info barrier)
RESUME_BLOCKLIST_PATTERNS = (
    "file", "path", "credential", "secret", "key", "token",
    "password", "finding", "project", "repo", "url", "endpoint",
)


def _is_blocked_field(key: str) -> bool:
    """Check if a field name matches blocklist patterns."""
    key_lower = key.lower()
    return any(pat in key_lower for pat in RESUME_BLOCKLIST_PATTERNS)


# ── Burst Handoff Generator ─────────────────────────────────────────────────


class HandoffGenerator:
    """Generates markdown-formatted burst handoff documents."""

    @staticmethod
    def generate_burst_handoff(
        employee_id: str,
        what_did: str,
        what_learned: str,
        open_threads: list[str] | None = None,
        key_files: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> str:
        """Generate a markdown burst handoff document.

        Args:
            employee_id: ID of the employee handing off.
            what_did: Summary of work completed.
            what_learned: Key insights and learnings.
            open_threads: Unfinished work items.
            key_files: Important files touched or created.
            blockers: Known blockers for continuation.

        Returns:
            Markdown-formatted handoff string.
        """
        lines = [
            f"# Burst Handoff — {employee_id}",
            f"",
            f"**Generated:** {_utcnow_iso()}",
            f"",
            f"## What I Did",
            f"",
            what_did,
            f"",
            f"## What I Learned",
            f"",
            what_learned,
            f"",
        ]

        if open_threads:
            lines.append("## Open Threads")
            lines.append("")
            for thread in open_threads:
                lines.append(f"- {thread}")
            lines.append("")

        if key_files:
            lines.append("## Key Files")
            lines.append("")
            for kf in key_files:
                lines.append(f"- `{kf}`")
            lines.append("")

        if blockers:
            lines.append("## Blockers")
            lines.append("")
            for blocker in blockers:
                lines.append(f"- ⚠️ {blocker}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def save_burst_handoff(
        employee_id: str,
        content: str,
        base_path: Path | None = None,
    ) -> Path:
        """Write handoff markdown to memory/handoff.md under the employee dir.

        Returns:
            Path to the written file.
        """
        base = base_path or Path.home() / ".claude-code" / "collab" / "employees"
        handoff_dir = base / employee_id / "memory"
        handoff_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoff_dir / "handoff.md"
        handoff_path.write_text(content, encoding="utf-8")
        return handoff_path

    @staticmethod
    def load_burst_handoff(
        employee_id: str,
        base_path: Path | None = None,
    ) -> str | None:
        """Load an existing burst handoff, or return None."""
        base = base_path or Path.home() / ".claude-code" / "collab" / "employees"
        handoff_path = base / employee_id / "memory" / "handoff.md"
        if handoff_path.exists():
            return handoff_path.read_text(encoding="utf-8")
        return None


# ── Resume Generator (with info barrier) ─────────────────────────────────────


class ResumeGenerator:
    """Generates YAML termination resumes with cross-company info barrier."""

    @staticmethod
    def generate_resume(
        employee: EmployeeLike,
        reason: str,
        warmth: float,
        specialties: list[str] | None = None,
        strategies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a sanitized termination resume.

        The resume intentionally omits project-specific details,
        file paths, credentials, and findings per the info barrier policy.

        Args:
            employee: Employee being terminated.
            reason: Reason for termination.
            warmth: Manager warmth rating at termination (0.0-1.0).
            specialties: Domain specialties demonstrated.
            strategies: General strategies the employee used well.

        Returns:
            Resume dict containing only whitelisted fields.
        """
        resume: dict[str, Any] = {
            "id": employee.id,
            "nickname": employee.nickname,
            "role": employee.role,
            "skills": list(employee.all_skills),
            "tasks_completed": employee.tasks_completed_under_manager,
            "specialties_demonstrated": list(specialties) if specialties else [],
            "warmth_at_termination": max(0.0, min(1.0, warmth)),
            "reason": reason,
            "strategies": list(strategies) if strategies else [],
            "terminated_at": _utcnow_iso(),
            "previous_managers": [],
        }
        return resume

    @staticmethod
    def save_resume(
        resume: dict[str, Any],
        base_path: Path | None = None,
    ) -> Path:
        """Write resume YAML to resumes/{id}.yaml.

        Returns:
            Path to the written file.
        """
        base = base_path or Path.home() / ".claude-code" / "collab"
        resume_dir = base / "resumes"
        resume_dir.mkdir(parents=True, exist_ok=True)
        resume_path = resume_dir / f"{resume['id']}.yaml"
        with open(resume_path, "w") as f:
            yaml.dump(resume, f, default_flow_style=False, sort_keys=False)
        return resume_path

    @staticmethod
    def load_resume(
        employee_id: str,
        base_path: Path | None = None,
    ) -> dict[str, Any] | None:
        """Load a resume by employee ID, or return None."""
        base = base_path or Path.home() / ".claude-code" / "collab"
        resume_path = base / "resumes" / f"{employee_id}.yaml"
        if not resume_path.exists():
            return None
        with open(resume_path, "r") as f:
            return yaml.safe_load(f)

    @staticmethod
    def list_resumes(base_path: Path | None = None) -> list[dict[str, Any]]:
        """List all saved resumes."""
        base = base_path or Path.home() / ".claude-code" / "collab"
        resume_dir = base / "resumes"
        if not resume_dir.exists():
            return []
        resumes = []
        for path in sorted(resume_dir.glob("*.yaml")):
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                if data:
                    resumes.append(data)
        return resumes

    @staticmethod
    def sanitize_for_rehire(resume: dict[str, Any]) -> dict[str, Any]:
        """Strip resume to only whitelisted fields for cross-company rehire.

        Enforces the info barrier: no project files, specific findings,
        credentials, or file paths may cross the boundary.
        """
        sanitized: dict[str, Any] = {}
        for key in RESUME_WHITELIST:
            if key in resume:
                sanitized[key] = resume[key]

        # Double-check: remove any accidentally included blocked fields
        to_remove = [k for k in sanitized if _is_blocked_field(k)]
        for k in to_remove:
            del sanitized[k]

        # Scrub string values for path-like or credential-like content
        if "strategies" in sanitized:
            sanitized["strategies"] = [
                s for s in sanitized["strategies"]
                if not _is_blocked_field(s) and "/" not in s
            ]

        return sanitized
