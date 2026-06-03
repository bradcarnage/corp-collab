"""Tests for corp_collab.handoff — burst handoffs and termination resumes."""

import pytest

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from corp_collab.handoff import (
    HandoffGenerator,
    ResumeGenerator,
    RESUME_WHITELIST,
    _is_blocked_field,
)


# ── Fake Employee ────────────────────────────────────────────────────────────


@dataclass
class FakeEmployee:
    id: str = "emp-1234"
    nickname: str = "Sparky"
    role: str = "engineer"
    title: str = "Senior Engineer"
    skills: list[str] = field(default_factory=lambda: ["terminal", "file"])
    granted_skills: list[str] = field(default_factory=lambda: ["web"])
    tasks_completed_under_manager: int = 5

    @property
    def all_skills(self) -> list[str]:
        return list(dict.fromkeys(self.skills + self.granted_skills))

    @property
    def full_name(self) -> str:
        return f"{self.title} {self.nickname}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "role": self.role,
            "skills": self.skills,
            "granted_skills": self.granted_skills,
        }


# ── HandoffGenerator ─────────────────────────────────────────────────────────


class TestHandoffGenerator:
    def test_generate_basic_handoff(self):
        content = HandoffGenerator.generate_burst_handoff(
            employee_id="emp-1234",
            what_did="Fixed the parser bug",
            what_learned="The tokenizer is fragile",
        )
        assert "# Burst Handoff — emp-1234" in content
        assert "Fixed the parser bug" in content
        assert "The tokenizer is fragile" in content

    def test_generate_with_open_threads(self):
        content = HandoffGenerator.generate_burst_handoff(
            employee_id="emp-1234",
            what_did="Done",
            what_learned="Learned",
            open_threads=["refactor tokenizer", "add edge case tests"],
        )
        assert "## Open Threads" in content
        assert "- refactor tokenizer" in content

    def test_generate_with_key_files(self):
        content = HandoffGenerator.generate_burst_handoff(
            employee_id="emp-1234",
            what_did="Done",
            what_learned="Learned",
            key_files=["src/parser.py", "tests/test_parser.py"],
        )
        assert "## Key Files" in content
        assert "`src/parser.py`" in content

    def test_generate_with_blockers(self):
        content = HandoffGenerator.generate_burst_handoff(
            employee_id="emp-1234",
            what_did="Done",
            what_learned="Learned",
            blockers=["Waiting on API key"],
        )
        assert "## Blockers" in content
        assert "⚠️ Waiting on API key" in content

    def test_save_and_load(self, tmp_path: Path):
        content = "# Test handoff"
        path = HandoffGenerator.save_burst_handoff("emp-1234", content, tmp_path)
        assert path.exists()
        assert path == tmp_path / "emp-1234" / "memory" / "handoff.md"

        loaded = HandoffGenerator.load_burst_handoff("emp-1234", tmp_path)
        assert loaded == content

    def test_load_nonexistent(self, tmp_path: Path):
        assert HandoffGenerator.load_burst_handoff("emp-9999", tmp_path) is None


# ── ResumeGenerator ──────────────────────────────────────────────────────────


class TestResumeGenerator:
    def make_employee(self) -> FakeEmployee:
        return FakeEmployee()

    def test_generate_resume_basic(self):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(emp, reason="project_complete", warmth=0.8)
        assert resume["id"] == "emp-1234"
        assert resume["nickname"] == "Sparky"
        assert resume["role"] == "engineer"
        assert resume["tasks_completed"] == 5
        assert resume["warmth_at_termination"] == 0.8
        assert resume["reason"] == "project_complete"
        assert "terminated_at" in resume

    def test_generate_resume_with_specialties(self):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(
            emp,
            reason="downsizing",
            warmth=0.5,
            specialties=["parsing", "testing"],
            strategies=["divide and conquer", "test-driven"],
        )
        assert resume["specialties_demonstrated"] == ["parsing", "testing"]
        assert "divide and conquer" in resume["strategies"]

    def test_warmth_clamped(self):
        emp = self.make_employee()
        r1 = ResumeGenerator.generate_resume(emp, "test", warmth=1.5)
        assert r1["warmth_at_termination"] == 1.0
        r2 = ResumeGenerator.generate_resume(emp, "test", warmth=-0.5)
        assert r2["warmth_at_termination"] == 0.0

    def test_resume_has_only_whitelisted_fields(self):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(emp, "test", warmth=0.5)
        for key in resume:
            assert key in RESUME_WHITELIST, f"Non-whitelisted field: {key}"

    def test_save_and_load(self, tmp_path: Path):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(emp, "test", warmth=0.7)
        path = ResumeGenerator.save_resume(resume, tmp_path)
        assert path.exists()
        assert path == tmp_path / "resumes" / "emp-1234.yaml"

        loaded = ResumeGenerator.load_resume("emp-1234", tmp_path)
        assert loaded is not None
        assert loaded["id"] == "emp-1234"

    def test_load_nonexistent(self, tmp_path: Path):
        assert ResumeGenerator.load_resume("emp-9999", tmp_path) is None

    def test_list_resumes(self, tmp_path: Path):
        for i in range(3):
            emp = FakeEmployee(id=f"emp-{i:04d}", nickname=f"Bot{i}")
            resume = ResumeGenerator.generate_resume(emp, "batch", warmth=0.5)
            ResumeGenerator.save_resume(resume, tmp_path)

        resumes = ResumeGenerator.list_resumes(tmp_path)
        assert len(resumes) == 3

    def test_list_resumes_empty_dir(self, tmp_path: Path):
        assert ResumeGenerator.list_resumes(tmp_path) == []

    def test_sanitize_for_rehire(self):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(emp, "test", warmth=0.6)
        # Inject some forbidden fields to test barrier
        resume["project_files"] = ["/secret/repo/main.py"]
        resume["credentials"] = {"api_key": "sk-xxx"}
        resume["findings"] = "Found a vulnerability"

        sanitized = ResumeGenerator.sanitize_for_rehire(resume)

        # Only whitelisted fields survive
        assert "project_files" not in sanitized
        assert "credentials" not in sanitized
        assert "findings" not in sanitized
        assert sanitized["id"] == "emp-1234"
        assert sanitized["role"] == "engineer"

    def test_sanitize_scrubs_path_strategies(self):
        emp = self.make_employee()
        resume = ResumeGenerator.generate_resume(
            emp, "test", warmth=0.5,
            strategies=["divide and conquer", "/home/user/.secret/plan.txt"],
        )
        sanitized = ResumeGenerator.sanitize_for_rehire(resume)
        assert "/home/user/.secret/plan.txt" not in sanitized["strategies"]
        assert "divide and conquer" in sanitized["strategies"]


# ── Info Barrier ─────────────────────────────────────────────────────────────


class TestInfoBarrier:
    def test_blocked_fields(self):
        assert _is_blocked_field("file_paths") is True
        assert _is_blocked_field("credentials") is True
        assert _is_blocked_field("secret_key") is True
        assert _is_blocked_field("project_name") is True

    def test_allowed_fields(self):
        assert _is_blocked_field("nickname") is False
        assert _is_blocked_field("role") is False
        assert _is_blocked_field("skills") is False
        assert _is_blocked_field("warmth_at_termination") is False
