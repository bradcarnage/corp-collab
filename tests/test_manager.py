"""Tests for corp_collab.manager."""

import pytest
import yaml

from corp_collab.employee import Employee
from corp_collab.roster import Roster
from corp_collab.manager import ManagerAgent, TaskAssignment


MGR_ID = 'mgr-01'


def _make_employee(tmp_path, emp_id, role='engineer', status='idle', tasks=0, manager=MGR_ID):
    """Helper: create and register an employee."""
    emp_dir = tmp_path / 'employees' / emp_id
    emp_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        'id': emp_id,
        'nickname': f'Bot-{emp_id}',
        'title': role.capitalize(),
        'full_name': f'{role.capitalize()} Bot-{emp_id}',
        'role': role,
        'skills': ['terminal', 'file', 'code_exec'],
        'granted_skills': [],
        'can_delegate': False,
        'max_subordinates': 0,
        'hired_by': manager,
        'hired_at': '2025-01-01T00:00:00Z',
        'last_active': '2025-01-01T00:00:00Z',
        'status': status,
        'current_task': None,
        'custom_manager_title': None,
        'tasks_completed_under_manager': tasks,
        'promotion_level': 'role',
    }
    with open(emp_dir / 'profile.yaml', 'w') as f:
        yaml.dump(profile, f, default_flow_style=False)

    # Register in roster
    roster = Roster(base_path=tmp_path)
    registry = roster._load_registry()
    registry[emp_id] = {
        'role': role,
        'status': status,
        'manager_id': manager,
        'hired_at': '2025-01-01T00:00:00Z',
    }
    roster._save_registry(registry)
    return emp_id


@pytest.fixture
def mgr(tmp_path):
    return ManagerAgent(MGR_ID, base_path=tmp_path)


# ── find_best_employee ───────────────────────────────────────────────────────


def test_find_best_employee_idle_match(tmp_path, mgr):
    _make_employee(tmp_path, 'emp-01', role='engineer', status='idle', tasks=5)
    _make_employee(tmp_path, 'emp-02', role='engineer', status='idle', tasks=2)
    result = mgr.find_best_employee('engineer')
    assert result['needs_hire'] is False
    assert result['source'] == 'idle_roster'
    # Should pick emp-01 (higher warmth due to more tasks)
    assert result['employee'].id == 'emp-01'


def test_find_best_employee_skill_overlap(tmp_path, mgr):
    emp_id = _make_employee(tmp_path, 'emp-03', role='analyst', status='idle')
    # Analyst doesn't match 'researcher' role, but has skill overlap
    result = mgr.find_best_employee('researcher', skills=['terminal', 'file'])
    # No idle researchers, but emp-03 is an analyst with terminal/file skills
    assert result is not None
    # Since no role match, should fall to skill_match or new_hire
    # emp-03 is analyst (not researcher), so role_matches empty
    # Then skill overlap check: emp-03 has terminal, file -> overlap with requested skills
    assert result['source'] == 'skill_match'
    assert result['needs_hire'] is False


def test_find_best_employee_new_hire(tmp_path, mgr):
    # No employees at all
    result = mgr.find_best_employee('researcher')
    assert result['needs_hire'] is True
    assert result['source'] == 'new_hire'
    assert result['rehire'] is False


def test_find_best_employee_resume_match(tmp_path, mgr):
    # Create a resume
    resumes_dir = tmp_path / 'resumes'
    resumes_dir.mkdir(parents=True, exist_ok=True)
    resume = {
        'id': 'emp-old',
        'nickname': 'OldBot',
        'role': 'researcher',
        'skills': ['web', 'browser'],
        'tasks_completed': 10,
    }
    with open(resumes_dir / 'emp-old.yaml', 'w') as f:
        yaml.dump(resume, f)

    result = mgr.find_best_employee('researcher')
    assert result['needs_hire'] is True
    assert result['source'] == 'resume'
    assert result['rehire'] is True


# ── assign_task ──────────────────────────────────────────────────────────────


def test_assign_task_saves_and_notifies(tmp_path, mgr):
    emp_id = _make_employee(tmp_path, 'emp-10')
    task = TaskAssignment(task_id='t-1', description='Build the widget')
    result = mgr.assign_task(task, emp_id)
    assert result.assigned_to == emp_id
    assert result.status == 'assigned'
    assert result.assigned_at is not None

    # Verify task was persisted
    loaded = mgr.get_task('t-1')
    assert loaded.assigned_to == emp_id

    # Verify email notification was sent
    from corp_collab.mailbox import Mailbox
    db_path = tmp_path / 'employees' / emp_id / 'mailbox.db'
    mailbox = Mailbox(emp_id, db_path=db_path)
    unread = mailbox.get_unread('email')
    assert len(unread) >= 1
    assert 't-1' in unread[0]['subject']
    mailbox.close()


# ── accept_counter_estimate ──────────────────────────────────────────────────


def test_accept_counter_estimate(tmp_path, mgr):
    emp_id = _make_employee(tmp_path, 'emp-11')
    task = TaskAssignment(task_id='t-2', description='Research topic', estimated_minutes=30)
    mgr.assign_task(task, emp_id)
    updated = mgr.accept_counter_estimate('t-2', 45.0)
    assert updated.counter_estimate == 45.0
    assert updated.estimated_minutes == 45.0

    # Verify persistence
    reloaded = mgr.get_task('t-2')
    assert reloaded.estimated_minutes == 45.0


# ── get_task / not found ─────────────────────────────────────────────────────


def test_get_task_not_found(mgr):
    with pytest.raises(FileNotFoundError):
        mgr.get_task('t-nonexistent')


# ── list_tasks ───────────────────────────────────────────────────────────────


def test_list_tasks_filters_by_status(tmp_path, mgr):
    emp_id = _make_employee(tmp_path, 'emp-12')
    t1 = TaskAssignment(task_id='t-10', description='A')
    t2 = TaskAssignment(task_id='t-11', description='B')
    mgr.assign_task(t1, emp_id)
    mgr.assign_task(t2, emp_id)
    mgr.complete_task('t-10')

    assigned = mgr.list_tasks(status='assigned')
    completed = mgr.list_tasks(status='completed')
    all_tasks = mgr.list_tasks()
    assert len(assigned) == 1
    assert assigned[0].task_id == 't-11'
    assert len(completed) == 1
    assert completed[0].task_id == 't-10'
    assert len(all_tasks) == 2


# ── complete_task ────────────────────────────────────────────────────────────


def test_complete_task(tmp_path, mgr):
    emp_id = _make_employee(tmp_path, 'emp-13')
    task = TaskAssignment(task_id='t-20', description='Finish report')
    mgr.assign_task(task, emp_id)
    result = mgr.complete_task('t-20')
    assert result.status == 'completed'
    reloaded = mgr.get_task('t-20')
    assert reloaded.status == 'completed'


# ── roster_summary ───────────────────────────────────────────────────────────


def test_roster_summary(tmp_path, mgr):
    _make_employee(tmp_path, 'emp-20', status='idle')
    _make_employee(tmp_path, 'emp-21', status='idle')
    _make_employee(tmp_path, 'emp-22', status='active')

    summary = mgr.roster_summary()
    assert summary['total'] == 3
    assert summary['idle'] == 2
    assert summary['active'] == 1
    assert len(summary['idle_employees']) == 2
    assert len(summary['active_employees']) == 1


# ── TaskAssignment serialization ─────────────────────────────────────────────


def test_task_assignment_roundtrip():
    t = TaskAssignment(task_id='t-99', description='Test', complexity_tier='C3', estimated_minutes=60)
    d = t.to_dict()
    t2 = TaskAssignment.from_dict(d)
    assert t2.task_id == 't-99'
    assert t2.complexity_tier == 'C3'
    assert t2.estimated_minutes == 60


def test_task_assignment_from_dict_ignores_extra():
    d = {'task_id': 't-1', 'description': 'X', 'unknown_field': 'ignored'}
    t = TaskAssignment.from_dict(d)
    assert t.task_id == 't-1'
    assert not hasattr(t, 'unknown_field')
