"""Tests for the employee identity module."""

import tempfile
from pathlib import Path

import pytest
import yaml

from corp_collab.employee import (
    DEFAULT_SKILLS,
    PROMOTION_TRACK,
    Employee,
)
from corp_collab.nicknames import NicknameGenerator


@pytest.fixture
def nickgen():
    return NicknameGenerator(seed=42)


@pytest.fixture
def tmp_path_factory_dir(tmp_path):
    return tmp_path / "employees"


@pytest.fixture
def researcher(nickgen):
    return Employee.create(role="researcher", hired_by="mgr-001", nicknames=nickgen)


@pytest.fixture
def engineer(nickgen):
    return Employee.create(role="engineer", hired_by="mgr-001", nicknames=nickgen)


# ── Creation ─────────────────────────────────────────────────────────────────


class TestCreate:
    def test_create_researcher(self, researcher):
        emp = researcher
        assert emp.id.startswith("emp-")
        assert len(emp.id) == 8  # emp- + 4 hex
        assert emp.nickname  # non-empty
        assert emp.role == "researcher"
        assert emp.title == "Intern"
        assert emp.full_name == f"Intern {emp.nickname}"
        assert emp.status == "onboarding"
        assert emp.hired_by == "mgr-001"
        assert emp.skills == ["web", "browser"]
        assert emp.granted_skills == []
        assert emp.can_delegate is False
        assert emp.max_subordinates == 0
        assert emp.current_task is None
        assert emp.custom_manager_title is None
        assert emp.tasks_completed_under_manager == 0

    def test_create_manager_prefix(self, nickgen):
        mgr = Employee.create(role="manager", hired_by="sys", nicknames=nickgen)
        assert mgr.id.startswith("mgr-")

    def test_create_invalid_role(self, nickgen):
        with pytest.raises(ValueError, match="Unknown role"):
            Employee.create(role="janitor", hired_by="mgr-001", nicknames=nickgen)

    def test_create_avoids_existing_names(self, nickgen):
        # Use a set of existing names
        existing = {"Curie", "Tesla"}
        emp = Employee.create(
            role="researcher", hired_by="mgr-001", nicknames=nickgen, existing_names=existing
        )
        assert emp.nickname not in existing


# ── Default skills by role ───────────────────────────────────────────────────


class TestDefaultSkills:
    @pytest.mark.parametrize("role,expected", list(DEFAULT_SKILLS.items()))
    def test_default_skills(self, nickgen, role, expected):
        emp = Employee.create(role=role, hired_by="mgr-001", nicknames=nickgen)
        assert emp.skills == expected


# ── Save / Load round-trip ───────────────────────────────────────────────────


class TestPersistence:
    def test_save_and_load(self, researcher, tmp_path_factory_dir):
        emp = researcher
        path = emp.save(base_path=tmp_path_factory_dir)
        assert path.exists()
        assert path.name == "profile.yaml"

        loaded = Employee.load(emp.id, base_path=tmp_path_factory_dir)
        assert loaded.id == emp.id
        assert loaded.nickname == emp.nickname
        assert loaded.role == emp.role
        assert loaded.title == emp.title
        assert loaded.skills == emp.skills
        assert loaded.hired_by == emp.hired_by
        assert loaded.status == emp.status

    def test_save_creates_dirs(self, researcher):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "deep" / "nested" / "employees"
            path = researcher.save(base_path=base)
            assert path.exists()

    def test_load_missing_raises(self, tmp_path_factory_dir):
        with pytest.raises(FileNotFoundError):
            Employee.load("emp-0000", base_path=tmp_path_factory_dir)

    def test_yaml_structure(self, researcher, tmp_path_factory_dir):
        researcher.save(base_path=tmp_path_factory_dir)
        profile_path = tmp_path_factory_dir / researcher.id / "profile.yaml"
        with open(profile_path) as f:
            data = yaml.safe_load(f)
        assert data["id"] == researcher.id
        assert data["full_name"] == researcher.full_name
        assert "promotion_level" in data


# ── Promotion track ──────────────────────────────────────────────────────────


class TestPromotion:
    def test_full_promotion_track(self, researcher):
        emp = researcher
        assert emp.promotion_level == "intern"
        assert emp.title == "Intern"

        # intern -> role
        name = emp.promote()
        assert emp.promotion_level == "role"
        assert emp.title == "Researcher"
        assert name == f"Researcher {emp.nickname}"

        # role -> senior
        name = emp.promote()
        assert emp.promotion_level == "senior"
        assert emp.title == "Senior Researcher"

        # senior -> lead
        name = emp.promote()
        assert emp.promotion_level == "lead"
        assert emp.title == "Lead Researcher"
        assert emp.can_delegate is True
        assert emp.max_subordinates == 3

        # lead -> director
        name = emp.promote()
        assert emp.promotion_level == "director"
        assert emp.title == "Director"
        assert emp.can_delegate is True
        assert emp.max_subordinates == 10

    def test_promote_past_director_raises(self, researcher):
        emp = researcher
        for _ in range(4):
            emp.promote()
        with pytest.raises(ValueError, match="highest level"):
            emp.promote()


# ── Lifecycle states ─────────────────────────────────────────────────────────


class TestLifecycle:
    def test_activate(self, researcher):
        emp = researcher
        emp.activate(task_id="task-001")
        assert emp.status == "active"
        assert emp.current_task == "task-001"

    def test_activate_without_task(self, researcher):
        emp = researcher
        emp.activate()
        assert emp.status == "active"
        assert emp.current_task is None

    def test_deactivate(self, researcher):
        emp = researcher
        emp.activate(task_id="task-001")
        emp.deactivate()
        assert emp.status == "idle"
        assert emp.current_task is None

    def test_terminate(self, researcher):
        emp = researcher
        emp.terminate()
        assert emp.status == "terminated"
        assert emp.current_task is None

    def test_activate_terminated_raises(self, researcher):
        emp = researcher
        emp.terminate()
        with pytest.raises(RuntimeError, match="terminated"):
            emp.activate()

    def test_deactivate_terminated_raises(self, researcher):
        emp = researcher
        emp.terminate()
        with pytest.raises(RuntimeError, match="terminated"):
            emp.deactivate()


# ── Skills ───────────────────────────────────────────────────────────────────


class TestSkills:
    def test_grant_skill(self, researcher):
        emp = researcher
        emp.grant_skill("terminal")
        assert "terminal" in emp.granted_skills
        assert "terminal" in emp.all_skills

    def test_grant_duplicate_ignored(self, researcher):
        emp = researcher
        emp.grant_skill("terminal")
        emp.grant_skill("terminal")
        assert emp.granted_skills.count("terminal") == 1

    def test_grant_base_skill_ignored(self, researcher):
        emp = researcher
        emp.grant_skill("web")  # already a base skill
        assert "web" not in emp.granted_skills

    def test_revoke_skill(self, researcher):
        emp = researcher
        emp.grant_skill("terminal")
        emp.revoke_skill("terminal")
        assert "terminal" not in emp.granted_skills

    def test_revoke_base_skill_raises(self, researcher):
        emp = researcher
        with pytest.raises(ValueError, match="base skill"):
            emp.revoke_skill("web")

    def test_all_skills_combined(self, researcher):
        emp = researcher
        emp.grant_skill("terminal")
        assert emp.all_skills == ["web", "browser", "terminal"]


# ── Renaming rights ─────────────────────────────────────────────────────────


class TestRenamingRights:
    def test_no_rights_initially(self, researcher):
        assert researcher.has_renaming_rights is False

    def test_rights_after_10_tasks(self, researcher):
        emp = researcher
        for i in range(10):
            emp.activate(task_id=f"task-{i}")
            emp.complete_task()
        assert emp.tasks_completed_under_manager == 10
        assert emp.has_renaming_rights is True

    def test_complete_task_sets_idle(self, researcher):
        emp = researcher
        emp.activate(task_id="task-001")
        emp.complete_task()
        assert emp.status == "idle"
        assert emp.current_task is None

    def test_custom_title_in_full_name(self, researcher):
        emp = researcher
        emp.custom_manager_title = "Supreme Overlord"
        assert emp.full_name == f"Supreme Overlord {emp.nickname}"


# ── to_dict ──────────────────────────────────────────────────────────────────


class TestToDict:
    def test_to_dict_keys(self, researcher):
        d = researcher.to_dict()
        expected_keys = {
            "id", "nickname", "title", "full_name", "role", "skills",
            "granted_skills", "can_delegate", "max_subordinates", "hired_by",
            "hired_at", "last_active", "status", "current_task",
            "custom_manager_title", "tasks_completed_under_manager",
            "promotion_level", "job_title",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self, researcher):
        d = researcher.to_dict()
        assert d["id"] == researcher.id
        assert d["full_name"] == researcher.full_name
        assert d["skills"] == ["web", "browser"]
