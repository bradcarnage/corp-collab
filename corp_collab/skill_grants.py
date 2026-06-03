"""Corp-Collab: grantable skills system.

Manages skill grants for employees — manager grants skills at hire time
or on-demand via tool request approval. Skills map to matt-pocock collection
and other agent skills that employees can use during their work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Skill Catalog ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SkillDefinition:
    """A skill available for granting to employees."""
    name: str
    description: str
    min_level: str  # minimum promotion level required
    roles: tuple[str, ...]  # which roles can receive this skill
    category: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "min_level": self.min_level,
            "roles": list(self.roles),
            "category": self.category,
        }


# Promotion level ordering for comparisons
LEVEL_ORDER = ("intern", "role", "senior", "lead", "director")

# Built-in skill catalog (matt-pocock skills + general tools)
DEFAULT_CATALOG: dict[str, SkillDefinition] = {
    "grill-me": SkillDefinition(
        name="grill-me",
        description="Interrogate designs/implementations with relentless questions",
        min_level="intern",
        roles=("reviewer", "engineer", "researcher"),
        category="review",
    ),
    "diagnose": SkillDefinition(
        name="diagnose",
        description="Disciplined diagnosis loop for hard bugs and performance issues",
        min_level="intern",
        roles=("engineer", "debugger"),
        category="debugging",
    ),
    "tdd": SkillDefinition(
        name="tdd",
        description="Test-driven development with red-green-refactor loop",
        min_level="intern",
        roles=("engineer",),
        category="development",
    ),
    "review": SkillDefinition(
        name="review",
        description="Audit changes against spec and standards",
        min_level="intern",
        roles=("reviewer", "engineer"),
        category="review",
    ),
    "handoff": SkillDefinition(
        name="handoff",
        description="Generate handoff docs at burst end for context continuity",
        min_level="intern",
        roles=("engineer", "researcher", "reviewer", "writer", "manager"),
        category="workflow",
    ),
    "prototype": SkillDefinition(
        name="prototype",
        description="Build throwaway prototypes to validate ideas",
        min_level="intern",
        roles=("engineer",),
        category="development",
    ),
    "teach": SkillDefinition(
        name="teach",
        description="Teach concepts or skills to junior employees",
        min_level="senior",
        roles=("engineer", "researcher", "reviewer"),
        category="mentoring",
    ),
    "plan": SkillDefinition(
        name="plan",
        description="Write implementation plans with bite-sized tasks",
        min_level="role",
        roles=("engineer", "manager", "researcher"),
        category="planning",
    ),
    "spike": SkillDefinition(
        name="spike",
        description="Throwaway experiments to validate an approach",
        min_level="intern",
        roles=("engineer", "researcher"),
        category="development",
    ),
    "systematic-debugging": SkillDefinition(
        name="systematic-debugging",
        description="4-phase root cause debugging: understand before fixing",
        min_level="intern",
        roles=("engineer", "debugger"),
        category="debugging",
    ),
    "writing-plans": SkillDefinition(
        name="writing-plans",
        description="Write implementation plans with paths and code examples",
        min_level="role",
        roles=("engineer", "manager"),
        category="planning",
    ),
    "code-review": SkillDefinition(
        name="code-review",
        description="Pre-commit review: security scan, quality gates",
        min_level="role",
        roles=("reviewer", "engineer"),
        category="review",
    ),
}


# ── Grant Record ─────────────────────────────────────────────────────────────

@dataclass
class SkillGrant:
    """A skill granted to a specific employee."""
    skill_name: str
    employee_id: str
    granted_by: str  # manager who granted it
    granted_at: str = ""  # ISO timestamp
    revoked: bool = False
    revoke_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "employee_id": self.employee_id,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "revoked": self.revoked,
            "revoke_reason": self.revoke_reason,
        }


# ── Skill Grant Manager ─────────────────────────────────────────────────────

class SkillGrantManager:
    """Manages skill grants for employees.

    Skills can be:
    - Granted at hire time (auto-grant based on role)
    - Granted on-demand by manager
    - Requested by employee via tool request
    - Revoked by manager
    """

    def __init__(self, catalog: dict[str, SkillDefinition] | None = None):
        self.catalog = catalog or dict(DEFAULT_CATALOG)
        self._grants: dict[str, list[SkillGrant]] = {}  # employee_id → grants

    def _level_index(self, level: str) -> int:
        try:
            return LEVEL_ORDER.index(level)
        except ValueError:
            return 0

    def check_eligibility(
        self,
        skill_name: str,
        employee_role: str,
        employee_level: str,
    ) -> tuple[bool, str]:
        """Check if an employee is eligible for a skill.

        Returns (eligible, reason).
        """
        if skill_name not in self.catalog:
            return False, f"Skill '{skill_name}' not in catalog"

        skill = self.catalog[skill_name]

        # Check role
        if employee_role not in skill.roles:
            return False, f"Role '{employee_role}' not eligible for '{skill_name}' (requires: {', '.join(skill.roles)})"

        # Check level
        required_idx = self._level_index(skill.min_level)
        actual_idx = self._level_index(employee_level)
        if actual_idx < required_idx:
            return False, f"Level '{employee_level}' too low for '{skill_name}' (requires: {skill.min_level})"

        return True, "Eligible"

    def grant(
        self,
        skill_name: str,
        employee: Any,
        granted_by: str,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Grant a skill to an employee.

        Args:
            skill_name: skill to grant
            employee: employee object (needs .id, .role, .promotion_level)
            granted_by: ID of granting manager
            force: skip eligibility check

        Returns (success, message).
        """
        emp_id = employee.id
        role = getattr(employee, "role", "engineer")
        level = getattr(employee, "promotion_level", "intern")

        if not force:
            eligible, reason = self.check_eligibility(skill_name, role, level)
            if not eligible:
                return False, reason

        # Check for duplicate
        existing = self._grants.get(emp_id, [])
        for g in existing:
            if g.skill_name == skill_name and not g.revoked:
                return False, f"Skill '{skill_name}' already granted to {emp_id}"

        grant = SkillGrant(
            skill_name=skill_name,
            employee_id=emp_id,
            granted_by=granted_by,
        )
        self._grants.setdefault(emp_id, []).append(grant)

        return True, f"Granted '{skill_name}' to {emp_id}"

    def revoke(
        self,
        skill_name: str,
        employee_id: str,
        reason: str = "",
    ) -> tuple[bool, str]:
        """Revoke a skill from an employee."""
        grants = self._grants.get(employee_id, [])
        for g in grants:
            if g.skill_name == skill_name and not g.revoked:
                g.revoked = True
                g.revoke_reason = reason
                return True, f"Revoked '{skill_name}' from {employee_id}"
        return False, f"No active grant of '{skill_name}' for {employee_id}"

    def get_employee_skills(self, employee_id: str) -> list[str]:
        """Get list of active skill names for an employee."""
        grants = self._grants.get(employee_id, [])
        return [g.skill_name for g in grants if not g.revoked]

    def get_employee_grants(self, employee_id: str) -> list[SkillGrant]:
        """Get all grant records (active and revoked) for an employee."""
        return list(self._grants.get(employee_id, []))

    def auto_grant_for_role(
        self,
        employee: Any,
        granted_by: str,
    ) -> list[str]:
        """Auto-grant all eligible skills for an employee's role and level.

        Used at hire time.
        Returns list of granted skill names.
        """
        role = getattr(employee, "role", "engineer")
        level = getattr(employee, "promotion_level", "intern")
        granted = []

        for skill_name, skill_def in self.catalog.items():
            eligible, _ = self.check_eligibility(skill_name, role, level)
            if eligible:
                ok, _ = self.grant(skill_name, employee, granted_by)
                if ok:
                    granted.append(skill_name)

        return granted

    def process_tool_request(
        self,
        skill_name: str,
        employee: Any,
        manager_approved: bool = False,
    ) -> tuple[bool, str]:
        """Process an employee's request for a skill.

        If manager_approved, grants regardless of eligibility.
        Otherwise checks eligibility first.
        """
        if not manager_approved:
            role = getattr(employee, "role", "engineer")
            level = getattr(employee, "promotion_level", "intern")
            eligible, reason = self.check_eligibility(skill_name, role, level)
            if not eligible:
                return False, f"Request denied: {reason}. Requires manager approval."

        return self.grant(
            skill_name,
            employee,
            granted_by="manager",
            force=manager_approved,
        )

    def list_available(
        self,
        role: str | None = None,
        level: str | None = None,
        category: str | None = None,
    ) -> list[SkillDefinition]:
        """List available skills, optionally filtered."""
        results = []
        for skill in self.catalog.values():
            if category and skill.category != category:
                continue
            if role and role not in skill.roles:
                continue
            if level:
                required_idx = self._level_index(skill.min_level)
                actual_idx = self._level_index(level)
                if actual_idx < required_idx:
                    continue
            results.append(skill)
        return results

    def add_to_catalog(self, skill: SkillDefinition) -> None:
        """Add a custom skill to the catalog."""
        self.catalog[skill.name] = skill

    def remove_from_catalog(self, skill_name: str) -> bool:
        """Remove a skill from the catalog (does not revoke existing grants)."""
        if skill_name in self.catalog:
            del self.catalog[skill_name]
            return True
        return False

    def build_context_block(self, employee_id: str) -> str:
        """Build a context injection block listing employee's granted skills.

        This gets injected into the employee's burst session context.
        """
        skills = self.get_employee_skills(employee_id)
        if not skills:
            return ""

        lines = ["## Granted Skills", ""]
        for name in skills:
            if name in self.catalog:
                desc = self.catalog[name].description
                lines.append(f"- **{name}**: {desc}")
            else:
                lines.append(f"- **{name}**: (custom skill)")

        lines.append("")
        lines.append("Load any granted skill with `skill_view(name='<skill>')` before using it.")
        return "\n".join(lines)
